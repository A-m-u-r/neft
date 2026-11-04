import asyncio
import logging
import signal
import sys
from app.core.config import settings
from app.services.task_queue import task_queue_service
from app.services.import_service import import_service
from app.database.session import init_db

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [Worker] %(message)s",
)
logger = logging.getLogger(__name__)


class ImportWorker:
    def __init__(self):
        self.running = True

    def stop(self, *args):
        logger.info("Получен сигнал остановки воркера...")
        self.running = False

    async def run(self):
        logger.info(f"Запуск воркера импорта очереди '{settings.REDIS_QUEUE_NAME}'...")
        await init_db()

        while self.running:
            try:
                task_data = task_queue_service.pop_task(timeout=2)
                if task_data and "task_id" in task_data:
                    task_id = task_data["task_id"]
                    logger.info(f"Получена задача из очереди: {task_id}")
                    await import_service.process_import_task(task_id)
                else:
                    await asyncio.sleep(0.5)
            except Exception as exc:
                logger.error(f"Ошибка в цикле воркера: {exc}", exc_info=True)
                await asyncio.sleep(2)

        logger.info("Воркер импорта успешно остановлен.")


def main():
    worker = ImportWorker()
    signal.signal(signal.SIGINT, worker.stop)
    signal.signal(signal.SIGTERM, worker.stop)
    asyncio.run(worker.run())


if __name__ == "__main__":
    main()
