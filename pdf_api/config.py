from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENV: str = "dev"
    CORS_ORIGINS: str = "http://localhost"  # must be explicitly set in production
    MAX_PDF_BYTES: int = 10 * 1024 * 1024  # 10 MB
    MAX_CSV_BYTES: int = 5 * 1024 * 1024   # 5 MB
    LOG_DIR: str = "/app/logs/api"
    LOG_RETENTION_DAYS: int = 30

    # Local AI classifier (Ollama-compatible)
    AI_BASE_URL: str = "http://localhost:11434"
    AI_MODEL: str = "llama3.2"
    AI_REQUEST_TIMEOUT: int = 30
    AI_CLASSIFY_CONCURRENCY: int = 10
    AI_CLASSIFY_CATEGORIES: str = (
        "Food and Dining,Transport and Travel,Shopping and Retail,"
        "Utilities and Bills,Health and Medical,Entertainment and Leisure,"
        "Transfers and Payments,Salary and Income,ATM and Cash,Other"
    )
    # Override the full system prompt; if empty, it is built from AI_CLASSIFY_CATEGORIES
    AI_CLASSIFY_SYSTEM_PROMPT: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origins_list(self) -> list[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]


settings = Settings()
