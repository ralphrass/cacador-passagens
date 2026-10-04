"""Coletor diário de preços de passagens.

1. Travelpayouts (grátis): ida e volta de 7 a 15 dias para cada rota, próximos meses.
2. Travelpayouts (grátis): descoberta "de GRU para qualquer lugar".
3. SerpApi (cota): confirma no Google Flights o par de datas mais barato de cada rota,
   seguindo a agenda por antecedência ou quando há uma queda forte de preço.
"""
import logging
import os
import statistics
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

import fontes

log = logging.getLogger("coletor")

DIAS_MIN, DIAS_MAX = 7, 15
MESES_A_FRENTE = int(os.environ.get("MESES_A_FRENTE", 6))
LIMITE_MENSAL = int(os.environ.get("LIMITE_MENSAL_SERPAPI", 220))
QUEDA = Decimal("0.85")  # preço abaixo de 85% da mediana recente conta como queda


def intervalo_dias(antecedencia):
    """De quantos em quantos dias buscar na SerpApi, conforme a distância da viagem."""
    if antecedencia > 60:
        return 7
    if antecedencia > 30:
        return 3
    return 1


def meses_seguintes(hoje, n):
    ano, mes = hoje.year, hoje.month
    for _ in range(n):
        yield f"{ano:04d}-{mes:02d}"
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)


def _erro(e):
    """Descrição curta do erro, sem a URL (que leva o token/chave da API)."""
    status = getattr(getattr(e, "response", None), "status_code", None)
    return f"{type(e).__name__}" + (f" HTTP {status}" if status else "")


def _data(texto):
    return date.fromisoformat(texto[:10]) if texto else None


# ---------- Etapa 1 e 2: Travelpayouts ----------

