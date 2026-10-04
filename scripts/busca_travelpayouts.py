"""Preços em cache (grátis) da Travelpayouts/Aviasales: o mais barato por mês/dia.

Bom para "descobrir" quando está barato; os preços vêm de buscas recentes de
usuários (2 a 7 dias de idade), então confirme no Google Flights antes de comprar.

Uso:
    pip install requests
    export TRAVELPAYOUTS_TOKEN="seu_token"   # Perfil > API token, após cadastro grátis
    python busca_travelpayouts.py GRU LIS 2026-11
"""
import os
import sys

import requests


def mais_baratos(origem, destino, mes):
    resp = requests.get(
        "https://api.travelpayouts.com/aviasales/v3/prices_for_dates",
        params={
            "origin": origem,
            "destination": destino,
            "departure_at": mes,  # AAAA-MM ou AAAA-MM-DD
            "currency": "brl",
            "sorting": "price",
            "one_way": "true",
            "limit": 15,
            "token": os.environ["TRAVELPAYOUTS_TOKEN"],
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["data"]


if __name__ == "__main__":
    origem, destino, mes = sys.argv[1:] or ["GRU", "LIS", "2026-11"]
    for v in mais_baratos(origem, destino, mes):
        print(f"R$ {v['price']:>6} | {v['airline']} | {v['departure_at'][:10]} | "
              f"{v['transfers']} conexões | aviasales.com{v['link']}")
