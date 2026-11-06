from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "Nedra Backend"
    APP_VERSION: str = "0.1.0"
    APP_ENV: str = "local"
    DEBUG: bool = False

    # База данных: относительный путь SQLite всегда преобразуется в абсолютный
    DATABASE_URL: str = ""
    DATABASE_URL_SYNC: str = ""

    # Очередь фоновых задач (Redis)
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_QUEUE_NAME: str = "nedra_import_queue"
    USE_REDIS_QUEUE: bool = False

    # Хранилище MinIO / S3
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_NAME: str = "nedra-excel-files"
    MINIO_SECURE: bool = False
    USE_S3_STORAGE: bool = False
    LOCAL_STORAGE_DIR: str = str((BASE_DIR / "storage" / "uploads").resolve())

    # Префикс API
    API_V1_STR: str = "/api/v1"

    def __init__(self, **values):
        super().__init__(**values)
        self._resolve_database_urls()

    def _resolve_database_urls(self):
        default_sqlite_file = (BASE_DIR / "nedra.db").resolve().as_posix()

        if not self.DATABASE_URL:
            self.DATABASE_URL = f"sqlite+aiosqlite:///{default_sqlite_file}"
        elif self.DATABASE_URL.startswith("sqlite+aiosqlite:///."):
            rel = self.DATABASE_URL.replace("sqlite+aiosqlite:///.", "").lstrip("/\\")
            self.DATABASE_URL = f"sqlite+aiosqlite:///{(BASE_DIR / rel).resolve().as_posix()}"
        elif self.DATABASE_URL.startswith("sqlite:///."):
            rel = self.DATABASE_URL.replace("sqlite:///.", "").lstrip("/\\")
            self.DATABASE_URL = f"sqlite+aiosqlite:///{(BASE_DIR / rel).resolve().as_posix()}"

        if not self.DATABASE_URL_SYNC:
            if "sqlite+aiosqlite" in self.DATABASE_URL:
                self.DATABASE_URL_SYNC = self.DATABASE_URL.replace("sqlite+aiosqlite://", "sqlite://")
            elif "postgresql+asyncpg" in self.DATABASE_URL:
                self.DATABASE_URL_SYNC = self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
            else:
                self.DATABASE_URL_SYNC = self.DATABASE_URL


settings = Settings()
