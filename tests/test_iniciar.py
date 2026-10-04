from datetime import datetime, timezone

from iniciar import proxima_coleta


def test_proxima_coleta_hoje_ou_amanha():
    antes = datetime(2026, 10, 4, 9, 30, tzinfo=timezone.utc)
    depois = datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc)
    assert proxima_coleta(antes, 10) == datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc)
    assert proxima_coleta(depois, 10) == datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)
