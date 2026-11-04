import json
import logging
import asyncio
from typing import Optional, Callable, Awaitable
import redis

from app.core.config import settings

logger = logging.getLogger(__name__)


class TaskQueueService:
    """Сервис очереди задач на базе Redis с автоматическим fallback на фоновые задачи."""

    def __init__(self):
        self._redis_client: Optional[redis.Redis] = None

    def _get_redis(self) -> Optional[redis.Redis]:
        if not settings.USE_REDIS_QUEUE:
            return None

        if self._redis_client is None:
            try:
                client = redis.from_url(settings.REDIS_URL, decode_responses=True)
                client.ping()
                self._redis_client = client
            except Exception as exc:
                logger.warning(f"Не удалось подключиться к Redis: {exc}. Переключение на асинхронный локальный режим.")
                self._redis_client = None
        return self._redis_client

    def enqueue_import_task(self, task_id: str) -> bool:
        """Ставит задачу в очередь Redis. Возвращает True, если отправлено в Redis, иначе False."""
        r = self._get_redis()
        if r:
            try:
                payload = json.dumps({"task_id": task_id})
                r.lpush(settings.REDIS_QUEUE_NAME, payload)
                logger.info(f"Задача импорта {task_id} отправлена в очередь Redis '{settings.REDIS_QUEUE_NAME}'")
                return True
            except Exception as exc:
                logger.warning(f"Ошибка отправки задачи в Redis: {exc}. Задача будет запущена локально.")
        return False

    def pop_task(self, timeout: int = 2) -> Optional[dict]:
        """Для worker-процесса: извлекает задачу из очереди Redis (блокирующий вызов)."""
        r = self._get_redis()
        if not r:
            return None
        try:
            item = r.brpop(settings.REDIS_QUEUE_NAME, timeout=timeout)
            if item:
                # item is a tuple: (queue_name, data)
                return json.loads(item[1])
        except Exception as exc:
            logger.error(f"Ошибка извлечения задачи из Redis: {exc}")
        return None


task_queue_service = TaskQueueService()
