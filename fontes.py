"""Clientes das duas fontes de preço: Travelpayouts (grátis) e SerpApi (cota)."""
import os

import requests

TP_URL = "https://api.travelpayouts.com/aviasales/v3"
SERPAPI_URL = "https://serpapi.com"


# ---------- Travelpayouts ----------

def tp_ida_volta(destino, mes):
    """Ida e volta mais baratas de São Paulo para `destino` com ida no mês AAAA-MM."""
    resp = requests.get(f"{TP_URL}/prices_for_dates", params={
        "origin": "SAO",
        "destination": destino,
        "departure_at": mes,
        "one_way": "false",
        "currency": "brl",
        "market": "br",
        "sorting": "price",
        "limit": 1000,
        "token": os.environ["TRAVELPAYOUTS_TOKEN"],
    }, timeout=30)
    resp.raise_for_status()
    return resp.json().get("data", [])


def tp_descoberta():
    """Destinos mais baratos saindo de São Paulo no último ano de buscas."""
    resp = requests.get(f"{TP_URL}/get_latest_prices", params={
        "origin": "SAO",
        "period_type": "year",
        "group_by": "directions",
        "one_way": "false",
        "currency": "brl",
        "market": "br",
        "sorting": "price",
        "limit": 100,
        "token": os.environ["TRAVELPAYOUTS_TOKEN"],
    }, timeout=30)
    resp.raise_for_status()
    return resp.json().get("data", [])


# ---------- SerpApi ----------

def serp_uso_mes():
    """Buscas já gastas no mês. Consultar a conta não consome cota."""
    resp = requests.get(f"{SERPAPI_URL}/account.json",
                        params={"api_key": os.environ["SERPAPI_KEY"]}, timeout=30)
    resp.raise_for_status()
    return resp.json()["this_month_usage"]


def serp_voos(origem, destino, ida, volta):
    resp = requests.get(f"{SERPAPI_URL}/search.json", params={
        "engine": "google_flights",
        "departure_id": origem,
        "arrival_id": destino,
        "outbound_date": ida.isoformat(),
        "return_date": volta.isoformat(),
        "type": 1,
        "currency": "BRL",
        "hl": "pt-br",
        "gl": "br",
        "adults": 1,
        "api_key": os.environ["SERPAPI_KEY"],
    }, timeout=90)
    resp.raise_for_status()
    return resp.json()
