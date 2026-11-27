"""Protótipo do novo caçador: telas de visão geral sobre dados de teste.

Rode com: uvicorn prototipo.app:app --reload   (ou SERVICO=prototipo python iniciar.py)

As viagens ficam na memória do servidor e somem quando ele reinicia: é um protótipo.
"""
import itertools
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from prototipo import dados_teste

app = FastAPI(title="Caçador de Passagens (protótipo)")
app.add_middleware(GZipMiddleware, minimum_size=2000)
PAGINA = Path(__file__).parent / "index.html"
CODIGOS = {d[0] for d in dados_teste.DESTINOS}

_viagens: dict[int, dict] = {}
_ids = itertools.count(1)


class NovaViagem(BaseModel):
    nome: str = Field(min_length=1, max_length=60)
    destinos: list[str] = Field(min_length=1, max_length=len(CODIGOS))
    meses: list[int] = Field(default_factory=list, max_length=12)  # vazio = qualquer mês
    faixa: str = Field(default="media", pattern="^(curta|media|longa)$")


def semear():
    """Duas viagens de exemplo, para a tela inicial não começar vazia."""
    _viagens.clear()
    for v in (NovaViagem(nome="Visitar a família", destinos=["PFB"], faixa="curta"),
              NovaViagem(nome="Europa em março", destinos=["LIS", "MAD", "PAR", "ROM"], meses=[3])):
        criar_viagem(v)


@app.get("/", response_class=HTMLResponse)
def pagina():
    return PAGINA.read_text(encoding="utf-8")


@app.get("/api/dados")
def dados(faixa: str = "media"):
    if faixa not in dados_teste.FAIXAS:
        raise HTTPException(422, "faixa deve ser curta, media ou longa")
    return dados_teste.montar(faixa)


@app.get("/api/viagens")
def listar_viagens():
    return list(_viagens.values())


@app.post("/api/viagens", status_code=201)
def criar_viagem(v: NovaViagem):
    invalidos = set(v.destinos) - CODIGOS
    if invalidos or any(not 1 <= m <= 12 for m in v.meses):
        raise HTTPException(422, f"destino ou mês inválido: {sorted(invalidos) or v.meses}")
    viagem = {"id": next(_ids), **v.model_dump()}
    _viagens[viagem["id"]] = viagem
    return viagem


@app.delete("/api/viagens/{viagem_id}", status_code=204)
def apagar_viagem(viagem_id: int):
    if _viagens.pop(viagem_id, None) is None:
        raise HTTPException(404, "viagem não encontrada")


semear()
