import pytest

from fin_ai_lab.core.config import Settings
from fin_ai_lab.core.errors import ConfigError


def test_settings_load_gemini_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    settings = Settings(_env_file=None)

    assert settings.gemini_api_key == "test-key"


def test_require_gemini_api_key_raises_config_error_when_missing() -> None:
    settings = Settings(_env_file=None, gemini_api_key=None)

    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        settings.require_gemini_api_key()


def test_require_gemini_api_key_returns_key_when_set() -> None:
    settings = Settings(_env_file=None, gemini_api_key="test-key")

    assert settings.require_gemini_api_key() == "test-key"
