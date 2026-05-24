from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENV: str = "dev"
    CORS_ORIGINS: str = "http://localhost"  # must be explicitly set in production
    MAX_PDF_BYTES: int = 10 * 1024 * 1024  # 10 MB
    LOG_DIR: str = "/app/logs/api"
    LOG_RETENTION_DAYS: int = 30

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origins_list(self) -> list[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]


settings = Settings()
