import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def disable_external_llm(monkeypatch: pytest.MonkeyPatch):
    """Tests must never spend tokens or depend on the configured external provider."""
    monkeypatch.setattr(settings, "llm_api_key", "")
