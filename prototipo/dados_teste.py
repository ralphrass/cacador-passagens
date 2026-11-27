"""Dados de teste do protótipo: preços sintéticos, mas com a forma dos dados reais.

Tudo é determinístico (mesma semente, mesmos números), para os testes e para que a
tela não mude a cada recarga. Quando os dados reais entrarem, só este módulo é trocado:
a API e as telas leem o que `montar()` devolve.

Conceitos:
- preço de um trecho = ida em um dia, volta N dias depois, o menor valor do dia.
- normal = mediana do preço do trecho naquele mês, sem promoções.
- desconto = quanto o preço está abaixo do normal (0,30 = 30% abaixo).
- raridade = quantas vezes por ano um desconto assim apareceu no histórico.
- duração = quantos dias um desconto assim costuma ficar no ar.
"""
import math
import random
from datetime import date, timedelta
from functools import lru_cache
from statistics import mean, median

DIAS_HORIZONTE = 180
SEMANAS = 26
LIMIAR_JANELA = 0.15  # 15% abaixo do normal já é uma oportunidade

FAIXAS = {
    "curta": (2, 5),
    "media": (6, 12),
    "longa": (13, 20),
}

NOMES_MES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
             "agosto", "setembro", "outubro", "novembro", "dezembro"]

SAO_PAULO = (-23.43, -46.47)

# codigo, nome, lat, lon, regiao, tags, preço base de ida e volta (R$), episódios de oferta por ano
DESTINOS = [
    ("LIS", "Lisboa", 38.77, -9.13, "Europa", ["Europa"], 5200, 4),
    ("MAD", "Madri", 40.47, -3.56, "Europa", ["Europa"], 5100, 4),
    ("PAR", "Paris", 49.01, 2.55, "Europa", ["Europa"], 5500, 3),
    ("ROM", "Roma", 41.80, 12.25, "Europa", ["Europa"], 5600, 3),
    ("LON", "Londres", 51.47, -0.45, "Europa", ["Europa"], 5900, 3),
    ("FRA", "Frankfurt", 50.04, 8.56, "Europa", ["Europa"], 5400, 2),
    ("AMS", "Amsterdã", 52.31, 4.76, "Europa", ["Europa"], 5600, 2),
    ("DUB", "Dublin", 53.42, -6.27, "Europa", ["Europa"], 5800, 2),
    ("MCZ", "Maceió", -9.51, -35.79, "Nordeste", ["Praia", "Brasil"], 1500, 6),
    ("NAT", "Natal", -5.77, -35.38, "Nordeste", ["Praia", "Brasil"], 1550, 6),
    ("AJU", "Aracaju", -10.98, -37.07, "Nordeste", ["Praia", "Brasil"], 1450, 5),
    ("PFB", "Passo Fundo", -28.24, -52.33, "Sul", ["Família", "Brasil"], 900, 8),
    ("BUE", "Buenos Aires", -34.82, -58.54, "América do Sul", ["América do Sul"], 1750, 5),
    ("SCL", "Santiago", -33.39, -70.79, "América do Sul", ["América do Sul"], 2150, 4),
    ("MIA", "Miami", 25.79, -80.29, "EUA", ["EUA"], 4100, 3),
]

# Fator de temporada pelo mês de ida (1 = preço normal do ano)
TEMPORADA = {
    "Europa": [1.15, 0.95, 0.88, 0.92, 0.97, 1.08, 1.22, 1.15, 0.98, 0.95, 0.97, 1.20],
    "Nordeste": [1.30, 1.05, 0.90, 0.85, 0.85, 0.95, 1.20, 1.00, 0.90, 0.95, 1.00, 1.35],
    "Sul": [1.10, 1.00, 0.95, 0.95, 1.00, 1.00, 1.10, 1.00, 0.95, 1.00, 1.00, 1.25],
    "América do Sul": [1.15, 1.05, 0.92, 0.90, 0.95, 1.05, 1.20, 1.05, 0.95, 0.95, 0.98, 1.15],
    "EUA": [1.20, 0.95, 0.95, 1.00, 0.95, 1.10, 1.25, 1.10, 0.90, 0.92, 1.05, 1.25],
}


