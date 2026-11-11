"""Dados do site: trechos com preços e histórico, alertas e o diário das coletas."""
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

FUTURO = 180        # dias de ida à frente mostrados no site
HISTORICO = 90      # dias de coletas no gráfico de histórico
SP = ZoneInfo("America/Sao_Paulo")

# código de cidade da Travelpayouts -> (longitude, latitude), para o mapa
COORDENADAS = {
    "LIS": (-9.1, 38.8), "MAD": (-3.6, 40.5), "PAR": (2.5, 49.0), "ROM": (12.2, 41.8), "LON": (-0.5, 51.5),
    "FRA": (8.6, 50.0), "MUC": (11.8, 48.4), "BER": (13.5, 52.4), "AMS": (4.8, 52.3), "DUB": (-6.3, 53.4),
    "BCN": (2.1, 41.3), "MIL": (9.2, 45.5), "OPO": (-8.7, 41.2), "ZRH": (8.5, 47.4), "VIE": (16.4, 48.2),
    "ATH": (23.7, 38.0), "IST": (28.8, 41.0),
    "MCZ": (-35.8, -9.5), "NAT": (-35.2, -5.8), "AJU": (-37.1, -10.9), "SSA": (-38.3, -12.9),
    "REC": (-34.9, -8.1), "FOR": (-38.5, -3.8), "PFB": (-52.3, -28.2), "FLN": (-48.5, -27.7),
    "POA": (-51.2, -30.0), "IGU": (-54.5, -25.6),
    "BUE": (-58.5, -34.8), "MVD": (-56.0, -34.8), "SCL": (-70.8, -33.4), "LIM": (-77.1, -12.0),
    "BOG": (-74.1, 4.7), "MIA": (-80.3, 25.8), "NYC": (-73.8, 40.6), "ORL": (-81.3, 28.4), "CUN": (-86.9, 21.0),
}


def hoje_em_sao_paulo():
    return datetime.now(SP).date()


def trechos(conn, hoje):
    """Trechos ativos com o preço por dia de ida (coleta mais recente) e o menor preço de cada coleta."""
    rotas = {}
    for rid, nome, origem, destino, confirmar in conn.execute(
            "SELECT id, nome, origem, destino_tp, confirmar FROM rotas WHERE ativa ORDER BY nome"):
        lon, lat = COORDENADAS.get(destino, (None, None))
        origens = origem.split(",")
        rotas[rid] = {"id": rid, "cod": destino, "origem": origens[0] if len(origens) == 1 else "SAO",
                      "nome": nome, "lon": lon, "lat": lat, "confirmar": confirmar,
                      "futuro": {}, "historico": [], "google": None}

    for rid, ida, volta, preco, cia, escalas in conn.execute(
            """WITH ult AS (SELECT rota_id, max(coletado_em::date) AS dia FROM precos_tp GROUP BY 1)
               SELECT DISTINCT ON (p.rota_id, p.ida) p.rota_id, p.ida, p.volta, p.preco, p.cia,
                      greatest(coalesce(p.conexoes_ida, 0), coalesce(p.conexoes_volta, 0))
               FROM precos_tp p JOIN ult u ON u.rota_id = p.rota_id AND p.coletado_em::date = u.dia
               WHERE p.ida > %s AND p.ida <= %s
               ORDER BY p.rota_id, p.ida, p.preco""", (hoje, hoje + timedelta(days=FUTURO))):
        if rid in rotas:
            rotas[rid]["futuro"][ida.isoformat()] = [float(preco), volta.isoformat(), cia, escalas]

    for rid, dia, preco in conn.execute(
            """SELECT rota_id, coletado_em::date, min(preco) FROM precos_tp
               WHERE coletado_em >= %s::date - %s GROUP BY 1, 2 ORDER BY 2""", (hoje, HISTORICO)):
        if rid in rotas:
            rotas[rid]["historico"].append([dia.isoformat(), float(preco)])

    for rid, em, ida, volta, preco, nivel, fmin, fmax in conn.execute(
            """SELECT DISTINCT ON (rota_id) rota_id, buscado_em, ida, volta, menor_preco, nivel, faixa_min, faixa_max
               FROM buscas WHERE menor_preco IS NOT NULL ORDER BY rota_id, buscado_em DESC"""):
        if rid in rotas:
            rotas[rid]["google"] = {
                "em": em.astimezone(SP).date().isoformat(), "ida": ida.isoformat(), "volta": volta.isoformat(),
                "preco": float(preco), "nivel": nivel,
                "faixa": [float(fmin), float(fmax)] if fmin is not None and fmax is not None else None}
    return list(rotas.values())


