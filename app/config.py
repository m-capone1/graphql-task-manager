from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://lush:lush_secret@localhost:5432/lush_tasks"
    debug: bool = False
    log_level: str = "INFO"


settings = Settings()
