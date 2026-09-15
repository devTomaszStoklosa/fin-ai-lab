from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict

from fin_ai_lab.core.errors import ConfigError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str | None = None
    fin_ai_lab_max_run_cost_usd: Decimal = Decimal(0)

    def require_gemini_api_key(self) -> str:
        if not self.gemini_api_key:
            raise ConfigError("GEMINI_API_KEY")
        return self.gemini_api_key
