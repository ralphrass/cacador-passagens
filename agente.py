"""Agente de IA que responde perguntas sobre o banco de preços usando o Claude."""
import json
import os
from datetime import date

import anthropic
import psycopg
from anthropic import beta_tool

import planejador

MODELO = "claude-opus-5-5"
MAX_LINHAS = 200

SISTEMA = """Você é o assistente de viagens do Ralph: caça preços de passagens e planeja as viagens. \
Responda sempre em português do Brasil, de forma direta e conversada, citando os números que encontrou \
(preços em R$, datas em dd/mm/aaaa). O Ralph é brasileiro, mora em São Paulo e viaja a partir de GRU.

## Preços
Use consultar_sql para ler o banco Postgres antes de falar de preço. Ela só permite leitura. \
Se uma consulta der erro, corrija e tente de novo. Não invente preços: se o banco não tem dado suficiente, diga isso. \
Os preços coletados são de ida e volta de 7 a 15 dias saindo de GRU.

## Planejar viagens
Quando o Ralph pedir um roteiro ou ajuda com uma viagem:
1. Entenda destino, datas (ou mês), quem vai, gostos e ritmo. Se faltar algo essencial, pergunte numa frase só; \
para o resto, assuma algo razoável e diga o que assumiu.
2. Cruze com os preços do banco: quanto está a passagem para essas datas ou mês, se há datas próximas mais \
baratas e se o preço está bom (faixa típica do Google na tabela buscas). Se o destino não é monitorado, \
ofereça monitorar com monitorar_destino (só depois que ele confirmar).
3. Veja o clima com consultar_clima para as datas da viagem.
4. Use web_search para o que muda com o tempo: exigências de entrada para brasileiros (visto, ETIAS na Europa, \
ETA no Reino Unido, ESTA ou visto nos EUA, validade mínima do passaporte), vacinas, eventos e festivais \
nas datas, horários e ingressos que esgotam. Cite a fonte e a data da informação quando for regra de entrada.
5. Monte o roteiro dia a dia (manhã, tarde, noite), agrupando atrações próximas, com dicas de transporte, \
reservas antecipadas e custos aproximados, adequado ao clima e aos gostos.
6. Salve tudo: salvar_viagem com o roteiro em markdown, e salvar_itens com o checklist:
   - roupa: peças e quantidades para o clima, as atividades e o número de dias (camadas, calçado de caminhada, \
roupa de chuva, traje para restaurante etc.);
   - mala: tomada e adaptador, remédios, eletrônicos, itens específicos do destino;
   - documento: passaporte, visto ou autorização eletrônica, seguro viagem (obrigatório no Espaço Schengen), \
vacinas, CNH/PID, cartões; com prazo realista (ex.: pedir visto americano com meses de antecedência);
   - tarefa: comprar a passagem, reservar hospedagem, ingressos que esgotam, avisar o banco, chip/eSIM, \
check-in online; cada uma com prazo.
   Os prazos geram lembretes por e-mail. Depois diga que está tudo na página Minhas viagens.
Para ajustar uma viagem já salva, leia viagens e itens_viagem com consultar_sql e use viagem_id e atualizar_itens.

## Tabelas

Tabelas:
- rotas(id, nome, origem, destino_tp, destino_serpapi, ativa): destinos monitorados. destino_tp é o código \
de cidade (LIS, MAD, PAR, ROM, LON, SCL, ORL, NYC).
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
- viagens(id, criada_em, titulo, destino, ida, volta, pessoas, preferencias, roteiro): viagens planejadas.
- itens_viagem(id, viagem_id, tipo, descricao, prazo, feito): checklist de cada viagem; tipo é roupa, mala, \
documento ou tarefa.

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


BUSCA_WEB = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8,
             "user_location": {"type": "approximate", "city": "São Paulo", "region": "São Paulo",
                               "country": "BR", "timezone": "America/Sao_Paulo"}}
FERRAMENTAS = [consultar_sql, *planejador.FERRAMENTAS, BUSCA_WEB]
MAX_RETOMADAS = 3


def responder(historico):
    """historico: lista de {"role": "user"|"assistant", "content": str}, terminando no usuário."""
    cliente = anthropic.Anthropic()
    mensagens = list(historico)
    final = None
    for _ in range(MAX_RETOMADAS + 1):
        runner = cliente.beta.messages.tool_runner(
            model=MODELO,
            max_tokens=16000,
            system=[{"type": "text", "text": SISTEMA, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": f"Hoje é {date.today():%d/%m/%Y}."}],
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            tools=FERRAMENTAS,
            messages=mensagens,
            max_iterations=25,
        )
        # Copia o histórico enquanto roda: se a busca na web pausar o turno (pause_turn),
        # um novo runner continua de onde parou
        for final in runner:
            mensagens.append({"role": "assistant", "content": final.content})
            resposta_ferramentas = runner.generate_tool_call_response()
            if resposta_ferramentas is not None:
                mensagens.append(resposta_ferramentas)
        if final is None or final.stop_reason != "pause_turn":
            break
    if final.stop_reason == "refusal":
        return "Não consegui responder essa pergunta. Tente reformular."
    # com citações da busca na web o texto vem quebrado em vários blocos seguidos
    texto = "".join(b.text for b in final.content if b.type == "text").strip()
    return texto or "Não encontrei uma resposta. Tente perguntar de outro jeito."
