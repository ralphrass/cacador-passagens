"""Página de chat com o agente. Rode com: python web.py (usa a porta da variável PORT, padrão 8080)"""
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import anthropic
import psycopg
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

import agente
import planejador

log = logging.getLogger("web")
PASTA = Path(__file__).parent
PAGINA = (PASTA / "chat.html").read_text(encoding="utf-8")
PAGINA_VIAGENS = (PASTA / "viagens.html").read_text(encoding="utf-8")


@asynccontextmanager
async def iniciar(app):
    # Cria as tabelas novas (viagens) sem esperar a próxima coleta
    try:
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            conn.execute((PASTA / "schema.sql").read_text())
    except Exception:
        log.exception("Não consegui aplicar o schema.sql")
    yield


app = FastAPI(title="Caçador de Passagens", lifespan=iniciar)
seguranca = HTTPBasic(realm="Cacador de Passagens")


def autenticar(cred: HTTPBasicCredentials = Depends(seguranca)):
    senha = os.environ.get("APP_SENHA", "")
    usuario = os.environ.get("APP_USUARIO", "ralph")
    ok = bool(senha) and secrets.compare_digest(cred.password.encode(), senha.encode()) \
        and secrets.compare_digest(cred.username.encode(), usuario.encode())
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})


class Mensagem(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class Pergunta(BaseModel):
    historico: list[Mensagem] = Field(min_length=1, max_length=40)


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(autenticar)])
def pagina():
    return PAGINA


@app.post("/api/perguntar", dependencies=[Depends(autenticar)])
def perguntar(p: Pergunta):
    if p.historico[-1].role != "user":
        raise HTTPException(400, "A última mensagem precisa ser do usuário")
    try:
        resposta = agente.responder([m.model_dump() for m in p.historico])
    except anthropic.RateLimitError:
        raise HTTPException(429, "Muitas perguntas seguidas; espere um pouco.")
    except anthropic.APIStatusError as e:
        log.error("Erro da API Anthropic: %s %s", e.status_code, e.message)
        raise HTTPException(502, "O Claude não respondeu agora. Tente de novo.")
    except anthropic.APIConnectionError:
        raise HTTPException(502, "Sem conexão com o Claude. Tente de novo.")
    return {"resposta": resposta}


@app.get("/viagens", response_class=HTMLResponse, dependencies=[Depends(autenticar)])
def pagina_viagens():
    return PAGINA_VIAGENS


@app.get("/api/viagens", dependencies=[Depends(autenticar)])
def viagens():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        return planejador.listar_viagens(conn)


class Marcacao(BaseModel):
    feito: bool


@app.post("/api/itens/{item_id}", dependencies=[Depends(autenticar)])
def marcar_item(item_id: int, m: Marcacao):
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        if conn.execute("UPDATE itens_viagem SET feito = %s WHERE id = %s", (m.feito, item_id)).rowcount == 0:
            raise HTTPException(404, "Item não encontrado")
    return {"ok": True}


@app.delete("/api/viagens/{viagem_id}", dependencies=[Depends(autenticar)])
def apagar_viagem(viagem_id: int):
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        if conn.execute("DELETE FROM viagens WHERE id = %s", (viagem_id,)).rowcount == 0:
            raise HTTPException(404, "Viagem não encontrada")
    return {"ok": True}


@app.get("/saude")
def saude():
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
