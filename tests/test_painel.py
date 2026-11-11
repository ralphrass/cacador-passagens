import os
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import alertas
import coletor
import painel
import web
from tests.test_coletor import conn  # noqa: F401  (fixture)

HOJE = date.today()
AUTH = ("ralph", "segredo")


def rota(conn, nome):
    return conn.execute("SELECT id FROM rotas WHERE nome = %s", (nome,)).fetchone()[0]


def preco(conn, rota_id, ida, valor, dias_atras=0, dias=10):
    conn.execute(
        """INSERT INTO precos_tp (coletado_em, rota_id, ida, volta, dias, preco, cia, conexoes_ida, conexoes_volta)
           VALUES (now() - make_interval(days => %s), %s, %s, %s, %s, %s, 'TP', 0, 1)""",
        (dias_atras, rota_id, ida, ida + timedelta(days=dias), dias, valor))


@pytest.fixture
def banco(conn, monkeypatch):
    monkeypatch.setenv("APP_SENHA", "segredo")
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    lis = rota(conn, "Lisboa")
    ida = HOJE + timedelta(days=30)
    preco(conn, lis, ida, 3900, dias=12)
    preco(conn, lis, ida, 3200)                          # o mais barato do dia de ida vence
    preco(conn, lis, ida, 2500, dias_atras=5)            # coleta antiga: só entra no histórico
    preco(conn, lis, HOJE + timedelta(days=400), 5000)   # além da janela do site
    conn.execute(
        """INSERT INTO buscas (rota_id, ida, volta, motivo, menor_preco, nivel, faixa_min, faixa_max)
           VALUES (%s, %s, %s, 'agenda', 3300, 'low', 3600, 4500)""", (lis, ida, ida + timedelta(days=10)))
    conn.commit()
    return conn


def test_trechos_com_futuro_historico_e_google(banco):
    d = painel.dados(banco, HOJE)
    assert len(d["trechos"]) == 33                       # todos os ativos, mesmo sem preço
    lis = next(t for t in d["trechos"] if t["nome"] == "Lisboa")
    ida = HOJE + timedelta(days=30)
    assert lis["cod"] == "LIS" and lis["origem"] == "GRU" and lis["lon"] == -9.1 and lis["confirmar"]
    assert lis["futuro"] == {ida.isoformat(): [3200.0, (ida + timedelta(days=10)).isoformat(), "TP", 1]}
    assert [p for _, p in lis["historico"]] == [2500.0, 3200.0]
    assert lis["google"]["preco"] == 3300.0 and lis["google"]["faixa"] == [3600.0, 4500.0]
    pfb = next(t for t in d["trechos"] if t["nome"] == "Passo Fundo")
    assert pfb["origem"] == "SAO" and pfb["futuro"] == {} and pfb["google"] is None
    assert next(t for t in d["trechos"] if t["nome"] == "Barcelona")["confirmar"] is False


def test_trechos_novos_nao_gastam_serpapi(banco):
    todas = banco.execute(
        "SELECT id, nome, origem, destino_tp, destino_serpapi FROM rotas WHERE ativa ORDER BY id").fetchall()
    bcn = rota(banco, "Barcelona")
    preco(banco, bcn, HOJE + timedelta(days=40), 4000)
    nomes = {c[3] for c in coletor.escolher_buscas(banco, todas, HOJE)}
    assert "Madri" in nomes and "Barcelona" not in nomes


