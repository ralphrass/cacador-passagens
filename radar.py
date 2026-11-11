"""Dados da página Radar: o menor preço por dia de ida de cada rota, comparado com a faixa típica."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DIAS = 182          # janela do filtro de período: 26 semanas
HISTORICO = 90      # dias de coletas usados para a escala do termômetro
MAX_DESCOBERTA = 12

# código de cidade da Travelpayouts -> (nome, longitude, latitude)
CIDADES = {
    "LIS": ("Lisboa", -9.1, 38.8), "MAD": ("Madri", -3.6, 40.5), "PAR": ("Paris", 2.5, 49.0),
    "ROM": ("Roma", 12.2, 41.8), "LON": ("Londres", -0.5, 51.5), "FRA": ("Frankfurt", 8.6, 50.0),
    "MUC": ("Munique", 11.8, 48.4), "BER": ("Berlim", 13.5, 52.4), "AMS": ("Amsterdã", 4.8, 52.3),
    "DUB": ("Dublin", -6.3, 53.4), "MCZ": ("Maceió", -35.8, -9.5), "NAT": ("Natal", -35.2, -5.8),
    "AJU": ("Aracaju", -37.1, -10.9), "PFB": ("Passo Fundo", -52.3, -28.2),
    "SCL": ("Santiago", -70.8, -33.4), "ORL": ("Orlando", -81.3, 28.4), "NYC": ("Nova York", -73.8, 40.6),
    "BUE": ("Buenos Aires", -58.5, -34.8), "MVD": ("Montevidéu", -56.0, -34.8), "LIM": ("Lima", -77.1, -12.0),
    "BOG": ("Bogotá", -74.1, 4.7), "MIA": ("Miami", -80.3, 25.8), "CUN": ("Cancún", -86.9, 21.0),
    "MEX": ("Cidade do México", -99.1, 19.4), "PTY": ("Panamá", -79.4, 9.1), "ASU": ("Assunção", -57.5, -25.2),
    "CAS": ("Casablanca", -7.6, 33.4), "BCN": ("Barcelona", 2.1, 41.3), "OPO": ("Porto", -8.7, 41.2),
    "MIL": ("Milão", 9.2, 45.5), "RIO": ("Rio de Janeiro", -43.2, -22.9), "SSA": ("Salvador", -38.3, -12.9),
    "REC": ("Recife", -34.9, -8.1), "FOR": ("Fortaleza", -38.5, -3.8), "BSB": ("Brasília", -47.9, -15.9),
    "POA": ("Porto Alegre", -51.2, -30.0), "FLN": ("Florianópolis", -48.5, -27.7), "CWB": ("Curitiba", -49.2, -25.5),
    "BHZ": ("Belo Horizonte", -43.9, -19.6), "IGU": ("Foz do Iguaçu", -54.5, -25.6), "JPA": ("João Pessoa", -34.9, -7.1),
}


def hoje_em_sao_paulo():
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date()


def dados(conn, hoje=None):
    """Tudo o que a página precisa, num dicionário pronto para virar JSON."""
    hoje = hoje or hoje_em_sao_paulo()
    fim = hoje + timedelta(days=DIAS)
    rotas = {}
    for rid, nome, origem, destino in conn.execute(
            "SELECT id, nome, origem, destino_tp FROM rotas WHERE ativa ORDER BY id"):
        _, lon, lat = CIDADES.get(destino, (nome, None, None))
        origens = origem.split(",")
        rotas[rid] = {"nome": nome, "cod": f"{origens[0] if len(origens) == 1 else 'SAO'}–{destino}",
                      "lon": lon, "lat": lat, "serie": {}}

    # menor preço de cada dia de ida, na coleta mais recente da rota
    for rid, ida, volta, preco, cia, escalas in conn.execute(
            """WITH ult AS (SELECT rota_id, max(coletado_em::date) AS dia FROM precos_tp GROUP BY 1)
               SELECT DISTINCT ON (p.rota_id, p.ida) p.rota_id, p.ida, p.volta, p.preco, p.cia,
                      greatest(coalesce(p.conexoes_ida, 0), coalesce(p.conexoes_volta, 0))
               FROM precos_tp p JOIN ult u ON u.rota_id = p.rota_id AND p.coletado_em::date = u.dia
               WHERE p.ida >= %s AND p.ida < %s
               ORDER BY p.rota_id, p.ida, p.preco""", (hoje, fim)):
        if rid in rotas:
            rotas[rid]["serie"][ida.isoformat()] = [float(preco), volta.isoformat(), cia, escalas]

    # escala do termômetro e faixa de reserva, pelos preços coletados nos últimos 90 dias
    for rid, minimo, p25, p75, p95 in conn.execute(
            """SELECT rota_id, min(preco),
                      percentile_cont(0.25) WITHIN GROUP (ORDER BY preco),
                      percentile_cont(0.75) WITHIN GROUP (ORDER BY preco),
                      percentile_cont(0.95) WITHIN GROUP (ORDER BY preco)
               FROM precos_tp WHERE coletado_em >= %s::date - %s GROUP BY 1""", (hoje, HISTORICO)):
        if rid in rotas:
            rotas[rid].update(min=float(minimo), max=float(p95), faixa=[float(p25), float(p75)],
                              faixa_fonte="historico")

    # faixa típica do Google, da busca confirmada mais recente
    for rid, fmin, fmax in conn.execute(
            """SELECT DISTINCT ON (rota_id) rota_id, faixa_min, faixa_max FROM buscas
               WHERE faixa_min IS NOT NULL AND faixa_max IS NOT NULL
               ORDER BY rota_id, buscado_em DESC"""):
        if rid in rotas and "min" in rotas[rid]:
            r = rotas[rid]
            r.update(faixa=[float(fmin), float(fmax)], faixa_fonte="google",
                     min=min(r["min"], float(fmin)), max=max(r["max"], float(fmax)))

    monitorados = {r["cod"].split("–")[1] for r in rotas.values()}
    descoberta = []
    for destino, preco in conn.execute(
            """SELECT destino, min(preco) FROM descoberta
               WHERE coletado_em::date = (SELECT max(coletado_em::date) FROM descoberta)
               GROUP BY 1 ORDER BY 2"""):
        if destino in CIDADES and destino not in monitorados and len(descoberta) < MAX_DESCOBERTA:
            nome, lon, lat = CIDADES[destino]
            descoberta.append({"nome": nome, "lon": lon, "lat": lat, "preco": float(preco)})

    return {"hoje": hoje.isoformat(), "dias": DIAS,
            "rotas": [r for r in rotas.values() if r["serie"] and "min" in r],
            "descoberta": descoberta}
