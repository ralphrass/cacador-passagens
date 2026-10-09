import json
import os

import pytest
from fastapi.testclient import TestClient

import agente
import web
from tests.test_coletor import conn  # noqa: F401  (fixture)


@pytest.fixture
def banco(conn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    return conn


def sql(q):
    return agente.consultar_sql.call({"sql": q})


def test_consulta_de_leitura(banco):
    r = json.loads(sql("SELECT nome FROM rotas WHERE nome LIKE 'L%' ORDER BY nome"))
    assert r["linhas"] == [["Lisboa"], ["Londres"]]


def test_bloqueia_escrita_e_varios_comandos(banco):
    assert "read-only" in sql("DELETE FROM rotas")
    assert "multiple commands" in sql("COMMIT; DELETE FROM rotas")
    assert banco.execute("SELECT count(*) FROM rotas").fetchone()[0] == 13


def test_erro_volta_como_texto(banco):
    assert sql("SELECT * FROM nao_existe").startswith("Erro do Postgres")


def test_limita_linhas(banco):
    r = json.loads(sql("SELECT generate_series(1, 500)"))
    assert len(r["linhas"]) == 200 and "aviso" in r


def test_web_exige_senha_e_responde(monkeypatch):
    monkeypatch.setenv("APP_SENHA", "segredo")
    monkeypatch.setattr(agente, "responder", lambda h: f"ok: {h[-1]['content']}")
    c = TestClient(web.app)
    assert c.get("/").status_code == 401
    assert c.get("/", auth=("ralph", "errada")).status_code == 401
    assert "Caçador de Passagens" in c.get("/", auth=("ralph", "segredo")).text
    r = c.post("/api/perguntar", auth=("ralph", "segredo"),
               json={"historico": [{"role": "user", "content": "Lisboa?"}]})
    assert r.json() == {"resposta": "ok: Lisboa?"}
    assert c.get("/saude").status_code == 200


def test_web_sem_senha_configurada_bloqueia(monkeypatch):
    monkeypatch.delenv("APP_SENHA", raising=False)
    assert TestClient(web.app).get("/", auth=("ralph", "")).status_code == 401