def rumo(origem, destino):
    """Direção da bússola de origem para destino, em graus (0 = norte, 90 = leste)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*origem, *destino))
    x = math.sin(lon2 - lon1) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return round((math.degrees(math.atan2(x, y)) + 360) % 360)


def _ruido(codigo, dia, dur):
    return random.Random(f"{codigo}|{dia.isoformat()}|{dur}").gauss(0, 0.02)


@lru_cache(maxsize=None)
def promocoes(codigo, hoje):
    """Ofertas que estão no ar agora: cada uma derruba o preço de idas em torno de um dia."""
    rnd = random.Random(f"promo|{codigo}|{hoje.isoformat()}")
    return [(rnd.randint(5, DIAS_HORIZONTE - 5), rnd.uniform(0.10, 0.40), rnd.uniform(2, 9))
            for _ in range(rnd.randint(0, 2))]


def _fator_promo(codigo, hoje, ida):
    d = (ida - hoje).days
    queda = sum(prof * math.exp(-((d - centro) ** 2) / (2 * largura ** 2))
                for centro, prof, largura in promocoes(codigo, hoje))
    return max(0.45, 1 - queda)


def preco(dest, hoje, ida, dur, com_promo=True):
    codigo, regiao, base = dest[0], dest[4], dest[6]
    valor = base * TEMPORADA[regiao][ida.month - 1]
    valor *= 1 + 0.012 * (dur - 7)
    valor *= 1.06 if ida.weekday() in (4, 5) else 1.0  # ida na sexta ou no sábado
    valor *= 1 + _ruido(codigo, ida, dur)
    if com_promo:
        valor *= _fator_promo(codigo, hoje, ida)
    return round(valor)


@lru_cache(maxsize=None)
def historico(codigo, episodios_ano):
    """Ofertas dos últimos dois anos: (desconto, dias que ficou no ar)."""
    rnd = random.Random(f"hist|{codigo}")
    total = round(episodios_ano * 2 * rnd.uniform(0.8, 1.2))
    return [(rnd.uniform(0.10, 0.42), max(1, round(rnd.expovariate(1 / 3.5)))) for _ in range(total)]


def raridade(dest, desconto):
    """Quantas vezes por ano e por quantos dias um desconto assim apareceu."""
    parecidos = [dias for desc, dias in historico(dest[0], dest[7]) if desc >= desconto - 0.02]
    if not parecidos:
        return {"vezes_ano": 0, "dura_dias": None}
    return {"vezes_ano": round(len(parecidos) / 2, 1), "dura_dias": round(mean(parecidos))}


def _meses(hoje):
    meses, d = [], hoje.replace(day=1)
    for _ in range(7):
        meses.append((d.year, d.month))
        d = (d + timedelta(days=32)).replace(day=1)
    return meses


def _destino(dest, hoje, faixa):
    dur_min, dur_max = FAIXAS[faixa]
    dias = [hoje + timedelta(days=i) for i in range(1, DIAS_HORIZONTE + 1)]

    normais = {}
    for ano, mes in _meses(hoje):
        # o normal é o menor preço de um dia comum (sem promoção), na mediana do mês
        valores = [min(preco(dest, hoje, d, dur, com_promo=False) for dur in range(dur_min, dur_max + 1))
                   for d in dias if (d.year, d.month) == (ano, mes)]
        if valores:
            normais[(ano, mes)] = round(median(valores))

    calendario = []
    for d in dias:
        valor, dur = min((preco(dest, hoje, d, dur), dur) for dur in range(dur_min, dur_max + 1))
        normal = normais[(d.year, d.month)]
        calendario.append({"ida": d.isoformat(), "dur": dur, "preco": valor, "normal": normal,
                           "desconto": round(1 - valor / normal, 3)})

    mensal = []
    for ano, mes in _meses(hoje):
        do_mes = [c for c in calendario if c["ida"].startswith(f"{ano}-{mes:02d}")]
        if do_mes:
            melhor = max(do_mes, key=lambda c: c["desconto"])
            mensal.append({"ano": ano, "mes": mes, **melhor})

    semanal = [round(max(c["desconto"] for c in calendario[s * 7:(s + 1) * 7]), 3)
               for s in range(SEMANAS) if calendario[s * 7:(s + 1) * 7]]

    return {"codigo": dest[0], "nome": dest[1], "regiao": dest[4], "tags": dest[5],
            "rumo": rumo(SAO_PAULO, (dest[2], dest[3])),
            "mensal": mensal, "semanal": semanal, "calendario": calendario}


def janelas(destinos):
    """Uma oportunidade por destino e mês com desconto de 15% ou mais, as mais raras primeiro."""
    achadas = []
    por_codigo = {d[0]: d for d in DESTINOS}
    for d in destinos:
        for m in d["mensal"]:
            if m["desconto"] >= LIMIAR_JANELA:
                achadas.append({"codigo": d["codigo"], "nome": d["nome"], "tags": d["tags"],
                                "ano": m["ano"], "mes": m["mes"], "ida": m["ida"], "dur": m["dur"],
                                "preco": m["preco"], "normal": m["normal"], "desconto": m["desconto"],
                                **raridade(por_codigo[d["codigo"]], m["desconto"])})
    return sorted(achadas, key=lambda j: (j["vezes_ano"] if j["vezes_ano"] else 0.1, -j["desconto"]))


@lru_cache(maxsize=8)
def montar(faixa="media", hoje=None):
    """Tudo o que as telas precisam, para uma faixa de duração de viagem."""
    if faixa not in FAIXAS:
        raise ValueError(f"faixa desconhecida: {faixa}")
    hoje = hoje or date.today()
    destinos = [_destino(dest, hoje, faixa) for dest in DESTINOS]
    meses = [{"ano": a, "mes": m, "nome": NOMES_MES[m - 1]} for a, m in _meses(hoje)]
    return {"hoje": hoje.isoformat(), "faixa": faixa, "dias": list(FAIXAS[faixa]),
            "meses": meses, "destinos": destinos, "janelas": janelas(destinos)}
