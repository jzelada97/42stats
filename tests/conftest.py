"""Los tests no deben esperar de verdad: se anulan las pausas que respetan el límite de 2 peticiones por segundo de 42."""
import pytest

from stats42 import auth as authmod
from stats42 import probe as probemod


@pytest.fixture(autouse=True)
def no_real_waiting(monkeypatch):
    monkeypatch.setattr(authmod, "_sleep", lambda seconds: None)
    monkeypatch.setattr(probemod, "DEFAULT_PAUSE", 0)
