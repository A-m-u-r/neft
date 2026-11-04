from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class DiagnosticErrorItem(BaseModel):
    sheet: str = Field(..., description="Название листа")
    row: int = Field(..., description="Номер строки с ошибкой")
    column: str = Field(..., description="Название столбца")
    error_type: str = Field(..., description="Тип ошибки: non_numeric, out_of_range, ref_error, missing_column и др.")
    level: str = Field(default="error", description="Уровень ошибки: error, warning")
    message: str = Field(..., description="Описание ошибки")


class DiagnosticSheetReport(BaseModel):
    sheet_name: str
    trajectory_status: str = Field(..., description="loaded, error, missing")
    points_count: int = 0
    errors_count: int = 0
    errors: List[DiagnosticErrorItem] = []
    message: Optional[str] = None


class DiagnosticReportResponse(BaseModel):
    task_id: str
    status: str
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
