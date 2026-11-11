"""Site: análise de preços e alertas (/) e chat com o agente (/chat). Rode com: python web.py (usa a porta da variável PORT, padrão 8080)"""
import logging
import os
import secrets
from pathlib import Path

import anthropic
import psycopg
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

import agente
import painel

log = logging.getLogger("web")
app = FastAPI(title="Caçador de Passagens")
app.add_middleware(GZipMiddleware, minimum_size=2000)
seguranca = HTTPBasic(realm="Cacador de Passagens")
PAGINA = (Path(__file__).parent / "site.html").read_text(encoding="utf-8")
PAGINA_CHAT = (Path(__file__).parent / "chat.html").read_text(encoding="utf-8")


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


class Regra(BaseModel):
    rota_id: int
    preco_max: float = Field(gt=0, lt=1_000_000)
    mes_de: int = Field(ge=1, le=12)
    mes_ate: int = Field(ge=1, le=12)


def banco():
    try:
        return psycopg.connect(os.environ["DATABASE_URL"])
    except psycopg.Error:
        log.exception("Falha ao conectar no banco")
        raise HTTPException(503, "Não consegui ler o banco agora. Tente de novo.")


@app.get("/chat", response_class=HTMLResponse, dependencies=[Depends(autenticar)])
def pagina_chat():
    return PAGINA_CHAT


@app.get("/radar", include_in_schema=False)
def radar_antigo():
    return RedirectResponse("/")


@app.get("/api/dados", dependencies=[Depends(autenticar)])
def api_dados():
    with banco() as conn:
        return painel.dados(conn)


@app.post("/api/alertas", dependencies=[Depends(autenticar)])
def criar_alerta(r: Regra):
    with banco() as conn:
        regra_id = painel.criar_regra(conn, r.rota_id, r.preco_max, r.mes_de, r.mes_ate)
    if regra_id is None:
        raise HTTPException(404, "Trecho não encontrado")
    return {"id": regra_id}


@app.delete("/api/alertas/{regra_id}", dependencies=[Depends(autenticar)])
def remover_alerta(regra_id: int):
    with banco() as conn:
        if not painel.remover_regra(conn, regra_id):
            raise HTTPException(404, "Alerta não encontrado")
    return {"ok": True}


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
