import os
import logging
from typing import Optional, List
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession

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
        db: Optional[AsyncSession] = None,
    ) -> str:
        """Сохраняет исходный файл и регистрирует задачу импорта в БД."""
        # Сохранение файла в MinIO / локальное хранилище
        storage_path = storage_service.save_file(file_bytes, filename)

        # Если имя куста не передано, берем имя файла без расширения
        if not well_pad_name or not well_pad_name.strip():
            well_pad_name = Path(filename).stem

        # Создаем запись задачи в БД
        if db:
            task_repo = ImportTaskRepository(db)
            task = await task_repo.create(
                filename=filename,
                storage_path=storage_path,
                well_pad_name=well_pad_name,
            )
            await db.commit()
            task_id = task.id
        else:
            async with AsyncSessionLocal() as session:
                task_repo = ImportTaskRepository(session)
                task = await task_repo.create(
                    filename=filename,
                    storage_path=storage_path,
                    well_pad_name=well_pad_name,
                )
                await session.commit()
                task_id = task.id

        # Ставим в очередь Redis или запускаем асинхронно
        enqueued = task_queue_service.enqueue_import_task(task_id)
        if not enqueued:
            # Запуск в фоновой async-задаче
            import asyncio
            asyncio.create_task(self.process_import_task(task_id))

        return task_id

    async def process_import_task(self, task_id: str) -> None:
        """Основной пайплайн обработки файла: чтение, валидация, сохранение скважин и точек."""
        async with AsyncSessionLocal() as db:
            task_repo = ImportTaskRepository(db)
            well_pad_repo = WellPadRepository(db)
            well_repo = WellRepository(db)
            trajectory_repo = TrajectoryRepository(db)

            task = await task_repo.get_by_id(task_id)
            if not task:
                logger.error(f"Задача импорта {task_id} не найдена в БД")
                return

            try:
                await task_repo.update_status(task_id, status="processing")
                await db.commit()

                # Считывание содержимого файла
                file_bytes = storage_service.get_file(task.storage_path)

                # Потоковый парсинг книги Excel
                parsed_sheets: List[ParsedSheetData] = parse_excel_workbook(file_bytes, task.filename)

                # Получение или создание кустовой площадки
                pad_name = task.well_pad_name or Path(task.filename).stem
                well_pad = await well_pad_repo.get_or_create(pad_name)

                successful_count = 0
                failed_count = 0

                # Обработка каждого листа (каждой скважины)
                for sheet in parsed_sheets:
                    # 1. Скважина всегда сохраняется и остаётся доступной в системе
                    well, created = await well_repo.get_or_create(
                        well_pad_id=well_pad.id,
                        name=sheet.sheet_name,
                    )

                    if sheet.status == "loaded":
                        # Сохраняем точки траектории
                        saved_points = await trajectory_repo.bulk_save_points(well.id, sheet.points)
                        await well_repo.update_trajectory_status(
                            well_id=well.id,
                            status="loaded",
                            points_count=saved_points,
                            error_message=None,
                        )
                        successful_count += 1

                    elif sheet.status == "error":
                        # БИЗНЕС-ПРАВИЛО NEF-27:
                        # - скважина сохранена;
                        # - карточка скважины доступна;
                        # - устьевые координаты сохранены;
                        # - точки траектории целиком НЕ загружаются (удаляются, если были);
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

                    else:  # missing
                        await trajectory_repo.delete_by_well_id(well.id)
                        await well_repo.update_trajectory_status(
                            well_id=well.id,
                            status="not_loaded",
                            points_count=0,
                            error_message=sheet.message or "На листе не найдены точки траектории",
                        )

                # Формирование диагностического отчёта
                task_status = "completed_with_errors" if failed_count > 0 else "completed"
                diagnostic_sheets = [s.to_diagnostic_report() for s in parsed_sheets]

                report = DiagnosticReportResponse(
                    task_id=task_id,
                    status=task_status,
                    total_sheets=len(parsed_sheets),
                    successful_sheets=successful_count,
                    failed_sheets=failed_count,
                    sheets=diagnostic_sheets,
                    notes=[
                        "DLS и Radians не используются для построения траектории.",
                        "Траектория скважины строится по уже рассчитанным TVD, DeviationNS, DeviationEW.",
                        "Координаты устья: X=0, Y=0, Z=0 по умолчанию (могут быть скорректированы через API скважины).",
                        "X = wellhead_x + DeviationEW; Y = wellhead_y + DeviationNS; Z = wellhead_z - TVD.",
                    ],
                )

                # Фиксация статуса задачи в БД
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
                logger.info(f"Задача импорта {task_id} завершена со статусом {task_status}")

            except Exception as exc:
                logger.exception(f"Критическая ошибка обработки импорта {task_id}: {exc}")
                await task_repo.update_status(
                    task_id=task_id,
                    status="failed",
                    error_message=str(exc),
                )
                await db.commit()


import_service = ImportService()
