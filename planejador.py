"""Ferramentas do planejador de viagens: clima, roteiros salvos e checklist (roupas, mala, documentos, tarefas)."""
import json
import os
from datetime import date, timedelta
from statistics import mean
from typing import Literal, Optional

import psycopg
import requests
from anthropic import beta_tool
from typing_extensions import NotRequired, TypedDict

TIPOS = ("roupa", "mala", "documento", "tarefa")
DIAS_PREVISAO = 15  # a previsão da Open-Meteo vai até 16 dias à frente
ANOS_CLIMA = 3


def _conectar():
    return psycopg.connect(os.environ["DATABASE_URL"])


def _data(texto):
    return date.fromisoformat(texto) if texto else None


# ---------- clima (Open-Meteo, sem chave) ----------

def _get(url, **params):
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def localizar(cidade):
    # A busca da Open-Meteo só entende o nome; o país, se vier ("Porto, Portugal"), desempata
    nome, _, pais = (p.strip().lower() for p in cidade.partition(","))
    achados = _get("https://geocoding-api.open-meteo.com/v1/search",
                   name=nome, count=10, language="pt").get("results") or []
    if pais:
        no_pais = [a for a in achados if pais in (a.get("country", "").lower(), a.get("country_code", "").lower())]
        achados = no_pais or achados
    return achados[0] if achados else None


def _resumo_diario(daily):
    maximas = [t for t in daily["temperature_2m_max"] if t is not None]
    minimas = [t for t in daily["temperature_2m_min"] if t is not None]
    chuva = [p for p in daily["precipitation_sum"] if p is not None]
    if not maximas:
        return None
    return {"max_media": round(mean(maximas), 1), "min_media": round(mean(minimas), 1),
            "max_absoluta": max(maximas), "min_absoluta": min(minimas),
            "dias_com_chuva_pct": round(100 * sum(p >= 1 for p in chuva) / len(chuva)) if chuva else None,
            "chuva_total_mm": round(sum(chuva), 1)}


def clima(cidade, inicio, fim, hoje=None):
    hoje = hoje or date.today()
    fim = min(fim, inicio + timedelta(days=30))
    lugar = localizar(cidade)
    if not lugar:
        return {"erro": f"Não encontrei a cidade '{cidade}'. Tente o nome em inglês ou com o país."}
    base = {"lugar": f"{lugar['name']}, {lugar.get('country', '')}".strip(", "),
            "latitude": lugar["latitude"], "longitude": lugar["longitude"]}
    diarias = "temperature_2m_max,temperature_2m_min,precipitation_sum"
    if fim <= hoje + timedelta(days=DIAS_PREVISAO) and inicio >= hoje:
        d = _get("https://api.open-meteo.com/v1/forecast", latitude=lugar["latitude"],
                 longitude=lugar["longitude"], daily=diarias, timezone="auto",
                 start_date=inicio.isoformat(), end_date=fim.isoformat())["daily"]
        dias = [{"dia": dia, "max": mx, "min": mn, "chuva_mm": p} for dia, mx, mn, p in zip(
            d["time"], d["temperature_2m_max"], d["temperature_2m_min"], d["precipitation_sum"])]
        return {**base, "tipo": "previsão do tempo", "resumo": _resumo_diario(d), "dias": dias}
    # Viagem distante: média das mesmas datas nos últimos anos
    anos = []
    for n in range(1, ANOS_CLIMA + 1):
        try:
            ini, fi = inicio.replace(year=inicio.year - n), fim.replace(year=fim.year - n)
        except ValueError:  # 29/02
            ini, fi = inicio - timedelta(days=365 * n), fim - timedelta(days=365 * n)
        if fi >= hoje - timedelta(days=6):  # o arquivo histórico tem alguns dias de atraso
            continue
        d = _get("https://archive-api.open-meteo.com/v1/archive", latitude=lugar["latitude"],
                 longitude=lugar["longitude"], daily=diarias, timezone="auto",
                 start_date=ini.isoformat(), end_date=fi.isoformat())["daily"]
        resumo = _resumo_diario(d)
        if resumo:
            anos.append({"ano": ini.year, **resumo})
    if not anos:
        return {**base, "erro": "Sem dados históricos para essas datas."}
    media = {k: round(mean(a[k] for a in anos if a[k] is not None), 1)
             for k in ("max_media", "min_media", "dias_com_chuva_pct", "chuva_total_mm")}
    return {**base, "tipo": f"clima típico (mesmas datas nos últimos {len(anos)} anos)",
            "media": media, "anos": anos}


