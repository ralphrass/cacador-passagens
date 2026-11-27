"""Gera uma versão do protótipo num único HTML, com os dados de teste embutidos.

Serve para abrir no celular sem servidor. As viagens ficam no navegador.
Uso: python -m prototipo.gerar_estatico [saida.html]
"""
import json
import sys
from pathlib import Path

from prototipo import dados_teste

PASTA = Path(__file__).parent


def gerar():
    dados = {faixa: dados_teste.montar(faixa) for faixa in dados_teste.FAIXAS}
    embutido = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = (PASTA / "index.html").read_text(encoding="utf-8")
    return html.replace("<script>\nconst LIMIAR", f"<script>window.DADOS_EMBUTIDOS={embutido};</script>\n<script>\nconst LIMIAR", 1)


if __name__ == "__main__":
    saida = Path(sys.argv[1] if len(sys.argv) > 1 else PASTA / "dist" / "cacador.html")
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(gerar(), encoding="utf-8")
    print(f"{saida} ({saida.stat().st_size // 1024} KB)")
