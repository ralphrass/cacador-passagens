# Coletor de preços de passagens

Roda uma vez por dia no Railway, às 7h de Brasília (10:00 UTC, mude com `HORA_COLETA_UTC`), e grava no Postgres:

| Tabela | O que guarda | Fonte |
|---|---|---|
| `rotas` | As 10 rotas ativas saindo de GRU (Lisboa, Madri, Paris, Roma, Londres, Frankfurt, Munique, Berlim, Amsterdã, Dublin) | lista no `schema.sql` |
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
5. O `railway.json` roda `python iniciar.py`, que fica no ar e dispara a coleta no horário (não usa o cron do Railway). O próprio coletor cria as tabelas na primeira execução. Com `COLETAR_AGORA=1` ele coleta assim que sobe (e em cada novo deploy, enquanto a variável existir).

Variáveis opcionais: `MESES_A_FRENTE` (padrão 6), `LIMITE_MENSAL_SERPAPI` (padrão 220).

## Agente de IA (página web)

`web.py` serve um chat em que você pergunta em português ("qual o mês mais barato para Lisboa?") e o Claude responde consultando o banco. O agente (`agente.py`) usa o tool runner do SDK da Anthropic com uma ferramenta, `consultar_sql`, que roda **um único SELECT** numa transação somente leitura (limite de 15 s e 200 linhas).

Para subir no Railway, no mesmo projeto:
1. **New > GitHub Repo** e escolha este repositório de novo (vira um segundo serviço).
2. Em **Variables**: `SERVICO` = `web`, `PORT` = `8080`, `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`, `ANTHROPIC_API_KEY` (console.anthropic.com) e `APP_SENHA` (a senha da página; o usuário é `ralph`, ou defina `APP_USUARIO`).
3. Em **Settings > Networking**, clique em **Generate Domain** para ter a URL.

## Planejador de viagens (no mesmo chat)

No chat dá para pedir "monte um roteiro de 10 dias em Portugal em março, gosto de vinho e trilha". O agente:
- cruza com os preços do banco (quanto está a passagem nessas datas, se há datas mais baratas perto);
- vê o clima com a [Open-Meteo](https://open-meteo.com) (`planejador.py`, sem chave): previsão para os próximos 15 dias ou clima típico das mesmas datas nos últimos 3 anos;
- pesquisa na web (ferramenta `web_search` da Anthropic) regras de entrada para brasileiros, vacinas e eventos;
- salva o roteiro em `viagens` e o checklist em `itens_viagem`: roupas, mala, documentos e tarefas com prazo.

A página **/viagens** mostra os roteiros salvos e o checklist para marcar. Com `RESEND_API_KEY` e `ALERTA_EMAIL` no serviço do coletor, `lembretes.py` manda e-mail junto com a coleta diária: prazo de documento ou tarefa a 7 dias e na véspera, e o que falta na mala quando a viagem está a 3 dias.

Com a confirmação do Ralph, o agente também pode passar a monitorar um destino novo (`monitorar_destino` grava em `rotas`).

Não precisa de variável nova. A busca na web é cobrada à parte pela Anthropic (US$ 10 por mil buscas) e precisa estar liberada para a organização no console da Anthropic (costuma vir liberada).

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
    ('Viena', 'VIE', 'VIE', true),
```
