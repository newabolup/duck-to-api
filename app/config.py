from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_prefix="DUCK_API_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8000
    api_key: str | None = None
    default_adapter: str = "duck-ai"
    data_dir: Path = PROJECT_ROOT / "data"
    browser_headless: bool = True
    browser_channel: str | None = None
    chromium_no_sandbox: bool = False
    max_concurrent_jobs: int = 1
    job_timeout_seconds: int = 180
    sync_wait_timeout_seconds: int = 300
    max_upload_bytes: int = 20 * 1024 * 1024
    enable_browser_on_startup: bool = True
    base_url: str | None = None
    cors_origins: list[str] = ["*"]

    @property
    def resolved_data_dir(self) -> Path:
        if self.data_dir.is_absolute():
            return self.data_dir
        return (PROJECT_ROOT / self.data_dir).resolve()

    @property
    def profile_dir(self) -> Path:
        return self.resolved_data_dir / "browser_profile"

    @property
    def uploads_dir(self) -> Path:
        return self.resolved_data_dir / "uploads"

    @property
    def outputs_dir(self) -> Path:
        return self.resolved_data_dir / "outputs"

    @property
    def db_path(self) -> Path:
        return self.resolved_data_dir / "jobs.db"


def get_settings() -> Settings:
    return Settings()
