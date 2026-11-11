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
-- confirmar = false: o trecho só tem o preço diário gratuito da Travelpayouts e não gasta a cota da
-- SerpApi. É assim que a lista cresce sem diluir as buscas confirmadas das rotas principais.
ALTER TABLE rotas ADD COLUMN IF NOT EXISTS confirmar boolean NOT NULL DEFAULT true;

INSERT INTO rotas (nome, origem, destino_tp, destino_serpapi, ativa, meses_ida, dias_min, dias_max, confirmar) VALUES
    ('Lisboa',      'GRU',         'LIS', 'LIS',     true,   NULL,                             NULL,  NULL,  true),
    ('Madri',       'GRU',         'MAD', 'MAD',     true,   NULL,                             NULL,  NULL,  true),
    ('Paris',       'GRU',         'PAR', 'CDG,ORY', true,   NULL,                             NULL,  NULL,  true),
    ('Roma',        'GRU',         'ROM', 'FCO',     true,   NULL,                             NULL,  NULL,  true),
    ('Londres',     'GRU',         'LON', 'LHR,LGW', true,   NULL,                             NULL,  NULL,  true),
    ('Frankfurt',   'GRU',         'FRA', 'FRA',     true,   NULL,                             NULL,  NULL,  true),
    ('Munique',     'GRU',         'MUC', 'MUC',     true,   NULL,                             NULL,  NULL,  true),
    ('Berlim',      'GRU',         'BER', 'BER',     true,   NULL,                             NULL,  NULL,  true),
    ('Amsterdã',    'GRU',         'AMS', 'AMS',     true,   NULL,                             NULL,  NULL,  true),
    ('Dublin',      'GRU',         'DUB', 'DUB',     true,   NULL,                             NULL,  NULL,  true),
    ('Maceió',      'GRU',         'MCZ', 'MCZ',     true,   '{11,12,2,3}',                    NULL,  NULL,  true),
    ('Natal',       'GRU',         'NAT', 'NAT',     true,   '{11,12,2,3}',                    NULL,  NULL,  true),
    ('Aracaju',     'GRU',         'AJU', 'AJU',     true,   '{11,12,2,3}',                    NULL,  NULL,  true),
    ('Passo Fundo', 'GRU,CGH,VCP', 'PFB', 'PFB',     true,   '{1,2,3,4,5,6,7,8,9,10,11,12}',   2,     15,  true),
    ('Santiago',    'GRU',         'SCL', 'SCL',     false,  NULL,                             NULL,  NULL,  true),
    ('Orlando',     'GRU',         'ORL', 'MCO',     false,  NULL,                             NULL,  NULL,  true),
    ('Nova York',   'GRU',         'NYC', 'JFK,EWR', false,  NULL,                             NULL,  NULL,  true),
    ('Barcelona', 'GRU', 'BCN', 'BCN', true, NULL, NULL, NULL, false),
    ('Milão', 'GRU', 'MIL', 'MXP', true, NULL, NULL, NULL, false),
    ('Porto', 'GRU', 'OPO', 'OPO', true, NULL, NULL, NULL, false),
    ('Zurique', 'GRU', 'ZRH', 'ZRH', true, NULL, NULL, NULL, false),
    ('Viena', 'GRU', 'VIE', 'VIE', true, NULL, NULL, NULL, false),
    ('Atenas', 'GRU', 'ATH', 'ATH', true, NULL, NULL, NULL, false),
    ('Istambul', 'GRU', 'IST', 'IST', true, NULL, NULL, NULL, false),
    ('Salvador', 'GRU', 'SSA', 'SSA', true, NULL, 3, 15, false),
    ('Recife', 'GRU', 'REC', 'REC', true, NULL, 3, 15, false),
    ('Fortaleza', 'GRU', 'FOR', 'FOR', true, NULL, 3, 15, false),
    ('Florianópolis', 'GRU', 'FLN', 'FLN', true, NULL, 3, 15, false),
    ('Porto Alegre', 'GRU', 'POA', 'POA', true, NULL, 3, 15, false),
    ('Foz do Iguaçu', 'GRU', 'IGU', 'IGU', true, NULL, 3, 15, false),
    ('Buenos Aires', 'GRU', 'BUE', 'EZE,AEP', true, NULL, 3, 15, false),
    ('Montevidéu', 'GRU', 'MVD', 'MVD', true, NULL, 3, 15, false),
    ('Lima', 'GRU', 'LIM', 'LIM', true, NULL, NULL, NULL, false),
    ('Bogotá', 'GRU', 'BOG', 'BOG', true, NULL, NULL, NULL, false),
    ('Miami', 'GRU', 'MIA', 'MIA', true, NULL, NULL, NULL, false),
    ('Cancún', 'GRU', 'CUN', 'CUN', true, NULL, NULL, NULL, false)
ON CONFLICT (origem, destino_tp) DO UPDATE
    SET nome = EXCLUDED.nome, destino_serpapi = EXCLUDED.destino_serpapi,
        ativa = EXCLUDED.ativa, meses_ida = EXCLUDED.meses_ida, ida_de = NULL,
        dias_min = EXCLUDED.dias_min, dias_max = EXCLUDED.dias_max,
        confirmar = EXCLUDED.confirmar;

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

-- Alertas criados pelo usuário no site: avisa quando o trecho tiver ida nos meses escolhidos
-- (1 a 12; mes_de > mes_ate atravessa a virada do ano) por até preco_max.
CREATE TABLE IF NOT EXISTS regras_alerta (
    id         serial PRIMARY KEY,
    criada_em  timestamptz NOT NULL DEFAULT now(),
    rota_id    int NOT NULL REFERENCES rotas(id),
    preco_max  numeric(10,2) NOT NULL,
    mes_de     int NOT NULL,
    mes_ate    int NOT NULL
);

-- Avisos enviados por causa de uma regra (o histórico fica mesmo se a regra for removida).
CREATE TABLE IF NOT EXISTS avisos_regra (
    id          bigserial PRIMARY KEY,
    enviado_em  timestamptz NOT NULL DEFAULT now(),
    regra_id    int REFERENCES regras_alerta(id) ON DELETE SET NULL,
    rota_id     int NOT NULL REFERENCES rotas(id),
    ida         date NOT NULL,
    volta       date NOT NULL,
    preco       numeric(10,2) NOT NULL,
    preco_max   numeric(10,2) NOT NULL
);

-- Diário das coletas, para a tela de auditoria.
CREATE TABLE IF NOT EXISTS coletas (
    id                 bigserial PRIMARY KEY,
    iniciada_em        timestamptz NOT NULL,
    terminada_em       timestamptz NOT NULL DEFAULT now(),
    trechos_ativos     int NOT NULL,
    trechos_com_preco  int NOT NULL,
    precos             int NOT NULL,
    buscas             int NOT NULL,
    avisos             int NOT NULL
);
