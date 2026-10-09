import json
import os
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import agente
import alertas
import lembretes
import planejador
import web
from tests.test_coletor import conn  # noqa: F401  (fixture)


@pytest.fixture
def banco(conn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    return conn


def chamar(ferramenta, **args):
    return ferramenta.call(args)


def test_viagem_e_checklist(banco):
    r = json.loads(chamar(planejador.salvar_viagem, destino="Lisboa e Porto", ida="2027-03-10",
                          volta="2027-03-20", preferencias="vinho e trilha"))
    vid = r["viagem_id"]
    chamar(planejador.salvar_viagem, viagem_id=vid, destino="Lisboa e Porto", roteiro="## Dia 1\nAlfama")
    assert "Datas inválidas" in chamar(planejador.salvar_viagem, destino="X", ida="10/03/2027")
    assert "Não existe" in chamar(planejador.salvar_viagem, viagem_id=999, destino="X")

    r = json.loads(chamar(planejador.salvar_itens, viagem_id=vid, itens=[
        {"tipo": "documento", "descricao": "Seguro viagem Schengen", "prazo": "2027-03-01"},
        {"tipo": "roupa", "descricao": "Corta-vento"},
        {"tipo": "mala", "descricao": "Adaptador tomada tipo F"}]))
    assert r["itens_adicionados"] == 3

    v = planejador.listar_viagens(banco)[0]
    assert v["titulo"] == "Lisboa e Porto" and v["roteiro"].startswith("## Dia 1")
    assert v["preferencias"] == "vinho e trilha"  # atualizar não apaga campos não enviados
    assert [i["tipo"] for i in v["itens"]] == ["documento", "roupa", "mala"]

    ids = [i["id"] for i in v["itens"]]
    chamar(planejador.atualizar_itens, item_ids=ids[:1], acao="feito")
    chamar(planejador.atualizar_itens, item_ids=ids[2:], acao="remover")
    v = planejador.listar_viagens(banco)[0]
    assert [(i["descricao"], i["feito"]) for i in v["itens"]] == [
        ("Seguro viagem Schengen", True), ("Corta-vento", False)]


def test_monitorar_destino(banco):
    assert "próxima coleta" in chamar(planejador.monitorar_destino, nome="Tóquio",
                                      codigo_cidade="tyo", aeroportos="nrt, hnd")
    banco.execute("UPDATE rotas SET ativa = false WHERE destino_tp = 'LIS'")
    banco.commit()
    chamar(planejador.monitorar_destino, nome="Lisboa", codigo_cidade="LIS", aeroportos="LIS")
    linhas = dict(banco.execute("SELECT destino_tp, destino_serpapi FROM rotas WHERE ativa").fetchall())
    assert linhas["TYO"] == "NRT,HND" and "LIS" in linhas


def test_clima_previsao_e_historico(monkeypatch):
    pedidos = []

    def falso(url, **p):
        pedidos.append((url, p))
        if "geocoding" in url:
            assert p["name"] == "porto"
            return {"results": [{"name": "Porto", "country": "Brasil", "country_code": "BR", "latitude": 0, "longitude": 0},
                                {"name": "Porto", "country": "Portugal", "country_code": "PT", "latitude": 41.1, "longitude": -8.6}]}
        dias = (date.fromisoformat(p["end_date"]) - date.fromisoformat(p["start_date"])).days + 1
        return {"daily": {"time": [p["start_date"]] * dias, "temperature_2m_max": [20.0] * dias,
                          "temperature_2m_min": [10.0] * dias, "precipitation_sum": [0.0, 5.0] * (dias // 2) + [0.0] * (dias % 2)}}

    monkeypatch.setattr(planejador, "_get", falso)
    hoje = date(2026, 10, 4)
    r = planejador.clima("Porto, Portugal", date(2026, 10, 6), date(2026, 10, 9), hoje)
    assert r["lugar"] == "Porto, Portugal" and r["tipo"] == "previsão do tempo" and len(r["dias"]) == 4
    assert r["resumo"]["dias_com_chuva_pct"] == 50

    pedidos.clear()
    r = planejador.clima("Porto, PT", date(2027, 3, 10), date(2027, 3, 20), hoje)
    assert r["tipo"].startswith("clima típico") and len(r["anos"]) == 3
    assert r["media"]["max_media"] == 20.0
    assert {p["start_date"] for u, p in pedidos if "archive" in u} == {"2026-03-10", "2025-03-10", "2024-03-10"}


def test_lembretes(banco, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "x")
    monkeypatch.setenv("ALERTA_EMAIL", "eu@exemplo.com")
    enviados = []
    monkeypatch.setattr(alertas, "enviar_email", lambda a, c: enviados.append((a, c)))
    hoje = date.today()
    vid = banco.execute("INSERT INTO viagens (titulo, destino, ida) VALUES ('Londres', 'Londres', %s) RETURNING id",
                        (hoje + timedelta(days=30),)).fetchone()[0]
    for desc, dias in [("Pedir ETA", 5), ("Comprar ingresso", 20), ("Avisar banco", 1)]:
        banco.execute("INSERT INTO itens_viagem (viagem_id, tipo, descricao, prazo) VALUES (%s, 'tarefa', %s, %s)",
                      (vid, desc, hoje + timedelta(days=dias)))
    banco.commit()

    lembretes.processar(banco, hoje)
    assunto, corpo = enviados[-1]
    assert assunto == "🧳 2 lembretes de viagem"
    assert "Pedir ETA" in corpo and "Avisar banco" in corpo and "amanhã" in corpo and "Comprar ingresso" not in corpo

    lembretes.processar(banco, hoje)          # mesmo dia: nada novo
    assert len(enviados) == 1
    # perto do embarque: e-mail com o que falta na mala
    banco.execute("UPDATE viagens SET ida = %s", (hoje + timedelta(days=2),))
    banco.execute("INSERT INTO itens_viagem (viagem_id, tipo, descricao) VALUES (%s, 'roupa', 'Casaco')", (vid,))
    banco.commit()
    lembretes.processar(banco, hoje)
    assunto, corpo = enviados[-1]
    assert assunto == "🧳 Londres: a viagem está chegando" and "Roupas: Casaco" in corpo
    lembretes.processar(banco, hoje)
    assert len(enviados) == 2


def test_paginas_e_api_de_viagens(banco, monkeypatch):
    monkeypatch.setenv("APP_SENHA", "s")
    c = TestClient(web.app)
    assert c.get("/viagens").status_code == 401
    assert "Minhas viagens" in c.get("/viagens", auth=("ralph", "s")).text
    vid = json.loads(chamar(planejador.salvar_viagem, destino="Roma", ida="2027-05-01"))["viagem_id"]
    chamar(planejador.salvar_itens, viagem_id=vid, itens=[{"tipo": "mala", "descricao": "Protetor solar"}])
    v = c.get("/api/viagens", auth=("ralph", "s")).json()
    assert v[0]["ida"] == "2027-05-01"
    item = v[0]["itens"][0]["id"]
    assert c.post(f"/api/itens/{item}", json={"feito": True}, auth=("ralph", "s")).status_code == 200
    assert c.get("/api/viagens", auth=("ralph", "s")).json()[0]["itens"][0]["feito"] is True
    assert c.post("/api/itens/999", json={"feito": True}, auth=("ralph", "s")).status_code == 404
    assert c.delete(f"/api/viagens/{vid}", auth=("ralph", "s")).status_code == 200
    assert c.get("/api/viagens", auth=("ralph", "s")).json() == []


class Bloco:
    def __init__(self, texto):
        self.type, self.text = "text", texto


class Resposta:
    def __init__(self, stop, *textos):
        self.stop_reason, self.content = stop, [Bloco(t) for t in textos]


def test_responder_retoma_pause_turn(monkeypatch):
    chamadas = []
    respostas = iter([[Resposta("pause_turn", "Buscando…")], [Resposta("end_turn", "Precisa de ", "ETA.")]])

    class Runner:
        def __init__(self, msgs):
            self.msgs = list(msgs)
            self.respostas = next(respostas)

        def __iter__(self):
            return iter(self.respostas)

        def generate_tool_call_response(self):
            return None

    class Cliente:
        def __init__(self):
            self.beta = self
            self.messages = self

        def tool_runner(self, **kw):
            chamadas.append(kw)
            return Runner(kw["messages"])

    monkeypatch.setattr(agente.anthropic, "Anthropic", Cliente)
    assert agente.responder([{"role": "user", "content": "Londres?"}]) == "Precisa de ETA."
    assert len(chamadas) == 2
    assert chamadas[1]["messages"][-1]["role"] == "assistant"   # retoma o turno pausado
    nomes = [t["name"] if isinstance(t, dict) else t.name for t in chamadas[0]["tools"]]
    assert {"consultar_sql", "consultar_clima", "salvar_viagem", "web_search"} <= set(nomes)