@beta_tool
def consultar_clima(cidade: str, data_inicio: str, data_fim: str) -> str:
    """Temperatura e chuva esperadas numa cidade entre duas datas. Para datas nos próximos 15 dias
    devolve a previsão do tempo; para datas mais distantes, o clima típico das mesmas datas nos
    últimos 3 anos (médias de máxima, mínima e % de dias com chuva). Use para planejar roupas e atividades.

    Args:
        cidade: Nome da cidade, de preferência com o país (ex.: "Lisboa, Portugal").
        data_inicio: Primeiro dia, AAAA-MM-DD.
        data_fim: Último dia, AAAA-MM-DD (no máximo 31 dias depois do início).
    """
    try:
        resultado = clima(cidade, _data(data_inicio), _data(data_fim))
    except ValueError:
        return "Datas inválidas; use AAAA-MM-DD."
    except requests.RequestException as e:
        return f"O serviço de clima não respondeu agora ({type(e).__name__})."
    return json.dumps(resultado, ensure_ascii=False)


# ---------- viagens e checklist ----------

@beta_tool
def salvar_viagem(destino: str, titulo: Optional[str] = None, ida: Optional[str] = None,
                  volta: Optional[str] = None, pessoas: Optional[str] = None,
                  preferencias: Optional[str] = None, roteiro: Optional[str] = None,
                  viagem_id: Optional[int] = None) -> str:
    """Cria uma viagem planejada ou atualiza uma existente (passe viagem_id para atualizar; só os campos
    enviados mudam). Salve sempre o roteiro final para o Ralph ver depois na página Minhas viagens.

    Args:
        destino: Cidade(s) ou país (ex.: "Lisboa e Porto").
        titulo: Nome curto (ex.: "Portugal em março"). Se vazio, usa o destino.
        ida: Data de ida AAAA-MM-DD, se já definida.
        volta: Data de volta AAAA-MM-DD, se já definida.
        pessoas: Quem vai (ex.: "casal").
        preferencias: Gostos, ritmo e orçamento que o Ralph contou.
        roteiro: Roteiro dia a dia em markdown (dias, atividades, dicas, custos estimados).
        viagem_id: Id de uma viagem já salva, para atualizar.
    """
    try:
        campos = {"destino": destino, "titulo": titulo, "ida": _data(ida), "volta": _data(volta),
                  "pessoas": pessoas, "preferencias": preferencias, "roteiro": roteiro}
    except ValueError:
        return "Datas inválidas; use AAAA-MM-DD."
    with _conectar() as conn:
        if viagem_id is None:
            campos["titulo"] = titulo or destino
            cols = [k for k, v in campos.items() if v is not None]
            novo = conn.execute(
                f"INSERT INTO viagens ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id",
                [campos[c] for c in cols]).fetchone()[0]
            return json.dumps({"viagem_id": novo, "status": "criada"})
        cols = [k for k, v in campos.items() if v is not None]
        cur = conn.execute(
            f"UPDATE viagens SET {', '.join(f'{c} = %s' for c in cols)} WHERE id = %s",
            [campos[c] for c in cols] + [viagem_id])
        if cur.rowcount == 0:
            return f"Não existe viagem com id {viagem_id}."
        return json.dumps({"viagem_id": viagem_id, "status": "atualizada"})


class Item(TypedDict):
    tipo: Literal["roupa", "mala", "documento", "tarefa"]
    descricao: str
    prazo: NotRequired[str]


