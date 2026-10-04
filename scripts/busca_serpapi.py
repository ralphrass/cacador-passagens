"""Primeira busca real de passagens via SerpApi (Google Flights).

Uso:
    pip install requests
    export SERPAPI_KEY="sua_chave"          # https://serpapi.com/manage-api-key
    python busca_serpapi.py GRU LIS 2026-11-18 2026-12-02

Cada execução consome 1 busca da cota (plano grátis: 250/mês).
"""
import os
import sys

import requests

API_URL = "https://serpapi.com/search.json"


def buscar(origem, destino, ida, volta=None):
    params = {
        "engine": "google_flights",
        "departure_id": origem,
        "arrival_id": destino,
        "outbound_date": ida,
        "type": 1 if volta else 2,  # 1 = ida e volta, 2 = só ida
        "currency": "BRL",
        "hl": "pt-br",
        "gl": "br",
        "adults": 1,
        "api_key": os.environ["SERPAPI_KEY"],
    }
    if volta:
        params["return_date"] = volta
    resp = requests.get(API_URL, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def resumir(dados):
    insights = dados.get("price_insights", {})
    if insights:
        print(f"Menor preço: R$ {insights.get('lowest_price')}")
        print(f"Nível do preço: {insights.get('price_level')}")
        print(f"Faixa típica: {insights.get('typical_price_range')}")
        historico = insights.get("price_history", [])
        if historico:
            print(f"Histórico do Google: {len(historico)} pontos (timestamp, preço)")
    print()
    voos = dados.get("best_flights", []) + dados.get("other_flights", [])
    for opcao in voos[:10]:
        trechos = opcao["flights"]
        cias = ", ".join(sorted({t["airline"] for t in trechos}))
        rota = " > ".join([trechos[0]["departure_airport"]["id"]]
                          + [t["arrival_airport"]["id"] for t in trechos])
        horas = opcao["total_duration"] // 60
        print(f"R$ {opcao.get('price', '?'):>6} | {cias:<30} | {rota:<20} | {horas}h | "
              f"saída {trechos[0]['departure_airport']['time']}")


if __name__ == "__main__":
    args = sys.argv[1:] or ["GRU", "LIS", "2026-11-18"]
    resumir(buscar(*args))
