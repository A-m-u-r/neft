from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./nedra.db"
    DATABASE_URL_SYNC: str = "sqlite:///./nedra.db"

    # Redis Queue
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_QUEUE_NAME: str = "nedra_import_queue"
    USE_REDIS_QUEUE: bool = False  # Set to True when Redis is available

    # MinIO / S3 Storage
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_NAME: str = "nedra-excel-files"
    MINIO_SECURE: bool = False
    USE_S3_STORAGE: bool = False  # Falls back to local directory if False or unavailable
    LOCAL_STORAGE_DIR: str = "./storage/uploads"

    # API Prefix
    API_V1_STR: str = "/api/v1"


settings = Settings()
