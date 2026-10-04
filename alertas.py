"""Alertas por e-mail (Resend) para preços bons confirmados na SerpApi.

Uma busca vira alerta quando:
- o Google classifica o preço como "low", ou
- o menor preço fica abaixo da faixa típica do Google, ou
- o menor preço cai mais de 15% em relação à mediana das buscas anteriores da rota.

O mesmo trecho (rota + datas) só é avisado de novo se o preço cair mais 5%.
"""
import html
import logging
import os
import statistics
from decimal import Decimal

import requests

log = logging.getLogger("coletor")

QUEDA = Decimal("0.85")
NOVA_QUEDA = Decimal("0.95")
REMETENTE_PADRAO = "Caçador de Passagens <onboarding@resend.dev>"


def brl(valor):
    return "R$ " + f"{valor:,.0f}".replace(",", ".")


def motivo_alerta(conn, busca):
    """Devolve o motivo do alerta para esta busca, ou None."""
    _, rota_id, _, _, preco, nivel, faixa_min, _ = busca
    if preco is None:
        return None
    if nivel == "low":
        return "preço baixo segundo o Google"
    if faixa_min is not None and preco < faixa_min:
        return f"abaixo da faixa típica (a partir de {brl(faixa_min)})"
    anteriores = [r[0] for r in conn.execute(
        """SELECT menor_preco FROM buscas
           WHERE rota_id = %s AND id < %s AND menor_preco IS NOT NULL""",
        (rota_id, busca[0]))]
    if len(anteriores) >= 3:
        mediana = statistics.median(anteriores)
        if preco < QUEDA * mediana:
            return f"{(1 - preco / mediana) * 100:.0f}% abaixo da mediana das buscas ({brl(mediana)})"
    return None


def ja_avisado(conn, rota_id, ida, volta, preco):
    ultimo = conn.execute(
        """SELECT preco FROM alertas WHERE rota_id = %s AND ida = %s AND volta = %s
           ORDER BY enviado_em DESC LIMIT 1""", (rota_id, ida, volta)).fetchone()
    return ultimo is not None and preco >= NOVA_QUEDA * ultimo[0]


def encontrar_alertas(conn, desde_id):
    """Alertas das buscas com id > desde_id (as feitas nesta execução)."""
    buscas = conn.execute(
        """SELECT id, rota_id, ida, volta, menor_preco, nivel, faixa_min, faixa_max
           FROM buscas WHERE id > %s ORDER BY id""", (desde_id,)).fetchall()
    achados = []
    for b in buscas:
        motivo = motivo_alerta(conn, b)
        if motivo and not ja_avisado(conn, b[1], b[2], b[3], b[4]):
            nome, aeroportos = conn.execute(
                "SELECT nome, destino_serpapi FROM rotas WHERE id = %s", (b[1],)).fetchone()
            oferta = conn.execute(
                """SELECT cias, trajeto, duracao_min FROM ofertas
                   WHERE busca_id = %s ORDER BY preco NULLS LAST LIMIT 1""", (b[0],)).fetchone()
            achados.append({"busca_id": b[0], "rota_id": b[1], "nome": nome, "aeroporto": aeroportos.split(",")[0], "ida": b[2],
                            "volta": b[3], "preco": b[4], "faixa": (b[6], b[7]),
                            "motivo": motivo, "oferta": oferta})
    return achados


def montar_email(achados):
    def link(a):
        return ("https://www.google.com/travel/flights?hl=pt-BR&curr=BRL&q="
                + f"Flights+to+{a['aeroporto']}+from+GRU+on+{a['ida']}+through+{a['volta']}")

    achados = sorted(achados, key=lambda a: a["preco"])
    linhas = []
    for a in achados:
        detalhe = ""
        if a["oferta"]:
            cias, trajeto, duracao = a["oferta"]
            detalhe = f"<br><small>{html.escape(cias or '')} · {html.escape(trajeto or '')}"
            if duracao:
                detalhe += f" · {duracao // 60}h{duracao % 60:02d}"
            detalhe += "</small>"
        linhas.append(
            f"<li><b>{html.escape(a['nome'])}: {brl(a['preco'])}</b> "
            f"({a['ida']:%d/%m/%Y} a {a['volta']:%d/%m/%Y})<br>"
            f"{html.escape(a['motivo'])}{detalhe}<br>"
            f"<a href=\"{link(a)}\">Ver no Google Flights</a></li>")
    assunto = (f"✈️ {achados[0]['nome']} por {brl(achados[0]['preco'])}"
               if len(achados) == 1 else f"✈️ {len(achados)} preços bons hoje")
    corpo = f"<p>O coletor encontrou:</p><ul>{''.join(linhas)}</ul>"
    return assunto, corpo


def enviar_email(assunto, corpo):
    resp = requests.post("https://api.resend.com/emails", headers={
        "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
    }, json={
        "from": os.environ.get("ALERTA_REMETENTE", REMETENTE_PADRAO),
        "to": [e.strip() for e in os.environ["ALERTA_EMAIL"].split(",")],
        "subject": assunto,
        "html": corpo,
    }, timeout=30)
    resp.raise_for_status()


def processar(conn, desde_id):
    if not (os.environ.get("RESEND_API_KEY") and os.environ.get("ALERTA_EMAIL")):
        log.info("Alertas desligados (faltam RESEND_API_KEY ou ALERTA_EMAIL)")
        return
    achados = encontrar_alertas(conn, desde_id)
    if not achados:
        log.info("Nenhum alerta hoje")
        return
    assunto, corpo = montar_email(achados)
    try:
        enviar_email(assunto, corpo)
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        log.error("Falha ao enviar e-mail: %s %s", type(e).__name__, status or "")
        return
    for a in achados:
        conn.execute(
            """INSERT INTO alertas (busca_id, rota_id, ida, volta, preco, motivo)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (a["busca_id"], a["rota_id"], a["ida"], a["volta"], a["preco"], a["motivo"]))
    conn.commit()
    log.info("Alerta enviado: %d preço(s)", len(achados))
