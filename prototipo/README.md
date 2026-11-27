# Protótipo do novo caçador

Telas de visão geral sobre **dados de teste**, para validar a ideia antes de ligar os dados reais.
O sistema antigo (coletor, site, chat) continua intacto na raiz do repositório.

## Ideia

Duas jornadas, sem formulário de origem, destino e data:

- **Tenho uma viagem** (Início, "Suas viagens"): a pessoa diz para onde e mais ou menos quando; o sistema vigia e mostra se a janela está aberta.
- **Me mostra uma oportunidade** (Início, "Oportunidades", e Explorar): tudo o que está abaixo do normal agora.

Não há orçamento. O critério é sempre **quanto abaixo do normal** está o preço daquele trecho, mais a **raridade** (quantas vezes por ano aparece) e **quanto tempo costuma durar**.

## Telas

- **Início**: suas viagens e as oportunidades (15% ou mais abaixo do normal), as mais raras primeiro.
- **Explorar > Radar**: São Paulo no centro, um anel por mês, destinos na direção do mapa. Ponto maior e mais escuro = mais abaixo do normal.
- **Explorar > Ondas**: uma onda por destino, semana a semana, nos próximos 6 meses.
- **Trecho**: calendário colorido por dia de ida, com o detalhe do dia.
- **Nova viagem**: nome, destinos, meses e duração.

A duração (curtas 2–5 dias, médias 6–12, longas 13–20) muda tudo de uma vez.

## Rodar

```bash
pip install -r requirements.txt
uvicorn prototipo.app:app --reload          # http://localhost:8000
SERVICO=prototipo python iniciar.py         # igual, na porta PORT (para o Railway)
python -m prototipo.gerar_estatico          # um HTML só, com os dados embutidos, em prototipo/dist/
pytest -q tests/test_prototipo.py
```

## Arquivos

- `dados_teste.py`: gera preços sintéticos e determinísticos (temporada, dia da semana, promoções, histórico de ofertas). É o único módulo a trocar quando os dados reais entrarem: as telas leem o que `montar()` devolve.
- `app.py`: API (`/api/dados?faixa=`, `/api/viagens`) e a página. As viagens ficam na memória e somem quando o servidor reinicia.
- `index.html`: as telas, sem dependências.
- `gerar_estatico.py`: a versão em um arquivo só, em que as viagens ficam no navegador.
