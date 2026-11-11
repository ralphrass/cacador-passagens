import os
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import radar
import web
from tests.test_coletor import conn  # noqa: F401  (fixture)

HOJE = date(2026, 11, 11)


def rota(conn, nome):
    return conn.execute("SELECT id FROM rotas WHERE nome = %s", (nome,)).fetchone()[0]


def preco(conn, rota_id, ida, valor, coletado=HOJE, dias=10, cia="TP"):
    conn.execute(
        """INSERT INTO precos_tp (coletado_em, rota_id, ida, volta, dias, preco, cia, conexoes_ida, conexoes_volta)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 1)""",
        (coletado, rota_id, ida, ida + timedelta(days=dias), dias, valor, cia))


@pytest.fixture
def banco(conn):
    lis, mad = rota(conn, "Lisboa"), rota(conn, "Madri")
    ida = HOJE + timedelta(days=30)
    preco(conn, lis, ida, 3900, dias=12)
    preco(conn, lis, ida, 3200)                                   # o mais barato do dia de ida vence
    preco(conn, lis, ida, 2500, coletado=HOJE - timedelta(days=5))  # coleta antiga: fora da série, dentro do histórico
    preco(conn, lis, HOJE + timedelta(days=400), 2000)            # além dos 6 meses
    preco(conn, mad, ida, 3400)
    conn.execute(
        """INSERT INTO buscas (rota_id, ida, volta, motivo, menor_preco, nivel, faixa_min, faixa_max)
           VALUES (%s, %s, %s, 'agenda', 3300, 'low', 3600, 4500)""", (lis, ida, ida + timedelta(days=10)))
    conn.execute("INSERT INTO descoberta (destino, preco) VALUES ('BUE', 1480), ('LIS', 3000), ('XXX', 900)")
    conn.commit()
    return conn


def test_dados_do_radar(banco):
    d = radar.dados(banco, HOJE)
    assert d["hoje"] == "2026-11-11" and d["dias"] == 182
    assert [r["nome"] for r in d["rotas"]] == ["Lisboa", "Madri"]   # só rotas com preço
    lis, mad = d["rotas"]
    assert lis["cod"] == "GRU–LIS" and lis["lon"] == -9.1
    assert lis["serie"] == {"2026-12-11": [3200.0, "2026-12-21", "TP", 1]}
    assert lis["faixa"] == [3600.0, 4500.0] and lis["faixa_fonte"] == "google"
    assert lis["min"] == 2000.0 and lis["max"] == 4500.0
    assert mad["faixa_fonte"] == "historico" and mad["faixa"] == [3400.0, 3400.0]
    # descoberta: fora as rotas monitoradas e os códigos sem coordenada
    assert d["descoberta"] == [{"nome": "Buenos Aires", "lon": -58.5, "lat": -34.8, "preco": 1480.0}]


def test_paginas_do_radar(banco, monkeypatch):
    monkeypatch.setenv("APP_SENHA", "segredo")
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    c = TestClient(web.app)
    assert c.get("/radar").status_code == 401
    assert c.get("/api/radar").status_code == 401
    assert "Radar de passagens" in c.get("/radar", auth=("ralph", "segredo")).text
    assert c.get("/api/radar", auth=("ralph", "segredo")).json()["dias"] == 182
