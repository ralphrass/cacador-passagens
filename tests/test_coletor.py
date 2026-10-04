"""Testes com Postgres de verdade e APIs simuladas.

    TEST_DATABASE_URL=postgresql://postgres@localhost:5432/postgres pytest -q
"""
import os
from datetime import date, datetime, timedelta, timezone

import psycopg
import pytest

import coletor
import fontes

HOJE = date(2026, 10, 4)


@pytest.fixture
def conn():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL não definido")
    with psycopg.connect(url) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        c.execute(open(os.path.join(os.path.dirname(coletor.__file__), "schema.sql")).read())
        c.commit()
        yield c


def rotas(conn):
    return conn.execute(
        "SELECT id, nome, origem, destino_tp, destino_serpapi FROM rotas ORDER BY id").fetchall()


def resposta_serp(preco=4158):
    ts = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp())
    return {
        "price_insights": {"lowest_price": preco, "price_level": "typical",
                           "typical_price_range": [3800, 4550],
                           "price_history": [[ts, 4300], [ts + 86400, 4200]]},
        "best_flights": [{"price": preco, "total_duration": 540, "flights": [{
            "airline": "TAP Air Portugal",
            "departure_airport": {"id": "GRU", "time": "2026-11-18 23:15"},
            "arrival_airport": {"id": "LIS", "time": "2026-11-19 12:15"}}]}],
        "other_flights": [],
    }


def test_intervalo_por_antecedencia():
    assert coletor.intervalo_dias(90) == 7
    assert coletor.intervalo_dias(45) == 3
    assert coletor.intervalo_dias(10) == 1


def test_meses_vira_o_ano():
    assert list(coletor.meses_seguintes(date(2026, 11, 1), 3)) == ["2026-11", "2026-12", "2027-01"]


def test_tp_filtra_duracao_e_aeroporto(conn, monkeypatch):
    monkeypatch.setattr(coletor, "MESES_A_FRENTE", 1)
    monkeypatch.setattr(fontes, "tp_ida_volta", lambda destino, mes: [
        {"price": 4000, "departure_at": "2026-11-10T10:00:00-03:00",
         "return_at": "2026-11-20T10:00:00+00:00", "origin_airport": "GRU", "link": "/x"},
        {"price": 3000, "departure_at": "2026-11-10T10:00:00-03:00",
         "return_at": "2026-11-13T10:00:00+00:00", "origin_airport": "GRU"},   # 3 dias
        {"price": 2500, "departure_at": "2026-11-10T10:00:00-03:00",
         "return_at": "2026-11-20T10:00:00+00:00", "origin_airport": "VCP"},   # outro aeroporto
    ])
    coletor.coletar_tp(conn, rotas(conn)[:1], HOJE)
    linhas = conn.execute("SELECT dias, preco, link FROM precos_tp").fetchall()
    assert len(linhas) == 1
    assert linhas[0][0] == 10 and linhas[0][2] == "https://www.aviasales.com/x"


def test_primeira_execucao_busca_todas_as_rotas(conn, monkeypatch):
    feitas = []
    monkeypatch.setattr(fontes, "serp_uso_mes", lambda: 0)
    monkeypatch.setattr(fontes, "serp_voos",
                        lambda o, d, i, v: feitas.append(d) or resposta_serp())
    coletor.buscar_serpapi(conn, rotas(conn), HOJE)
    assert len(feitas) == 8
    assert conn.execute("SELECT count(*) FROM historico_google").fetchone()[0] == 16
    assert conn.execute("SELECT trajeto FROM ofertas LIMIT 1").fetchone()[0] == "GRU > LIS"


def test_respeita_limite_mensal(conn, monkeypatch):
    feitas = []
    monkeypatch.setattr(fontes, "serp_uso_mes", lambda: coletor.LIMITE_MENSAL - 2)
    monkeypatch.setattr(fontes, "serp_voos", lambda *a: feitas.append(a) or resposta_serp())
    coletor.buscar_serpapi(conn, rotas(conn), HOJE)
    assert len(feitas) == 2


def test_agenda_semanal_e_queda(conn):
    rs = rotas(conn)
    lis = rs[0][0]
    ida = HOJE + timedelta(days=90)
    # todas as rotas buscadas há 2 dias: viagem a 90 dias só volta em 7 dias
    for r in rs:
        conn.execute("INSERT INTO buscas (rota_id, ida, volta, motivo, buscado_em) "
                     "VALUES (%s, %s, %s, 'agenda', %s)",
                     (r[0], ida, ida + timedelta(days=10), HOJE - timedelta(days=2)))
    # Lisboa: 10 dias a ~5000 e hoje 3900 (queda de mais de 15%)
    for d in range(1, 11):
        conn.execute("INSERT INTO precos_tp (coletado_em, rota_id, ida, volta, dias, preco) "
                     "VALUES (%s, %s, %s, %s, 10, %s)",
                     (HOJE - timedelta(days=d), lis, ida, ida + timedelta(days=10), 5000))
    conn.execute("INSERT INTO precos_tp (coletado_em, rota_id, ida, volta, dias, preco) "
                 "VALUES (%s, %s, %s, %s, 10, 3900)", (HOJE, lis, ida, ida + timedelta(days=10)))
    candidatas = coletor.escolher_buscas(conn, rs, HOJE)
    # só Lisboa (queda); as demais caem em data padrão (45 dias -> a cada 3 dias), ainda não devidas
    assert [(c[0], c[3]) for c in candidatas] == [("queda", "Lisboa")]
