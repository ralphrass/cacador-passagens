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

-- Lista de rotas: esta é a fonte da verdade. Para tirar uma rota, mude ativa para false
-- (o histórico dela continua no banco); para incluir, acrescente uma linha.
INSERT INTO rotas (nome, destino_tp, destino_serpapi, ativa) VALUES
    ('Lisboa',    'LIS', 'LIS',     true),
    ('Madri',     'MAD', 'MAD',     true),
    ('Paris',     'PAR', 'CDG,ORY', true),
    ('Roma',      'ROM', 'FCO',     true),
    ('Londres',   'LON', 'LHR,LGW', true),
    ('Frankfurt', 'FRA', 'FRA',     true),
    ('Munique',   'MUC', 'MUC',     true),
    ('Berlim',    'BER', 'BER',     true),
    ('Amsterdã',  'AMS', 'AMS',     true),
    ('Dublin',    'DUB', 'DUB',     true),
    ('Santiago',  'SCL', 'SCL',     false),
    ('Orlando',   'ORL', 'MCO',     false),
    ('Nova York', 'NYC', 'JFK,EWR', false)
ON CONFLICT (origem, destino_tp) DO UPDATE
    SET nome = EXCLUDED.nome, destino_serpapi = EXCLUDED.destino_serpapi, ativa = EXCLUDED.ativa;

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

-- Planejador de viagens: roteiros salvos pelo agente do chat.
CREATE TABLE IF NOT EXISTS viagens (
    id             serial PRIMARY KEY,
    criada_em      timestamptz NOT NULL DEFAULT now(),
    titulo         text NOT NULL,
    destino        text NOT NULL,          -- cidade(s), ex.: "Lisboa e Porto"
    ida            date,
    volta          date,
    pessoas        text,                   -- ex.: "casal", "2 adultos e 1 criança"
    preferencias   text,                   -- o que gostam de fazer, ritmo, orçamento
    roteiro        text,                   -- roteiro dia a dia em markdown
    aviso_mala_em  timestamptz             -- quando foi o e-mail de "faltam poucos dias"
);

-- Checklist de cada viagem: roupas, mala, documentos e tarefas com prazo.
CREATE TABLE IF NOT EXISTS itens_viagem (
    id          serial PRIMARY KEY,
    viagem_id   int  NOT NULL REFERENCES viagens(id) ON DELETE CASCADE,
    tipo        text NOT NULL CHECK (tipo IN ('roupa', 'mala', 'documento', 'tarefa')),
    descricao   text NOT NULL,
    prazo       date,                     -- até quando fazer (tarefas e documentos)
    feito       boolean NOT NULL DEFAULT false,
    avisado_em  timestamptz               -- último lembrete por e-mail
);
CREATE INDEX IF NOT EXISTS itens_viagem_viagem ON itens_viagem (viagem_id);
