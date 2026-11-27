from datetime import date

import pytest
from fastapi.testclient import TestClient

from prototipo import app as prototipo_app
from prototipo import dados_teste, gerar_estatico

HOJE = date(2026, 11, 27)


@pytest.fixture
def cliente():
    prototipo_app.semear()
    return TestClient(prototipo_app.app)


def test_dados_sao_deterministicos():
    dados_teste.montar.cache_clear()
    a = dados_teste.montar("media", HOJE)
    dados_teste.montar.cache_clear()
    assert dados_teste.montar("media", HOJE) == a


def test_formato_dos_dados():
    d = dados_teste.montar("media", HOJE)
    assert len(d["destinos"]) == len(dados_teste.DESTINOS)
    lisboa = next(x for x in d["destinos"] if x["codigo"] == "LIS")
    assert len(lisboa["calendario"]) == dados_teste.DIAS_HORIZONTE
    assert len(lisboa["semanal"]) == dados_teste.SEMANAS
    assert all(6 <= c["dur"] <= 12 for c in lisboa["calendario"])
    c = lisboa["calendario"][0]
    assert c["desconto"] == round(1 - c["preco"] / c["normal"], 3)


def test_rumo_aponta_para_o_lugar_certo():
    europa = dados_teste.rumo(dados_teste.SAO_PAULO, (38.77, -9.13))
    sul = dados_teste.rumo(dados_teste.SAO_PAULO, (-28.24, -52.33))
    assert 0 < europa < 90 and 180 < sul < 270


def test_janelas_so_com_desconto_de_verdade():
    d = dados_teste.montar("media", HOJE)
    assert d["janelas"]
    assert all(j["desconto"] >= dados_teste.LIMIAR_JANELA for j in d["janelas"])


def test_desconto_mais_fundo_e_mais_raro():
    dest = dados_teste.DESTINOS[0]
    assert dados_teste.raridade(dest, 0.40)["vezes_ano"] <= dados_teste.raridade(dest, 0.15)["vezes_ano"]


def test_faixa_invalida():
    with pytest.raises(ValueError):
        dados_teste.montar("enorme")


def test_api_dados_e_pagina(cliente):
    assert cliente.get("/api/dados?faixa=curta").json()["dias"] == [2, 5]
    assert cliente.get("/api/dados?faixa=xyz").status_code == 422
    assert "Caçador" in cliente.get("/").text


def test_api_viagens(cliente):
    assert len(cliente.get("/api/viagens").json()) == 2
    nova = cliente.post("/api/viagens", json={"nome": "Praia", "destinos": ["NAT", "MCZ"], "meses": [2]})
    assert nova.status_code == 201
    assert cliente.post("/api/viagens", json={"nome": "X", "destinos": ["ZZZ"]}).status_code == 422
    assert cliente.delete(f"/api/viagens/{nova.json()['id']}").status_code == 204
    assert cliente.delete("/api/viagens/9999").status_code == 404
    assert len(cliente.get("/api/viagens").json()) == 2


def test_versao_estatica_embute_os_dados():
    html = gerar_estatico.gerar()
    assert "window.DADOS_EMBUTIDOS=" in html and '"curta"' in html and '"longa"' in html