def test_alertas_pela_api(banco):
    c = TestClient(web.app)
    lis = rota(banco, "Lisboa")
    assert c.get("/api/dados").status_code == 401
    assert c.post("/api/alertas", json={}).status_code == 401
    corpo = {"rota_id": lis, "preco_max": 3300, "mes_de": 11, "mes_ate": 3}
    regra = c.post("/api/alertas", auth=AUTH, json=corpo).json()["id"]
    assert c.post("/api/alertas", auth=AUTH, json={**corpo, "rota_id": 99999}).status_code == 404
    assert c.post("/api/alertas", auth=AUTH, json={**corpo, "mes_de": 13}).status_code == 422
    assert c.get("/api/dados", auth=AUTH).json()["regras"] == [
        {"id": regra, "rota_id": lis, "preco_max": 3300.0, "mes_de": 11, "mes_ate": 3}]
    assert c.delete(f"/api/alertas/{regra}", auth=AUTH).status_code == 200
    assert c.delete(f"/api/alertas/{regra}", auth=AUTH).status_code == 404
    assert c.get("/api/dados", auth=AUTH).json()["regras"] == []


def test_regra_avisa_uma_vez_e_de_novo_so_se_cair_5_por_cento(banco, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "x")
    monkeypatch.setenv("ALERTA_EMAIL", "a@b.c")
    enviados = []
    monkeypatch.setattr(alertas, "enviar_email", lambda assunto, corpo: enviados.append(corpo))
    lis, ida = rota(banco, "Lisboa"), HOJE + timedelta(days=30)
    meses = {"de": ida.month, "ate": ida.month}
    caro = painel.criar_regra(banco, lis, 3000, meses["de"], meses["ate"])
    outro_mes = painel.criar_regra(banco, lis, 9000, ida.month % 12 + 1, ida.month % 12 + 1)
    regra = painel.criar_regra(banco, lis, 3300, meses["de"], meses["ate"])
    banco.commit()
    ultima = banco.execute("SELECT max(id) FROM buscas").fetchone()[0]

    alertas.processar(banco, ultima)
    assert len(enviados) == 1 and "abaixo do seu limite de R$ 3.300" in enviados[0]
    assert banco.execute("SELECT regra_id, preco FROM avisos_regra").fetchall() == [(regra, 3200)]
    alertas.processar(banco, ultima)                     # mesmo preço: não repete
    assert len(enviados) == 1
    preco(banco, lis, ida, 3100)                         # caiu 3%: ainda não
    alertas.processar(banco, ultima)
    assert len(enviados) == 1
    preco(banco, lis, ida, 2990)                         # caiu mais de 5%: avisa (e a regra de 3.000 também)
    alertas.processar(banco, ultima)
    assert len(enviados) == 2
    assert {r[0] for r in banco.execute("SELECT regra_id FROM avisos_regra")} == {regra, caro}
    assert outro_mes not in {r[0] for r in banco.execute("SELECT regra_id FROM avisos_regra")}
    avisos = painel.dados(banco, HOJE)["avisos"]
    assert len(avisos) == 3 and avisos[0]["motivo"].startswith("abaixo do seu limite")


def test_diario_das_coletas(banco):
    inicio = datetime.now(timezone.utc) - timedelta(hours=1)
    coletor.registrar_coleta(banco, inicio, 33)
    c = painel.dados(banco, HOJE)["coletas"]
    linha = banco.execute("SELECT trechos_ativos, trechos_com_preco, precos, buscas FROM coletas").fetchone()
    assert linha == (33, 1, 3, 1)
    assert c["buscas_no_mes"] == 1 and c["limite_mensal"] == 220
    assert c["buscas"][0]["motivo"] == "agenda" and c["buscas"][0]["nivel"] == "low"
    assert sum(d["precos"] for d in c["dias"]) == 4
    assert any(d["trechos_ativos"] == 33 for d in c["dias"])


def test_paginas(banco):
    c = TestClient(web.app)
    assert c.get("/chat").status_code == 401
    assert "Assistente" in c.get("/", auth=AUTH).text
    assert "Pergunte" in c.get("/chat", auth=AUTH).text
    assert c.get("/radar", follow_redirects=False).headers["location"] == "/"


def test_site_cria_as_tabelas_na_subida(banco):
    banco.execute("DROP TABLE avisos_regra, regras_alerta, coletas")
    banco.commit()
    with TestClient(web.app) as c:                      # o bloco with dispara o evento de subida
        assert c.get("/api/dados", auth=AUTH).json()["regras"] == []
