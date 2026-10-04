# Coletor de preços de passagens

Roda uma vez por dia no Railway, às 7h de Brasília (10:00 UTC), e grava no Postgres:

| Tabela | O que guarda | Fonte |
|---|---|---|
| `rotas` | As 8 rotas saindo de GRU (Lisboa, Madri, Paris, Roma, Londres, Santiago, Orlando, Nova York) | fixa, edite à vontade |
| `precos_tp` | Ida e volta de 7 a 15 dias nos próximos 6 meses, um retrato por dia | Travelpayouts (grátis) |
| `descoberta` | Destinos mais baratos saindo de São Paulo | Travelpayouts (grátis) |
| `buscas` + `ofertas` | Busca confirmada no Google Flights: menor preço, nível, faixa típica e voos | SerpApi (cota) |
| `alertas` | Avisos já enviados por e-mail (para não repetir) | |
| `historico_google` | ~60 dias de preço diário que o Google devolve em cada busca | SerpApi |

## Como a cota da SerpApi é poupada

Para cada rota, o coletor pega o par de datas mais barato visto hoje na Travelpayouts e só busca na SerpApi quando:
- **agenda:** já passou o intervalo desde a última busca da rota (viagem a mais de 60 dias: 7 dias; de 30 a 60: 3 dias; menos de 30: diário), ou
- **queda:** o preço de hoje está mais de 15% abaixo da mediana dos últimos 30 dias.

Antes de buscar, consulta o uso do mês na conta (não gasta cota) e para em `LIMITE_MENSAL_SERPAPI` (padrão 220 de 250).

## Alertas por e-mail

No fim de cada execução, olha as buscas confirmadas na SerpApi e manda **um e-mail** com os preços bons:
- o Google classificou o preço como baixo (`low`), ou
- o preço ficou abaixo da faixa típica do Google, ou
- caiu mais de 15% em relação à mediana das buscas anteriores da rota.

O mesmo trecho (rota + datas) só é avisado de novo se cair mais 5%. O envio usa o [Resend](https://resend.com) pela API HTTPS (o Railway bloqueia SMTP em vários planos). Sem domínio próprio, o remetente `onboarding@resend.dev` só pode enviar para o e-mail da sua conta no Resend.

## Subir no Railway

1. Suba esta pasta para um repositório no GitHub.
2. No Railway: **New Project > Deploy from GitHub repo** e escolha o repositório.
3. No mesmo projeto: **New > Database > PostgreSQL**.
4. No serviço do coletor, em **Variables**:
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
   - `SERPAPI_KEY` = sua chave
   - `TRAVELPAYOUTS_TOKEN` = seu token (opcional; sem ele, usa datas padrão)
   - `RESEND_API_KEY` e `ALERTA_EMAIL` (opcionais; sem eles, não envia alertas)
5. O `railway.json` já define o cron diário e o comando `python coletor.py`. O próprio coletor cria as tabelas na primeira execução.

Variáveis opcionais: `MESES_A_FRENTE` (padrão 6), `LIMITE_MENSAL_SERPAPI` (padrão 220).

## Rodar e testar localmente

```bash
pip install -r requirements.txt pytest
DATABASE_URL=postgresql://... SERPAPI_KEY=... TRAVELPAYOUTS_TOKEN=... python coletor.py
TEST_DATABASE_URL=postgresql://... pytest -q    # apaga e recria o schema public desse banco!
```

## Mudar as rotas

```sql
UPDATE rotas SET ativa = false WHERE nome = 'Orlando';
INSERT INTO rotas (nome, destino_tp, destino_serpapi) VALUES ('Amsterdã', 'AMS', 'AMS');
```
