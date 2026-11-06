from typing import List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field


class DiagnosticErrorItem(BaseModel):
    sheet: str = Field(..., description="Название листа")
    row: Optional[int] = Field(None, description="Номер строки с ошибкой (None для заголовков/файла)")
    column: str = Field(..., description="Название столбца")
    error_type: str = Field(..., description="Тип ошибки: non_numeric, out_of_range, ref_error, missing_column, extra_column и др.")
    level: str = Field(default="error", description="Уровень серьезности: error, warning")
    scope: str = Field(default="well_trajectory", description="Область ошибки: file (файл), version (версия), well_trajectory (траектория скважины)")
    message: str = Field(..., description="Описание ошибки")


class DiagnosticSheetReport(BaseModel):
    sheet_name: str
    trajectory_status: str = Field(..., description="loaded, error, missing")
    points_count: int = 0
    errors_count: int = 0
    warnings_count: int = 0
    errors: List[DiagnosticErrorItem] = []
    message: Optional[str] = None


class DiagnosticReportResponse(BaseModel):
    task_id: str
    status: str
    file_status: str = Field(default="accepted", description="accepted (принят) или rejected (отклонен)")
    total_sheets: int
    successful_sheets: int
    failed_sheets: int
    sheets: List[DiagnosticSheetReport]
    notes: List[str] = []


class ImportTaskCreateResponse(BaseModel):
    task_id: str
    status: str
    message: str
    filename: str
    well_pad_id: Optional[str] = None
    well_pad_name: Optional[str] = None


class ImportTaskStatusResponse(BaseModel):
    task_id: str
    status: str
    filename: str
    well_pad_id: Optional[str] = None
    well_pad_name: Optional[str] = None
    total_sheets: int = 0
    successful_sheets: int = 0
    failed_sheets: int = 0
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
