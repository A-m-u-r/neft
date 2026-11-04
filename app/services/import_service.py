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

        # Шаг 1-2: создание записи задания и немедленная фиксация транзакции
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
            "Запись задания импорта %s создана в БД для файла '%s' (куст: '%s')",
            task_id,
            filename,
            well_pad_name,
        )

        # Шаг 3: сохранение исходного файла в объектное/локальное хранилище
        try:
            storage_path = storage_service.save_file(file_bytes, filename)
            async with AsyncSessionLocal() as session:
                task_repo = ImportTaskRepository(session)
                task = await task_repo.get_by_id(task_id)
                if task:
                    task.storage_path = storage_path
                    await session.commit()
            logger.info("Файл задания %s сохранён по пути '%s'", task_id, storage_path)
        except Exception as exc:
            logger.error("Ошибка сохранения файла задания %s в хранилище: %s", task_id, exc, exc_info=True)
            async with AsyncSessionLocal() as session:
                task_repo = ImportTaskRepository(session)
                await task_repo.update_status(
                    task_id=task_id,
                    status="failed",
                    error_message=f"Ошибка сохранения файла в хранилище: {exc}",
                )
                await session.commit()
            return task_id

        # Шаг 4: отправка задания в очередь обработки
        if settings.USE_REDIS_QUEUE:
            try:
                enqueued = task_queue_service.enqueue_import_task(task_id)
                if not enqueued:
                    raise RuntimeError(f"Очередь Redis недоступна или отклонила задачу {task_id}")
                logger.info("Задание %s отправлено в очередь Redis '%s'", task_id, settings.REDIS_QUEUE_NAME)
            except Exception as exc:
                logger.error("Ошибка отправки задания %s в очередь Redis: %s", task_id, exc, exc_info=True)
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
            if background_tasks:
                background_tasks.add_task(self.process_import_task, task_id)
            else:
                import asyncio
                asyncio.create_task(self.process_import_task(task_id))

        return task_id

    async def process_import_task(self, task_id: str) -> None:
        """Основной пайплайн обработки файла воркером (шаги 5-6)."""
        async with AsyncSessionLocal() as db:
            task_repo = ImportTaskRepository(db)
            well_pad_repo = WellPadRepository(db)
            well_repo = WellRepository(db)
            trajectory_repo = TrajectoryRepository(db)

            task = await task_repo.get_by_id(task_id)
            if not task:
                logger.error("Задание %s не найдено в БД при запуске обработки", task_id)
                return

            try:
                await task_repo.update_status(task_id, status="processing")
                await db.commit()

                if not task.storage_path:
                    raise ValueError("Файл не был сохранён в хранилище (отсутствует storage_path)")

                file_bytes = storage_service.get_file(task.storage_path)
                parsed_sheets: List[ParsedSheetData] = parse_excel_workbook(file_bytes, task.filename)

                # Валидация уровня 'file': отсутствие обязательных столбцов отклоняет весь файл (NEF-14)
                file_level_errors = [
                    err for s in parsed_sheets for err in s.errors if getattr(err, "scope", "") == "file"
                ]
                if file_level_errors:
                    err_msg = file_level_errors[0].message
                    logger.warning("Файл задачи %s отклонён: %s", task_id, err_msg)
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

                pad_name = task.well_pad_name or Path(task.filename).stem
                well_pad = await well_pad_repo.get_or_create(pad_name)

                successful_count = 0
                failed_count = 0

                for sheet in parsed_sheets:
                    # Скважина на кусте сохраняется всегда, даже при повреждённой траектории
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
                        logger.info("Скважина '%s' успешно импортирована (%d точек)", sheet.sheet_name, saved_points)

                    elif sheet.status == "error":
                        # Бизнес-правило NEF-27 и NEF-14:
                        # - скважина сохраняется на кустовой площадке;
                        # - карточка скважины остаётся доступной;
                        # - устьевые координаты сохраняются;
                        # - траектория целиком не загружается (0 сохранённых точек);
                        # - статус: error;
                        # - сообщение: "Траектория не загружена: ошибка в исходных данных".
                        await trajectory_repo.delete_by_well_id(well.id)
                        await well_repo.update_trajectory_status(
                            well_id=well.id,
                            status="error",
                            points_count=0,
                            error_message="Траектория не загружена: ошибка в исходных данных",
                        )
                        failed_count += 1
                        logger.warning(
                            "Скважина '%s' сохранена без траектории (ошибок в данных: %d)",
                            sheet.sheet_name,
                            sheet.total_errors_count,
                        )

                    else:  # missing
                        await trajectory_repo.delete_by_well_id(well.id)
                        await well_repo.update_trajectory_status(
                            well_id=well.id,
                            status="not_loaded",
                            points_count=0,
                            error_message=sheet.message or "На листе не найдены точки траектории",
                        )

                # Шаг 6: фиксация общего статуса и сохранение диагностического отчёта
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
                    "Задание %s завершено со статусом '%s' (успешно: %d, с ошибками: %d)",
                    task_id,
                    task_status,
                    successful_count,
                    failed_count,
                )

            except Exception as exc:
                logger.exception("Критическая ошибка обработки импорта %s: %s", task_id, exc)
                await task_repo.update_status(
                    task_id=task_id,
                    status="failed",
                    error_message=f"Ошибка обработки: {exc}",
                )
                await db.commit()


import_service = ImportService()
