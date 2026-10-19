from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict

from fin_ai_lab.core.errors import ConfigError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    sec_user_agent: str | None = None
    fred_api_key: str | None = None
    ntfy_topic: str | None = None
    fin_ai_lab_max_run_cost_usd: Decimal = Decimal(0)

    def require_gemini_api_key(self) -> str:
        if not self.gemini_api_key:
            raise ConfigError("GEMINI_API_KEY")
        return self.gemini_api_key

    def require_groq_api_key(self) -> str:
        if not self.groq_api_key:
            raise ConfigError("GROQ_API_KEY")
        return self.groq_api_key

    def require_sec_user_agent(self) -> str:
        if not self.sec_user_agent:
            raise ConfigError("SEC_USER_AGENT")
        return self.sec_user_agent

    def require_fred_api_key(self) -> str:
        if not self.fred_api_key:
            raise ConfigError("FRED_API_KEY")
        return self.fred_api_key

    def require_ntfy_topic(self) -> str:
        if not self.ntfy_topic:
            raise ConfigError("NTFY_TOPIC")
        return self.ntfy_topic
