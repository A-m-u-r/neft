import json
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.services.import_service import import_service
from app.repositories.import_task import ImportTaskRepository
from app.schemas.imports import (
    ImportTaskCreateResponse,
    ImportTaskStatusResponse,
    DiagnosticReportResponse,
)

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("/excel", response_model=ImportTaskCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_excel_file(
    file: UploadFile = File(..., description="Файл профилей скважин (.xlsx или .xlsm)"),
    well_pad_name: Optional[str] = Form(None, description="Опциональное наименование кустовой площадки"),
    db: AsyncSession = Depends(get_db),
):
    """Загрузка Excel-файла с профилями скважин кустовой площадки.
    
    - Каждый лист соответствует одной скважине.
    - Обработка выполняется в фоновом режиме (Redis worker / асинхронная задача).
    - Возвращает ID задачи для отслеживания статуса.
    """
    filename = (file.filename or "").strip()
    filename_lower = filename.lower()
    if not (filename_lower.endswith(".xlsx") or filename_lower.endswith(".xlsm")):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Поддерживаются только форматы .xlsx и .xlsm",
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Загруженный файл пуст",
        )

    task_id = await import_service.create_import_task(
        file_bytes=content,
        filename=filename,
        well_pad_name=well_pad_name,
        db=db,
    )

    return ImportTaskCreateResponse(
        task_id=task_id,
        status="pending",
        message="Файл принят на обработку",
        filename=filename,
        well_pad_name=well_pad_name,
    )


@router.post("/trajectories", response_model=ImportTaskCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_trajectories_legacy(
    file: UploadFile = File(...),
    well_mapping: Optional[str] = Form(None),
    well_pad_name: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Совместимый маршрут для загрузки Excel."""
    return await upload_excel_file(file=file, well_pad_name=well_pad_name, db=db)


@router.get("/{task_id}", response_model=ImportTaskStatusResponse)
async def get_import_task_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Получение текущего статуса обработки файла импорта."""
    task_repo = ImportTaskRepository(db)
    task = await task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    return ImportTaskStatusResponse(
        task_id=task.id,
        status=task.status,
        filename=task.filename,
        well_pad_id=task.well_pad_id,
        well_pad_name=task.well_pad_name,
        total_sheets=task.total_sheets,
        successful_sheets=task.successful_sheets,
        failed_sheets=task.failed_sheets,
        error_message=task.error_message,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.get("/{task_id}/report", response_model=DiagnosticReportResponse)
async def get_diagnostic_report(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Получение подробного диагностического отчёта со списком ошибок по листам и строкам."""
    task_repo = ImportTaskRepository(db)
    task = await task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    if not task.diagnostic_report:
        if task.status in ("pending", "processing"):
            return DiagnosticReportResponse(
                task_id=task.id,
                status=task.status,
                total_sheets=0,
                successful_sheets=0,
                failed_sheets=0,
                sheets=[],
                notes=["Обработка файла ещё не завершена."],
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Диагностический отчёт для данной задачи отсутствует",
        )

    return DiagnosticReportResponse(**task.diagnostic_report)