def coletar_tp(conn, rotas, hoje):
    total = 0
    for rota_id, _, origem, destino_tp, _ in rotas:
        for mes in meses_seguintes(hoje, MESES_A_FRENTE):
            try:
                itens = fontes.tp_ida_volta(destino_tp, mes)
            except Exception as e:
                log.error("Travelpayouts falhou para %s %s: %s", destino_tp, mes, _erro(e))
                continue
            for v in itens:
                ida, volta = _data(v.get("departure_at")), _data(v.get("return_at"))
                if not ida or not volta or ida <= hoje:
                    continue
                if v.get("origin_airport") and v["origin_airport"] != origem:
                    continue
                dias = (volta - ida).days
                if not DIAS_MIN <= dias <= DIAS_MAX:
                    continue
                conn.execute(
                    """INSERT INTO precos_tp (rota_id, ida, volta, dias, preco, cia,
                           conexoes_ida, conexoes_volta, link)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (rota_id, ida, volta, dias, v["price"], v.get("airline"),
                     v.get("transfers"), v.get("return_transfers"),
                     "https://www.aviasales.com" + v["link"] if v.get("link") else None))
                total += 1
    log.info("Travelpayouts: %d preços gravados", total)


def coletar_descoberta(conn):
    try:
        itens = fontes.tp_descoberta()
    except Exception as e:
        log.error("Descoberta falhou: %s", _erro(e))
        return
    for v in itens:
        conn.execute(
            """INSERT INTO descoberta (destino, ida, volta, preco, conexoes)
               VALUES (%s, %s, %s, %s, %s)""",
            (v["destination"], _data(v.get("depart_date")), _data(v.get("return_date")),
             v["value"], v.get("number_of_changes")))
    log.info("Descoberta: %d destinos", len(itens))


# ---------- Etapa 3: escolher e fazer as buscas na SerpApi ----------

def escolher_buscas(conn, rotas, hoje):
    """Uma candidata por rota: o par de datas mais barato visto hoje na Travelpayouts."""
    candidatas = []
    for rota_id, nome, *_ in rotas:
        melhor = conn.execute(
            """SELECT ida, volta, preco FROM precos_tp
               WHERE rota_id = %s AND coletado_em::date = %s AND ida >= %s
               ORDER BY preco LIMIT 1""",
            (rota_id, hoje, hoje + timedelta(days=7))).fetchone()
        if melhor:
            ida, volta, preco = melhor
        else:  # sem dados da Travelpayouts: data padrão daqui a 45 dias, 10 dias de viagem
            ida, preco = hoje + timedelta(days=45), None
            volta = ida + timedelta(days=10)

        ultima = conn.execute(
            "SELECT max(buscado_em)::date FROM buscas WHERE rota_id = %s",
            (rota_id,)).fetchone()[0]
        devida = ultima is None or (hoje - ultima).days >= intervalo_dias((ida - hoje).days)

        queda = False
        if preco is not None and ultima != hoje:
            recentes = [r[0] for r in conn.execute(
                """SELECT min(preco) FROM precos_tp
                   WHERE rota_id = %s AND coletado_em >= %s AND coletado_em::date < %s
                   GROUP BY coletado_em::date""",
                (rota_id, hoje - timedelta(days=30), hoje))]
            if len(recentes) >= 5 and preco < QUEDA * statistics.median(recentes):
                queda = True

        if queda or devida:
            motivo = "queda" if queda else ("agenda" if melhor else "padrao")
            candidatas.append((motivo, ultima or date.min, rota_id, nome, ida, volta))

    # quedas primeiro, depois as rotas buscadas há mais tempo
    candidatas.sort(key=lambda c: (c[0] != "queda", c[1]))
    return candidatas


def gravar_busca(conn, rota_id, ida, volta, motivo, dados):
    ins = dados.get("price_insights", {})
    faixa = ins.get("typical_price_range") or [None, None]
    busca_id = conn.execute(
        """INSERT INTO buscas (rota_id, ida, volta, motivo, menor_preco, nivel,
               faixa_min, faixa_max, resposta)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (rota_id, ida, volta, motivo, ins.get("lowest_price"), ins.get("price_level"),
         faixa[0], faixa[1], Jsonb(dados))).fetchone()[0]

    for op in dados.get("best_flights", []) + dados.get("other_flights", []):
        trechos = op.get("flights", [])
        if not trechos:
            continue
        conn.execute(
            """INSERT INTO ofertas (busca_id, preco, cias, trajeto, escalas, duracao_min, partida)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (busca_id, op.get("price"),
             ", ".join(sorted({t["airline"] for t in trechos})),
             " > ".join([trechos[0]["departure_airport"]["id"]]
                        + [t["arrival_airport"]["id"] for t in trechos]),
             len(trechos) - 1, op.get("total_duration"),
             trechos[0]["departure_airport"].get("time")))

    for ts, preco in ins.get("price_history", []):
        dia = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        conn.execute(
            """INSERT INTO historico_google (rota_id, ida, volta, dia, preco)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (rota_id, ida, volta, dia) DO UPDATE SET preco = EXCLUDED.preco""",
            (rota_id, ida, volta, dia, preco))
    return busca_id


def buscar_serpapi(conn, rotas, hoje):
    origem_por_rota = {r[0]: (r[2], r[4]) for r in rotas}
    try:
        usadas = fontes.serp_uso_mes()
    except Exception as e:
        log.error("Não consegui ler a cota da SerpApi; pulando buscas pagas: %s", _erro(e))
        return
    for motivo, _, rota_id, nome, ida, volta in escolher_buscas(conn, rotas, hoje):
        if usadas >= LIMITE_MENSAL:
            log.info("Cota do mês atingida (%d/%d); parando", usadas, LIMITE_MENSAL)
            break
        origem, destino = origem_por_rota[rota_id]
        try:
            dados = fontes.serp_voos(origem, destino, ida, volta)
        except Exception as e:
            log.error("SerpApi falhou para %s: %s", nome, _erro(e))
            continue
        usadas += 1
        gravar_busca(conn, rota_id, ida, volta, motivo, dados)
        conn.commit()
        log.info("SerpApi %s %s a %s (%s): menor R$ %s", nome, ida, volta, motivo,
                 dados.get("price_insights", {}).get("lowest_price"))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    hoje = date.today()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute(Path(__file__).with_name("schema.sql").read_text())
        conn.commit()
        rotas = conn.execute(
            """SELECT id, nome, origem, destino_tp, destino_serpapi
               FROM rotas WHERE ativa ORDER BY id""").fetchall()

        if os.environ.get("TRAVELPAYOUTS_TOKEN"):
            coletar_tp(conn, rotas, hoje)
            coletar_descoberta(conn)
            conn.commit()
        else:
            log.warning("TRAVELPAYOUTS_TOKEN ausente; usando datas padrão na SerpApi")

        buscar_serpapi(conn, rotas, hoje)


if __name__ == "__main__":
    main()
