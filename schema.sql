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

INSERT INTO rotas (nome, destino_tp, destino_serpapi) VALUES
    ('Lisboa',    'LIS', 'LIS'),
    ('Madri',     'MAD', 'MAD'),
    ('Paris',     'PAR', 'CDG,ORY'),
    ('Roma',      'ROM', 'FCO'),
    ('Londres',   'LON', 'LHR,LGW'),
    ('Santiago',  'SCL', 'SCL'),
    ('Orlando',   'ORL', 'MCO'),
    ('Nova York', 'NYC', 'JFK,EWR')
ON CONFLICT (origem, destino_tp) DO NOTHING;

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
