from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_data_dir: Path = Path("./data")
    database_url: str = "sqlite:///./data/app.db"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_response_format: str = "json_object"
    llm_auth_mode: str = "bearer"
    llm_api_key_header: str = "Authorization"
    llm_max_output_tokens: int = 64000
    llm_temperature: float = 0.2
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 1
    task_queue_backend: str = "local"
    redis_url: str = "redis://127.0.0.1:6379/0"
    max_upload_bytes: int = 100 * 1024 * 1024
    host: str = "127.0.0.1"
    port: int = 8000

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
settings.app_data_dir.mkdir(parents=True, exist_ok=True)

