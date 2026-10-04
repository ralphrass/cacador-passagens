"""Ponto de entrada único dos dois serviços no Railway.

A variável SERVICO escolhe o que roda:
- SERVICO=web: a página de chat com o agente (porta da variável PORT).
- qualquer outro valor ou vazio: o coletor, que fica rodando e coleta uma vez por dia
  na hora HORA_COLETA_UTC (padrão 10, ou seja, 7h de Brasília).
"""
import logging
import os
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger("iniciar")


def proxima_coleta(agora, hora):
    alvo = agora.replace(hour=hora, minute=0, second=0, microsecond=0)
    return alvo if alvo > agora else alvo + timedelta(days=1)


def rodar_coletor():
    import coletor

    hora = int(os.environ.get("HORA_COLETA_UTC", 10))
    while True:
        alvo = proxima_coleta(datetime.now(timezone.utc), hora)
        log.info("Próxima coleta em %s UTC", alvo.strftime("%d/%m %H:%M"))
        time.sleep(max(0, (alvo - datetime.now(timezone.utc)).total_seconds()))
        try:
            coletor.main()
        except Exception:
            log.exception("A coleta falhou; tento de novo amanhã")


def rodar_web():
    import uvicorn

    import web

    uvicorn.run(web.app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if os.environ.get("SERVICO", "").strip().lower() == "web":
        rodar_web()
    else:
        if os.environ.get("COLETAR_AGORA") == "1":  # uma coleta já, depois segue o horário normal
            import coletor
            coletor.main()
        rodar_coletor()
