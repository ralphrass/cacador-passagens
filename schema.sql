-- Esquema do coletor de preços. Pode rodar várias vezes (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS rotas (
    id                 serial PRIMARY KEY,
    nome               text NOT NULL,
    origem             text NOT NULL DEFAULT 'GRU',
    destino_tp         text NOT NULL,   -- código de cidade na Travelpayouts (ex.: PAR)
    destino_serpapi    text NOT NULL,   -- aeroportos na SerpApi (ex.: CDG,ORY)
    ativa              boolean NOT NULL DEFAULT true,
    UNIQUE (origem, destino_tp)
);

-- Preços em cache da Travelpayouts (ida e volta, 7 a 15 dias), um retrato por coleta.
CREATE TABLE IF NOT EXISTS precos_tp (
    id              bigserial PRIMARY KEY,
    coletado_em     timestamptz NOT NULL DEFAULT now(),
    rota_id         int NOT NULL REFERENCES rotas(id),
    ida             date NOT NULL,
    volta           date NOT NULL,
    dias            int  NOT NULL,
    preco           numeric(10,2) NOT NULL,
    cia             text,
    conexoes_ida    int,
    conexoes_volta  int,
    link            text
);
CREATE INDEX IF NOT EXISTS precos_tp_rota_data ON precos_tp (rota_id, coletado_em);

-- "De GRU para qualquer lugar": destinos mais baratos do momento.
CREATE TABLE IF NOT EXISTS descoberta (
    id           bigserial PRIMARY KEY,
    coletado_em  timestamptz NOT NULL DEFAULT now(),
    destino      text NOT NULL,
    ida          date,
    volta        date,
    preco        numeric(10,2) NOT NULL,
    conexoes     int
);
CREATE INDEX IF NOT EXISTS descoberta_data ON descoberta (coletado_em);

-- Cada busca paga (SerpApi / Google Flights).
CREATE TABLE IF NOT EXISTS buscas (
    id           bigserial PRIMARY KEY,
    buscado_em   timestamptz NOT NULL DEFAULT now(),
    rota_id      int NOT NULL REFERENCES rotas(id),
    ida          date NOT NULL,
    volta        date NOT NULL,
    motivo       text NOT NULL,      -- agenda | queda | padrao
    menor_preco  numeric(10,2),
    nivel        text,               -- low | typical | high
    faixa_min    numeric(10,2),
    faixa_max    numeric(10,2),
    resposta     jsonb
);
CREATE INDEX IF NOT EXISTS buscas_rota_data ON buscas (rota_id, buscado_em);

CREATE TABLE IF NOT EXISTS ofertas (
    id           bigserial PRIMARY KEY,
    busca_id     bigint NOT NULL REFERENCES buscas(id) ON DELETE CASCADE,
    preco        numeric(10,2),
    cias         text,
    trajeto      text,               -- ex.: GRU > MAD > LIS
    escalas      int,
    duracao_min  int,
    partida      timestamp
);

-- Histórico diário que o Google devolve junto com cada busca (~60 dias).
CREATE TABLE IF NOT EXISTS historico_google (
    rota_id  int  NOT NULL REFERENCES rotas(id),
    ida      date NOT NULL,
    volta    date NOT NULL,
    dia      date NOT NULL,
    preco    numeric(10,2) NOT NULL,
    PRIMARY KEY (rota_id, ida, volta, dia)
);

-- Janela de ida própria da rota para as buscas na SerpApi (vazia = janela global IDA_DE/IDA_ATE).
ALTER TABLE rotas ADD COLUMN IF NOT EXISTS ida_de date;
ALTER TABLE rotas ADD COLUMN IF NOT EXISTS ida_ate date;
-- Meses de ida aceitos pela rota (1 a 12). Quando preenchido, substitui a janela.
ALTER TABLE rotas ADD COLUMN IF NOT EXISTS meses_ida int[];
ALTER TABLE rotas ADD COLUMN IF NOT EXISTS dias_min int;
ALTER TABLE rotas ADD COLUMN IF NOT EXISTS dias_max int;

-- Lista de rotas: esta é a fonte da verdade. Para tirar uma rota, mude ativa para false
-- (o histórico dela continua no banco); para incluir, acrescente uma linha. meses_ida limita as
-- idas daquela rota a certos meses (ex.: Nordeste em nov, dez, fev e mar, sem janeiro).
-- Passo Fundo: qualquer mês (visitas à família), saindo de qualquer aeroporto de São Paulo,
-- viagens de 2 a 15 dias. Nas demais rotas, dias_min/dias_max vazios = 7 a 15 dias.
INSERT INTO rotas (nome, origem, destino_tp, destino_serpapi, ativa, meses_ida, dias_min, dias_max) VALUES
    ('Lisboa',      'GRU',         'LIS', 'LIS',     true,   NULL,                             NULL,  NULL),
    ('Madri',       'GRU',         'MAD', 'MAD',     true,   NULL,                             NULL,  NULL),
    ('Paris',       'GRU',         'PAR', 'CDG,ORY', true,   NULL,                             NULL,  NULL),
    ('Roma',        'GRU',         'ROM', 'FCO',     true,   NULL,                             NULL,  NULL),
    ('Londres',     'GRU',         'LON', 'LHR,LGW', true,   NULL,                             NULL,  NULL),
    ('Frankfurt',   'GRU',         'FRA', 'FRA',     true,   NULL,                             NULL,  NULL),
    ('Munique',     'GRU',         'MUC', 'MUC',     true,   NULL,                             NULL,  NULL),
    ('Berlim',      'GRU',         'BER', 'BER',     true,   NULL,                             NULL,  NULL),
    ('Amsterdã',    'GRU',         'AMS', 'AMS',     true,   NULL,                             NULL,  NULL),
    ('Dublin',      'GRU',         'DUB', 'DUB',     true,   NULL,                             NULL,  NULL),
    ('Maceió',      'GRU',         'MCZ', 'MCZ',     true,   '{11,12,2,3}',                    NULL,  NULL),
    ('Natal',       'GRU',         'NAT', 'NAT',     true,   '{11,12,2,3}',                    NULL,  NULL),
    ('Aracaju',     'GRU',         'AJU', 'AJU',     true,   '{11,12,2,3}',                    NULL,  NULL),
    ('Passo Fundo', 'GRU,CGH,VCP', 'PFB', 'PFB',     true,   '{1,2,3,4,5,6,7,8,9,10,11,12}',   2,     15),
    ('Santiago',    'GRU',         'SCL', 'SCL',     false,  NULL,                             NULL,  NULL),
    ('Orlando',     'GRU',         'ORL', 'MCO',     false,  NULL,                             NULL,  NULL),
    ('Nova York',   'GRU',         'NYC', 'JFK,EWR', false,  NULL,                             NULL,  NULL)
ON CONFLICT (origem, destino_tp) DO UPDATE
    SET nome = EXCLUDED.nome, destino_serpapi = EXCLUDED.destino_serpapi,
        ativa = EXCLUDED.ativa, meses_ida = EXCLUDED.meses_ida, ida_de = NULL,
        dias_min = EXCLUDED.dias_min, dias_max = EXCLUDED.dias_max;

-- Alertas já enviados, para não repetir o mesmo aviso todo dia.
CREATE TABLE IF NOT EXISTS alertas (
    id          bigserial PRIMARY KEY,
    enviado_em  timestamptz NOT NULL DEFAULT now(),
    busca_id    bigint NOT NULL REFERENCES buscas(id),
    rota_id     int  NOT NULL REFERENCES rotas(id),
    ida         date NOT NULL,
    volta       date NOT NULL,
    preco       numeric(10,2) NOT NULL,
    motivo      text NOT NULL
);
CREATE INDEX IF NOT EXISTS alertas_rota ON alertas (rota_id, ida, volta);
