"""Páginas do site: chat com o agente (/) e Radar de preços (/radar). Rode com: python web.py (usa a porta da variável PORT, padrão 8080)"""
import logging
import os
import secrets
from pathlib import Path

import anthropic
import psycopg
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

import agente
import radar

log = logging.getLogger("web")
app = FastAPI(title="Caçador de Passagens")
seguranca = HTTPBasic(realm="Cacador de Passagens")
PAGINA = (Path(__file__).parent / "chat.html").read_text(encoding="utf-8")
PAGINA_RADAR = (Path(__file__).parent / "radar.html").read_text(encoding="utf-8")


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


@app.get("/radar", response_class=HTMLResponse, dependencies=[Depends(autenticar)])
def pagina_radar():
    return PAGINA_RADAR


@app.get("/api/radar", dependencies=[Depends(autenticar)])
def api_radar():
    try:
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            return radar.dados(conn)
    except psycopg.Error:
        log.exception("Radar: falha ao ler o banco")
        raise HTTPException(503, "Não consegui ler o banco agora. Tente de novo.")


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


@app.get("/saude")
def saude():
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
