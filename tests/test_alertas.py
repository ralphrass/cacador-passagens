from datetime import date

import alertas
from tests.test_coletor import conn, rotas  # noqa: F401  (fixture e helper)


def busca(conn, rota_id, preco, nivel="typical", faixa=(3800, 4550), ida=date(2027, 2, 1)):
    return conn.execute(
        """INSERT INTO buscas (rota_id, ida, volta, motivo, menor_preco, nivel, faixa_min, faixa_max)
           VALUES (%s, %s, %s, 'agenda', %s, %s, %s, %s) RETURNING id""",
        (rota_id, ida, date(2027, 2, 14), preco, nivel, *faixa)).fetchone()[0]


def test_regras_de_alerta(conn):
    lis, mad, par = [r[0] for r in rotas(conn)[:3]]
    busca(conn, lis, 4200)                      # típico: sem alerta
    busca(conn, mad, 3500)                      # abaixo da faixa
    busca(conn, par, 4300, nivel="low")         # Google diz low
    for p in (5000, 5100, 4900):                # histórico de Lisboa
        busca(conn, lis, p, faixa=(None, None), ida=date(2027, 3, 1))
    busca(conn, lis, 4000, faixa=(None, None), ida=date(2027, 3, 1))  # 20% abaixo da mediana
    achados = alertas.encontrar_alertas(conn, 0)
    assert sorted(a["nome"] for a in achados) == ["Lisboa", "Madri", "Paris"]
    assunto, corpo = alertas.montar_email(achados)
    assert assunto == "✈️ 3 preços bons hoje"
    assert "Madri: R$ 3.500" in corpo and "abaixo da faixa típica (a partir de R$ 3.800)" in corpo
    assert "Flights+to+MAD+from+GRU" in corpo


def test_nao_repete_alerta_sem_nova_queda(conn, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "x")
    monkeypatch.setenv("ALERTA_EMAIL", "eu@exemplo.com")
    enviados = []
    monkeypatch.setattr(alertas, "enviar_email", lambda a, c: enviados.append(a))
    mad = rotas(conn)[1][0]
    busca(conn, mad, 3500)
    alertas.processar(conn, 0)
    ultimo = busca(conn, mad, 3450)             # só 1,4% mais barato: não repete
    alertas.processar(conn, ultimo - 1)
    ultimo = busca(conn, mad, 3200)             # mais 7%: avisa de novo
    alertas.processar(conn, ultimo - 1)
    assert enviados == ["✈️ Madri por R$ 3.500", "✈️ Madri por R$ 3.200"]


def test_sem_chave_nao_envia(conn, monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setattr(alertas, "enviar_email", lambda *a: (_ for _ in ()).throw(AssertionError))
    busca(conn, rotas(conn)[1][0], 3000)
    alertas.processar(conn, 0)
