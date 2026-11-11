# Coletor de preços de passagens

Roda uma vez por dia no Railway, às 7h de Brasília (10:00 UTC, mude com `HORA_COLETA_UTC`), e grava no Postgres:

| Tabela | O que guarda | Fonte |
|---|---|---|
| `rotas` | As 14 rotas principais (mais 19 trechos só com preço diário, veja abaixo): 13 saindo de GRU (Lisboa, Madri, Paris, Roma, Londres, Frankfurt, Munique, Berlim, Amsterdã, Dublin, Maceió, Natal, Aracaju) e Passo Fundo saindo de GRU, CGH ou VCP, qualquer mês, viagens de 2 a 15 dias | lista no `schema.sql` |
| `precos_tp` | Ida e volta de 7 a 15 dias nos próximos 6 meses, um retrato por dia | Travelpayouts (grátis) |
| `descoberta` | Destinos mais baratos saindo de São Paulo | Travelpayouts (grátis) |
| `buscas` + `ofertas` | Busca confirmada no Google Flights: menor preço, nível, faixa típica e voos | SerpApi (cota) |
| `alertas` | Avisos já enviados por e-mail (para não repetir) | |
| `historico_google` | ~60 dias de preço diário que o Google devolve em cada busca | SerpApi |

## Como a cota da SerpApi é poupada

Para cada rota, o coletor pega o par de datas mais barato visto hoje na Travelpayouts, com ida dentro da janela `IDA_DE`–`IDA_ATE`, e só busca na SerpApi quando:
- **agenda:** já passou o intervalo desde a última busca da rota (viagem a mais de 60 dias: 7 dias; de 30 a 60: 3 dias; menos de 30: diário), ou
- **queda:** o preço de hoje está mais de 15% abaixo da mediana dos últimos 30 dias.

Antes de buscar, consulta o uso do mês na conta (não gasta cota) e divide o que falta até `LIMITE_MENSAL_SERPAPI` (padrão 220 de 250) igualmente pelos dias restantes do mês. Se num dia mais rotas pedirem busca do que o orçamento permite, as quedas vão primeiro e depois as rotas buscadas há mais tempo; o resto fica para o dia seguinte.

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
5. O `railway.json` roda `python iniciar.py`, que fica no ar e dispara a coleta no horário (não usa o cron do Railway). O próprio coletor cria as tabelas na primeira execução. Com `COLETAR_AGORA=1` ele coleta assim que sobe (e em cada novo deploy, enquanto a variável existir).

Variáveis opcionais: `MESES_A_FRENTE` (padrão 6), `LIMITE_MENSAL_SERPAPI` (padrão 220), `IDA_DE` e `IDA_ATE` (janela de ida das buscas confirmadas na SerpApi; padrão 01/01/2027 a 31/03/2027; deixe vazias para desligar).

## Agente de IA (página web)

`web.py` serve, em `/chat`, um chat em que você pergunta em português ("qual o mês mais barato para Lisboa?") e o Claude responde consultando o banco. O agente (`agente.py`) usa o tool runner do SDK da Anthropic com uma ferramenta, `consultar_sql`, que roda **um único SELECT** numa transação somente leitura (limite de 15 s e 200 linhas).

Para subir no Railway, no mesmo projeto:
1. **New > GitHub Repo** e escolha este repositório de novo (vira um segundo serviço).
2. Em **Variables**: `SERVICO` = `web`, `PORT` = `8080`, `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`, `ANTHROPIC_API_KEY` (console.anthropic.com) e `APP_SENHA` (a senha da página; o usuário é `ralph`, ou defina `APP_USUARIO`).
3. Em **Settings > Networking**, clique em **Generate Domain** para ter a URL.

## Site de análise (página inicial)

O serviço web abre o site em `/` e o chat com o assistente em `/chat`. O site (`site.html`) tem quatro telas:

- **Promoções**: datas com preço pelo menos 12% abaixo do normal do trecho, em lista ou no mapa, com filtro por mês de ida. Um trecho pode ter mais de uma promoção, em datas diferentes.
- **Trechos**: todos os destinos ativos, com busca. Cada trecho abre a análise: menor preço de hoje, normal dos últimos 90 dias, gráfico do histórico, gráfico do preço por data de ida e as melhores datas.
- **Alertas**: cria, lista e remove alertas de preço (trecho, preço máximo e meses de ida) e mostra os avisos já enviados.
- **Coletas**: o diário das coletas (trechos com preço, preços gravados, buscas no Google, avisos) e as últimas conferências no Google Flights.

`painel.py` monta tudo em `/api/dados`. O "normal" de um trecho é a mediana do menor preço de cada coleta nos últimos 90 dias e só existe a partir de 5 coletas. Os alertas ficam em `regras_alerta`; no fim de cada coleta, `alertas.py` compara cada regra com o menor preço do dia e manda o e-mail (o mesmo alerta só repete se o preço cair mais 5%). Cada execução do coletor grava uma linha em `coletas`.

### Trechos só com preço diário

A coluna `confirmar` da tabela `rotas` separa dois níveis. Com `true` (as rotas principais), o trecho entra na fila de buscas da SerpApi. Com `false`, ele só recebe o preço diário gratuito da Travelpayouts, então a lista pode crescer sem diluir a cota. Para um destino novo aparecer no mapa, inclua as coordenadas em `COORDENADAS`, no `painel.py`.

## Rodar e testar localmente

```bash
pip install -r requirements.txt pytest httpx
DATABASE_URL=postgresql://... SERPAPI_KEY=... TRAVELPAYOUTS_TOKEN=... python coletor.py
SERVICO=web DATABASE_URL=postgresql://... ANTHROPIC_API_KEY=... APP_SENHA=teste python iniciar.py
TEST_DATABASE_URL=postgresql://... pytest -q    # apaga e recria o schema public desse banco!
```

## Mudar as rotas

A lista no fim do `schema.sql` é a fonte da verdade e é aplicada no início de cada coleta. Para tirar uma rota, troque `ativa` para `false` (o histórico continua no banco); para incluir, acrescente uma linha com o código de cidade da Travelpayouts e os aeroportos da SerpApi:

```sql
    ('Viena',     'VIE', 'VIE',     true,  NULL),
```

A última coluna (`meses_ida`) limita as idas daquela rota a certos meses e, quando preenchida, substitui a janela global. Maceió, Natal e Aracaju usam `'{11,12,2,3}'`: novembro, dezembro, fevereiro e março, sem janeiro.
