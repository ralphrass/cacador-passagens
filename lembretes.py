"""Lembretes por e-mail das viagens planejadas: prazos do checklist e itens pendentes perto do embarque.

Roda uma vez por dia junto com o coletor e usa o mesmo envio do Resend dos alertas de preço.
- Item com prazo (documento ou tarefa): avisa quando faltam 7 dias e de novo na véspera; atrasado, avisa uma vez.
- Viagem a 3 dias ou menos da ida: um e-mail com roupas, mala e documentos ainda não marcados.
"""
import logging
import os
from datetime import date
from html import escape

import alertas

log = logging.getLogger("lembretes")
NOMES = {"roupa": "Roupas", "mala": "Mala", "documento": "Documentos", "tarefa": "Tarefas"}


def prazos_a_avisar(conn, hoje):
    return conn.execute(
        """SELECT i.id, v.titulo, i.tipo, i.descricao, i.prazo
           FROM itens_viagem i JOIN viagens v ON v.id = i.viagem_id
           WHERE NOT i.feito AND i.prazo IS NOT NULL AND i.prazo <= %(hoje)s::date + 7
             AND (i.avisado_em IS NULL
                  OR (i.prazo - %(hoje)s::date <= 1 AND i.avisado_em::date < i.prazo - 1))
           ORDER BY i.prazo, v.titulo""", {"hoje": hoje}).fetchall()


def viagens_proximas(conn, hoje):
    viagens = conn.execute(
        """SELECT id, titulo, ida FROM viagens
           WHERE ida BETWEEN %(hoje)s AND %(hoje)s::date + 3 AND aviso_mala_em IS NULL
           ORDER BY ida""", {"hoje": hoje}).fetchall()
    resultado = []
    for vid, titulo, ida in viagens:
        pendentes = conn.execute(
            """SELECT tipo, descricao FROM itens_viagem
               WHERE viagem_id = %s AND NOT feito AND tipo IN ('documento', 'roupa', 'mala')
               ORDER BY array_position(ARRAY['documento', 'roupa', 'mala'], tipo), id""", (vid,)).fetchall()
        resultado.append({"id": vid, "titulo": titulo, "ida": ida, "pendentes": pendentes})
    return resultado


def quando(prazo, hoje):
    dias = (prazo - hoje).days
    if dias < 0:
        return f"atrasado desde {prazo:%d/%m}"
    return {0: "hoje", 1: "amanhã"}.get(dias, f"até {prazo:%d/%m} (faltam {dias} dias)")


def montar_email(prazos, viagens, hoje):
    partes = []
    if prazos:
        linhas = "".join(f"<li><b>{escape(desc)}</b> ({escape(titulo)}): {quando(prazo, hoje)}</li>"
                         for _, titulo, _, desc, prazo in prazos)
        partes.append(f"<h3>Prazos chegando</h3><ul>{linhas}</ul>")
    for v in viagens:
        dias = (v["ida"] - hoje).days
        falta = {0: "é hoje", 1: "é amanhã"}.get(dias, f"falta{'m' if dias > 1 else ''} {dias} dias")
        if v["pendentes"]:
            itens = "".join(f"<li>{NOMES[t]}: {escape(d)}</li>" for t, d in v["pendentes"])
            corpo = f"Ainda não marcados no checklist:<ul>{itens}</ul>"
        else:
            corpo = "<p>Checklist completo. Boa viagem!</p>"
        partes.append(f"<h3>{escape(v['titulo'])}: {falta}</h3>{corpo}")
    n = len(prazos) + len(viagens)
    assunto = (f"🧳 {viagens[0]['titulo']}: a viagem está chegando" if viagens and not prazos
               else f"🧳 {n} lembrete{'s' if n > 1 else ''} de viagem")
    return assunto, "".join(partes) + "<p>Marque o que já fez na página Minhas viagens.</p>"


def processar(conn, hoje=None):
    if not (os.environ.get("RESEND_API_KEY") and os.environ.get("ALERTA_EMAIL")):
        log.info("Lembretes desligados (faltam RESEND_API_KEY ou ALERTA_EMAIL)")
        return
    hoje = hoje or date.today()
    prazos, viagens = prazos_a_avisar(conn, hoje), viagens_proximas(conn, hoje)
    if not prazos and not viagens:
        log.info("Nenhum lembrete de viagem hoje")
        return
    assunto, corpo = montar_email(prazos, viagens, hoje)
    try:
        alertas.enviar_email(assunto, corpo)
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        log.error("Falha ao enviar lembretes: %s %s", type(e).__name__, status or "")
        return
    conn.execute("UPDATE itens_viagem SET avisado_em = now() WHERE id = ANY(%s)", ([p[0] for p in prazos],))
    conn.execute("UPDATE viagens SET aviso_mala_em = now() WHERE id = ANY(%s)", ([v["id"] for v in viagens],))
    conn.commit()
    log.info("Lembretes enviados: %d prazo(s), %d viagem(ns)", len(prazos), len(viagens))