def alertas(conn):
    regras = [{"id": i, "rota_id": r, "preco_max": float(p), "mes_de": de, "mes_ate": ate}
              for i, r, p, de, ate in conn.execute(
                  "SELECT id, rota_id, preco_max, mes_de, mes_ate FROM regras_alerta ORDER BY id")]
    avisos = [{"em": em.astimezone(SP).date().isoformat(), "rota_id": r, "ida": ida.isoformat(),
               "volta": volta.isoformat(), "preco": float(p), "motivo": m}
              for em, r, ida, volta, p, m in conn.execute(
                  """SELECT enviado_em, rota_id, ida, volta, preco, motivo FROM alertas
                     UNION ALL
                     SELECT enviado_em, rota_id, ida, volta, preco,
                            'abaixo do seu limite de R$ ' || round(preco_max)::text FROM avisos_regra
                     ORDER BY 1 DESC LIMIT 30""")]
    return regras, avisos


def coletas(conn, hoje):
    """Diário dos últimos 14 dias. Coletas anteriores à tabela `coletas` aparecem só com as contagens."""
    dias = [{"dia": d.isoformat(), "precos": precos, "trechos": tr, "buscas": b, "avisos": a,
             "trechos_ativos": ativos,
             "hora": inicio.astimezone(SP).strftime("%H:%M") if inicio else None}
            for d, precos, tr, b, a, ativos, inicio in conn.execute(
                """WITH p AS (SELECT (coletado_em AT TIME ZONE 'America/Sao_Paulo')::date AS dia,
                                     count(*) AS precos, count(DISTINCT rota_id) AS trechos
                              FROM precos_tp WHERE coletado_em >= %(h)s::date - 14 GROUP BY 1),
                        b AS (SELECT (buscado_em AT TIME ZONE 'America/Sao_Paulo')::date AS dia, count(*) AS n
                              FROM buscas WHERE buscado_em >= %(h)s::date - 14 GROUP BY 1),
                        a AS (SELECT dia, count(*) AS n FROM (
                                  SELECT (enviado_em AT TIME ZONE 'America/Sao_Paulo')::date AS dia FROM alertas
                                  UNION ALL
                                  SELECT (enviado_em AT TIME ZONE 'America/Sao_Paulo')::date FROM avisos_regra) x
                              GROUP BY 1),
                        c AS (SELECT DISTINCT ON (dia) (iniciada_em AT TIME ZONE 'America/Sao_Paulo')::date AS dia,
                                     trechos_ativos, iniciada_em
                              FROM coletas ORDER BY dia, iniciada_em DESC)
                   SELECT p.dia, p.precos, p.trechos, coalesce(b.n, 0), coalesce(a.n, 0),
                          c.trechos_ativos, c.iniciada_em
                   FROM p LEFT JOIN b USING (dia) LEFT JOIN a USING (dia) LEFT JOIN c USING (dia)
                   ORDER BY p.dia DESC""", {"h": hoje})]
    buscas = [{"em": em.astimezone(SP).date().isoformat(), "rota_id": r, "ida": ida.isoformat(),
               "volta": volta.isoformat(), "motivo": m, "preco": float(p) if p is not None else None, "nivel": n}
              for em, r, ida, volta, m, p, n in conn.execute(
                  """SELECT buscado_em, rota_id, ida, volta, motivo, menor_preco, nivel
                     FROM buscas ORDER BY buscado_em DESC LIMIT 15""")]
    no_mes = conn.execute(
        "SELECT count(*) FROM buscas WHERE buscado_em >= date_trunc('month', %s::date)", (hoje,)).fetchone()[0]
    return {"dias": dias, "buscas": buscas, "buscas_no_mes": no_mes,
            "limite_mensal": int(os.environ.get("LIMITE_MENSAL_SERPAPI", 220))}


def dados(conn, hoje=None):
    hoje = hoje or hoje_em_sao_paulo()
    regras, avisos = alertas(conn)
    return {"hoje": hoje.isoformat(), "futuro": FUTURO, "trechos": trechos(conn, hoje),
            "regras": regras, "avisos": avisos, "coletas": coletas(conn, hoje)}


def criar_regra(conn, rota_id, preco_max, mes_de, mes_ate):
    if not conn.execute("SELECT 1 FROM rotas WHERE id = %s AND ativa", (rota_id,)).fetchone():
        return None
    return conn.execute(
        "INSERT INTO regras_alerta (rota_id, preco_max, mes_de, mes_ate) VALUES (%s, %s, %s, %s) RETURNING id",
        (rota_id, preco_max, mes_de, mes_ate)).fetchone()[0]


def remover_regra(conn, regra_id):
    return conn.execute("DELETE FROM regras_alerta WHERE id = %s", (regra_id,)).rowcount > 0
