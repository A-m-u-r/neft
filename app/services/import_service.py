import os
import logging
from typing import Optional, List, Any
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database.session import AsyncSessionLocal
from app.services.storage import storage_service
from app.services.excel_parser import parse_excel_workbook, ParsedSheetData
from app.services.task_queue import task_queue_service
from app.repositories.well_pad import WellPadRepository
from app.repositories.well import WellRepository
from app.repositories.trajectory import TrajectoryRepository
from app.repositories.import_task import ImportTaskRepository
from app.schemas.imports import DiagnosticReportResponse

logger = logging.getLogger(__name__)


class ImportService:
    """Сервис координации импорта Excel-файлов с траекториями скважин."""

    async def create_import_task(
        self,
        file_bytes: bytes,
        filename: str,
        well_pad_name: Optional[str] = None,
        background_tasks: Optional[Any] = None,
        db: Optional[AsyncSession] = None,
    ) -> str:
        """Регистрирует задачу импорта строго по шагам 1-4.
        
        Порядок операций:
        1. Создание записи задания ImportTask в БД.
        2. Фиксация (commit) в БД (задание сразу доступно по task_id).
        3. Сохранение исходного файла в хранилище (MinIO / локально).
        4. Отправка задания в Redis (или локальный воркер).
        """
        if not well_pad_name or not well_pad_name.strip():
            well_pad_name = Path(filename).stem

        # --- ШАГ 1 & 2: Создание записи задания и немедленный Commit в БД ---
        async with AsyncSessionLocal() as session:
            task_repo = ImportTaskRepository(session)
            task = await task_repo.create(
                filename=filename,
                storage_path=None,
                well_pad_name=well_pad_name,
            )
            await session.commit()
            await session.refresh(task)
            task_id = task.id

        logger.info(
            f"[DIAG] [PID {os.getpid()}] [DB {settings.DATABASE_URL}] "
            f"INSERT ImportTask: id={task_id}, status={task.status}, filename={filename}"
        )
        logger.info(
            f"[Task {task_id}] Шаг 1-2: Запись ImportTask успешно создана в БД и закоммичена "
            f"для файла '{filename}' (куст: '{well_pad_name}')."
        )

        # --- ШАГ 3: Сохранение исходного файла в хранилище ---
        logger.info(f"[Task {task_id}] Шаг 3: Сохранение исходного файла в хранилище...")
        try:
            storage_path = storage_service.save_file(file_bytes, filename)
            async with AsyncSessionLocal() as session:
                task_repo = ImportTaskRepository(session)
                task = await task_repo.get_by_id(task_id)
                if task:
                    task.storage_path = storage_path
                    await session.commit()
            logger.info(f"[Task {task_id}] Исходный файл сохранён по пути '{storage_path}'.")
        except Exception as exc:
            logger.error(f"[Task {task_id}] Ошибка при сохранении файла в хранилище: {exc}", exc_info=True)
            async with AsyncSessionLocal() as session:
                task_repo = ImportTaskRepository(session)
                await task_repo.update_status(
                    task_id=task_id,
                    status="failed",
                    error_message=f"Ошибка сохранения файла в хранилище: {exc}",
                )
                await session.commit()
            return task_id

        # --- ШАГ 4: Отправка задания в очередь задач ---
        logger.info(f"[Task {task_id}] Шаг 4: Отправка задания на обработку...")
        if settings.USE_REDIS_QUEUE:
            try:
                enqueued = task_queue_service.enqueue_import_task(task_id)
                if not enqueued:
                    raise RuntimeError(f"Очередь Redis недоступна или отклонила задачу {task_id}")
                logger.info(f"[Task {task_id}] Задание успешно отправлено в очередь Redis '{settings.REDIS_QUEUE_NAME}'.")
            except Exception as exc:
                logger.error(f"[Task {task_id}] Ошибка отправки задания в очередь Redis: {exc}", exc_info=True)
                async with AsyncSessionLocal() as session:
                    task_repo = ImportTaskRepository(session)
                    await task_repo.update_status(
                        task_id=task_id,
                        status="failed",
                        error_message=f"Ошибка отправки задания в очередь Redis: {exc}",
                    )
                    await session.commit()
                return task_id
        else:
            logger.info(f"[Task {task_id}] Redis отключен (USE_REDIS_QUEUE=False). Запуск локального асинхронного воркера...")
            if background_tasks:
                background_tasks.add_task(self.process_import_task, task_id)
            else:
                import asyncio
                asyncio.create_task(self.process_import_task(task_id))

        return task_id

    async def process_import_task(self, task_id: str) -> None:
        """Основной пайплайн обработки файла воркером (Шаги 5-6)."""
        logger.info(f"[Task {task_id}] Шаг 5: Воркер начал обработку задания...")

        async with AsyncSessionLocal() as db:
            task_repo = ImportTaskRepository(db)
            well_pad_repo = WellPadRepository(db)
            well_repo = WellRepository(db)
            trajectory_repo = TrajectoryRepository(db)

            task = await task_repo.get_by_id(task_id)
            if not task:
                logger.error(f"[Task {task_id}] Критическая ошибка: задание не найдено в БД!")
                return

            try:
                await task_repo.update_status(task_id, status="processing")
                await db.commit()
                logger.info(f"[Task {task_id}] Статус задания обновлен на 'processing'.")

                if not task.storage_path:
                    raise ValueError("Файл не был сохранен в хранилище (отсутствует storage_path).")

                # Чтение содержимого файла
                logger.info(f"[Task {task_id}] Считывание файла из хранилища: {task.storage_path}...")
                file_bytes = storage_service.get_file(task.storage_path)

                # Потоковый парсинг книги Excel
                logger.info(f"[Task {task_id}] Парсинг листов Excel книги...")
                parsed_sheets: List[ParsedSheetData] = parse_excel_workbook(file_bytes, task.filename)
                logger.info(f"[Task {task_id}] Обнаружено листов: {len(parsed_sheets)}.")

                # Проверка наличия ошибки уровня 'file' (NEF-14, Таблица 3: отсутствие обязательного столбца)
                file_level_errors = [
                    err for s in parsed_sheets for err in s.errors if getattr(err, "scope", "") == "file"
                ]
                if file_level_errors:
                    err_msg = file_level_errors[0].message
                    logger.warning(f"[Task {task_id}] Файл отклонен: {err_msg}")
                    diagnostic_sheets = [s.to_diagnostic_report() for s in parsed_sheets]
                    report = DiagnosticReportResponse(
                        task_id=task_id,
                        status="failed",
                        file_status="rejected",
                        total_sheets=len(parsed_sheets),
                        successful_sheets=0,
                        failed_sheets=len(parsed_sheets),
                        sheets=diagnostic_sheets,
                        notes=[
                            "Файл отклонен согласно NEF-14: отсутствуют обязательные столбцы.",
                            "Профили кустовой площадки не загружены.",
                        ],
                    )
                    await task_repo.update_status(
                        task_id=task_id,
                        status="failed",
                        total_sheets=len(parsed_sheets),
                        successful_sheets=0,
                        failed_sheets=len(parsed_sheets),
                        diagnostic_report=report.model_dump(),
                        error_message=err_msg,
                    )
                    await db.commit()
                    return

                # Получение или создание кустовой площадки
                pad_name = task.well_pad_name or Path(task.filename).stem
                well_pad = await well_pad_repo.get_or_create(pad_name)

                successful_count = 0
                failed_count = 0

                # Обработка скважин по листам
                for sheet in parsed_sheets:
                    # Скважина всегда сохраняется и остаётся доступной в системе
                    well, _ = await well_repo.get_or_create(
                        well_pad_id=well_pad.id,
                        name=sheet.sheet_name,
                    )

                    if sheet.status == "loaded":
                        saved_points = await trajectory_repo.bulk_save_points(well.id, sheet.points)
                        await well_repo.update_trajectory_status(
                            well_id=well.id,
                            status="loaded",
                            points_count=saved_points,
                            error_message=None,
                        )
                        successful_count += 1
                        logger.info(f"[Task {task_id}] Скважина '{sheet.sheet_name}' успешно загружена ({saved_points} точек).")

                    elif sheet.status == "error":
                        # Правило NEF-27 и NEF-14:
                        # - Скважина сохраняется на кусте;
                        # - Карточка скважины остаётся доступной;
                        # - Устьевые координаты сохраняются;
                        # - Траектория целиком не загружается (0 точек);
                        # - Статус: error;
                        # - Сообщение: "Траектория не загружена: ошибка в исходных данных".
                        await trajectory_repo.delete_by_well_id(well.id)
                        await well_repo.update_trajectory_status(
                            well_id=well.id,
                            status="error",
                            points_count=0,
                            error_message="Траектория не загружена: ошибка в исходных данных",
                        )
                        failed_count += 1
                        logger.warning(
                            f"[Task {task_id}] Скважина '{sheet.sheet_name}' сохранена без траектории "
                            f"(ошибок: {sheet.total_errors_count})."
                        )

                    else:  # missing
                        await trajectory_repo.delete_by_well_id(well.id)
                        await well_repo.update_trajectory_status(
                            well_id=well.id,
                            status="not_loaded",
                            points_count=0,
                            error_message=sheet.message or "На листе не найдены точки траектории",
                        )

                # --- ШАГ 6: Обновление статуса и диагностического отчёта ---
                task_status = "completed_with_errors" if failed_count > 0 else "completed"
                diagnostic_sheets = [s.to_diagnostic_report() for s in parsed_sheets]

                report = DiagnosticReportResponse(
                    task_id=task_id,
                    status=task_status,
                    file_status="accepted",
                    total_sheets=len(parsed_sheets),
                    successful_sheets=successful_count,
                    failed_sheets=failed_count,
                    sheets=diagnostic_sheets,
                    notes=[
                        "DLS и Radians не используются для построения траектории.",
                        "Лишние столбцы зафиксированы в отчёте как предупреждения (warning).",
                        "Траектория скважины строится по уже рассчитанным TVD, DeviationNS, DeviationEW.",
                        "Координаты устья: X=0, Y=0, Z=0 по умолчанию (могут быть скорректированы через API скважины).",
                        "X = wellhead_x + DeviationEW; Y = wellhead_y + DeviationNS; Z = wellhead_z - TVD.",
                    ],
                )

                await task_repo.update_status(
                    task_id=task_id,
                    status=task_status,
                    total_sheets=len(parsed_sheets),
                    successful_sheets=successful_count,
                    failed_sheets=failed_count,
                    diagnostic_report=report.model_dump(),
                    well_pad_id=well_pad.id,
                )
                await db.commit()
                logger.info(
                    f"[Task {task_id}] Шаг 6: Задание успешно завершено со статусом '{task_status}'. "
                    f"Успешных листов: {successful_count}, с ошибками: {failed_count}."
                )

            except Exception as exc:
                logger.exception(f"[Task {task_id}] Критическая ошибка обработки импорта: {exc}")
                await task_repo.update_status(
                    task_id=task_id,
                    status="failed",
                    error_message=f"Ошибка обработки: {exc}",
                )
                await db.commit()


import_service = ImportService()
