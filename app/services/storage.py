import os
import uuid
import logging
from pathlib import Path
from typing import Optional, Tuple
import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageService:
    """Сервис для сохранения и получения исходных Excel-файлов в MinIO (S3) или локальном хранилище."""

    def __init__(self):
        self._s3_client = None
        self._bucket_initialized = False

    def _get_s3_client(self):
        if not settings.USE_S3_STORAGE:
            return None

        if self._s3_client is None:
            try:
                protocol = "https" if settings.MINIO_SECURE else "http"
                endpoint_url = f"{protocol}://{settings.MINIO_ENDPOINT}"
                self._s3_client = boto3.client(
                    "s3",
                    endpoint_url=endpoint_url,
                    aws_access_key_id=settings.MINIO_ACCESS_KEY,
                    aws_secret_access_key=settings.MINIO_SECRET_KEY,
                    region_name="us-east-1",
                )
                self._ensure_bucket()
            except Exception as exc:
                logger.warning(f"Не удалось инициализировать клиент MinIO/S3: {exc}. Переключение на локальное хранилище.")
                self._s3_client = None
        return self._s3_client

    def _ensure_bucket(self):
        if self._bucket_initialized or not self._s3_client:
            return
        try:
            self._s3_client.head_bucket(Bucket=settings.MINIO_BUCKET_NAME)
        except ClientError:
            try:
                self._s3_client.create_bucket(Bucket=settings.MINIO_BUCKET_NAME)
                self._bucket_initialized = True
            except Exception as e:
                logger.warning(f"Ошибка создания bucket {settings.MINIO_BUCKET_NAME}: {e}")

    def save_file(self, content: bytes, original_filename: str) -> str:
        """Сохраняет файл в MinIO или на диск и возвращает storage_path."""
        ext = os.path.splitext(original_filename)[1] or ".xlsx"
        unique_name = f"{uuid.uuid4()}_{Path(original_filename).name}"
        s3 = self._get_s3_client()

        if s3:
            try:
                s3.put_object(
                    Bucket=settings.MINIO_BUCKET_NAME,
                    Key=unique_name,
                    Body=content,
                )
                return f"s3://{settings.MINIO_BUCKET_NAME}/{unique_name}"
            except Exception as exc:
                logger.warning(f"Ошибка сохранения в MinIO: {exc}. Сохранение локально.")

        # Локальное хранилище
        os.makedirs(settings.LOCAL_STORAGE_DIR, exist_ok=True)
        local_path = os.path.join(settings.LOCAL_STORAGE_DIR, unique_name)
        with open(local_path, "wb") as f:
            f.write(content)
        return local_path

    def get_file(self, storage_path: str) -> bytes:
        """Считывает байты файла из MinIO или диска."""
        if storage_path.startswith("s3://"):
            s3 = self._get_s3_client()
            if s3:
                parts = storage_path.replace("s3://", "").split("/", 1)
                bucket, key = parts[0], parts[1]
                response = s3.get_object(Bucket=bucket, Key=key)
                return response["Body"].read()

        # Локальное чтение
        with open(storage_path, "rb") as f:
            return f.read()


storage_service = StorageService()