@beta_tool
def salvar_itens(viagem_id: int, itens: list[Item]) -> str:
    """Adiciona itens ao checklist de uma viagem. Tipos: roupa (peças e quantidades pensadas para o clima e
    as atividades), mala (o que levar além de roupa: adaptador de tomada, remédios, eletrônicos),
    documento (passaporte, visto, autorização eletrônica, seguro, vacinas, carteira de motorista internacional)
    e tarefa (algo a fazer antes da viagem, como reservar ingressos ou avisar o banco). Dê prazo
    (AAAA-MM-DD) para documentos e tarefas: o Ralph recebe lembrete por e-mail quando o prazo se aproxima.
    Não repita itens que o checklist já tem (consulte itens_viagem antes).

    Args:
        viagem_id: Id da viagem.
        itens: Lista de itens com tipo, descricao e prazo opcional.
    """
    try:
        linhas = [(viagem_id, i["tipo"], i["descricao"].strip(), _data(i.get("prazo"))) for i in itens]
    except ValueError:
        return "Prazo inválido; use AAAA-MM-DD."
    if any(t not in TIPOS for _, t, _, _ in linhas):
        return f"Tipo inválido; use um de {', '.join(TIPOS)}."
    with _conectar() as conn:
        if not conn.execute("SELECT 1 FROM viagens WHERE id = %s", (viagem_id,)).fetchone():
            return f"Não existe viagem com id {viagem_id}."
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO itens_viagem (viagem_id, tipo, descricao, prazo) VALUES (%s, %s, %s, %s)", linhas)
    return json.dumps({"viagem_id": viagem_id, "itens_adicionados": len(linhas)})


@beta_tool
def atualizar_itens(item_ids: list[int], acao: Literal["feito", "pendente", "remover"]) -> str:
    """Marca itens do checklist como feitos, volta para pendentes ou remove.

    Args:
        item_ids: Ids dos itens (tabela itens_viagem).
        acao: "feito", "pendente" ou "remover".
    """
    with _conectar() as conn:
        if acao == "remover":
            cur = conn.execute("DELETE FROM itens_viagem WHERE id = ANY(%s)", (item_ids,))
        else:
            cur = conn.execute("UPDATE itens_viagem SET feito = %s WHERE id = ANY(%s)",
                               (acao == "feito", item_ids))
    return json.dumps({"itens_afetados": cur.rowcount})


@beta_tool
def monitorar_destino(nome: str, codigo_cidade: str, aeroportos: str) -> str:
    """Passa a coletar preços diários de GRU para um destino novo (entra na tabela rotas). Cada rota gasta
    parte da cota mensal da SerpApi, então só use depois que o Ralph confirmar que quer monitorar.

    Args:
        nome: Nome da cidade (ex.: "Amsterdã").
        codigo_cidade: Código IATA de cidade usado pela Travelpayouts (ex.: AMS, TYO, MIL).
        aeroportos: Aeroportos IATA separados por vírgula para o Google Flights (ex.: "NRT,HND").
    """
    codigo = codigo_cidade.strip().upper()
    aeroportos = ",".join(a.strip().upper() for a in aeroportos.split(",") if a.strip())
    if len(codigo) != 3 or not aeroportos:
        return "Informe um código de cidade de 3 letras e ao menos um aeroporto."
    with _conectar() as conn:
        conn.execute(
            """INSERT INTO rotas (nome, destino_tp, destino_serpapi) VALUES (%s, %s, %s)
               ON CONFLICT (origem, destino_tp) DO UPDATE SET ativa = true""",
            (nome, codigo, aeroportos))
    return f"{nome} ({codigo}) será coletado a partir da próxima coleta diária."


FERRAMENTAS = [consultar_clima, salvar_viagem, salvar_itens, atualizar_itens, monitorar_destino]


# ---------- usado pela página Minhas viagens ----------

def listar_viagens(conn):
    viagens = conn.execute(
        """SELECT id, titulo, destino, ida, volta, pessoas, preferencias, roteiro
           FROM viagens ORDER BY ida NULLS LAST, id""").fetchall()
    itens = conn.execute(
        "SELECT id, viagem_id, tipo, descricao, prazo, feito FROM itens_viagem ORDER BY prazo NULLS LAST, id"
    ).fetchall()
    resultado = []
    for v in viagens:
        resultado.append({
            "id": v[0], "titulo": v[1], "destino": v[2], "ida": v[3], "volta": v[4],
            "pessoas": v[5], "preferencias": v[6], "roteiro": v[7],
            "itens": [{"id": i[0], "tipo": i[2], "descricao": i[3], "prazo": i[4], "feito": i[5]}
                      for i in itens if i[1] == v[0]],
        })
    return resultado
