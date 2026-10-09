"""Agente de IA que responde perguntas sobre o banco de preços usando o Claude."""
import json
import os
from datetime import date

import anthropic
import psycopg
from anthropic import beta_tool

MODELO = "claude-opus-5-5"
MAX_LINHAS = 200

SISTEMA = """Você é o assistente do Caçador de Passagens do Ralph. Responda sempre em português do Brasil, \
de forma direta e conversada, citando os números que encontrou (preços em R$, datas em dd/mm/aaaa).

Use a ferramenta consultar_sql para ler o banco Postgres antes de responder. Ela só permite leitura. \
Se uma consulta der erro, corrija e tente de novo. Não invente preços: se o banco não tem dado suficiente, diga isso.

Todas as viagens saem de GRU (São Paulo) e são ida e volta de 7 a 15 dias.

Tabelas:
- rotas(id, nome, origem, destino_tp, destino_serpapi, ativa): destinos monitorados. destino_tp é o código \
de cidade (ex.: LIS, MAD, PAR, FRA, AMS, DUB). Considere só ativa = true, a não ser que \
perguntem por rotas antigas.
- precos_tp(coletado_em, rota_id, ida, volta, dias, preco, cia, conexoes_ida, conexoes_volta, link): \
preços em cache da Travelpayouts/Aviasales, um retrato por dia de coleta. Bom para comparar meses e datas. \
Os preços podem ter de 2 a 7 dias de idade.
- descoberta(coletado_em, destino, ida, volta, preco, conexoes): destinos mais baratos saindo de São Paulo \
para qualquer lugar. destino é um código IATA de cidade.
- buscas(id, buscado_em, rota_id, ida, volta, motivo, menor_preco, nivel, faixa_min, faixa_max): \
preço confirmado no Google Flights. nivel é low/typical/high; faixa_min e faixa_max são a faixa típica do Google.
- ofertas(busca_id, preco, cias, trajeto, escalas, duracao_min, partida): voos de cada busca.
- historico_google(rota_id, ida, volta, dia, preco): preço diário que o Google mostrava para aquelas datas.
- alertas(enviado_em, busca_id, rota_id, ida, volta, preco, motivo): avisos já enviados por e-mail.

Dicas: o preço mais recente da Travelpayouts para cada data está no maior coletado_em; para "qual mês é mais \
barato", agrupe precos_tp por date_trunc('month', ida) usando só a coleta mais recente; para dizer se um preço \
está bom, compare com faixa_min/faixa_max e nivel da tabela buscas."""


@beta_tool
def consultar_sql(sql: str) -> str:
    """Executa uma consulta SQL de leitura (um único SELECT) no banco Postgres de preços.

    Args:
        sql: Um único comando SELECT ou WITH. Retorna no máximo 200 linhas em JSON.
    """
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("SET LOCAL statement_timeout = '15s'")
            # prepare=True usa o protocolo estendido, que recusa vários comandos de uma vez
            cur = conn.execute(sql, prepare=True)
            if cur.description is None:
                return "A consulta não devolveu linhas."
            colunas = [c.name for c in cur.description]
            linhas = cur.fetchmany(MAX_LINHAS + 1)
            conn.rollback()
    except psycopg.Error as e:
        return f"Erro do Postgres: {str(e).strip()}"
    resultado = {"colunas": colunas, "linhas": linhas[:MAX_LINHAS]}
    if len(linhas) > MAX_LINHAS:
        resultado["aviso"] = f"Resultado cortado em {MAX_LINHAS} linhas; agregue ou filtre mais."
    return json.dumps(resultado, default=str, ensure_ascii=False)


def preferencia():
    de, ate = os.environ.get("IDA_DE", "2027-01-01"), os.environ.get("IDA_ATE", "2027-02-28")
    if not (de and ate):
        return ""
    return (f"O Ralph quer viajar com ida entre {date.fromisoformat(de):%d/%m/%Y} e "
            f"{date.fromisoformat(ate):%d/%m/%Y}; priorize essas datas quando a pergunta não disser outra época.")


def responder(historico):
    """historico: lista de {"role": "user"|"assistant", "content": str}, terminando no usuário."""
    cliente = anthropic.Anthropic()
    runner = cliente.beta.messages.tool_runner(
        model=MODELO,
        max_tokens=16000,
        system=[{"type": "text", "text": SISTEMA, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": f"Hoje é {date.today():%d/%m/%Y}. {preferencia()}"}],
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        tools=[consultar_sql],
        messages=historico,
        max_iterations=15,
    )
    final = runner.until_done()
    if final.stop_reason == "refusal":
        return "Não consegui responder essa pergunta. Tente reformular."
    texto = "\n".join(b.text for b in final.content if b.type == "text").strip()
    return texto or "Não encontrei uma resposta. Tente perguntar de outro jeito."
