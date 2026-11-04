"""Модуль обратной совместимости для валидации и парсинга книги Excel."""
from io import BytesIO
from typing import Any, Dict, List
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from app.services.excel_parser import parse_excel_workbook, ParsedSheetData


def parse_workbook(
    content: bytes,
    filename: str,
    well_mapping: Dict[str, str],
) -> Dict[str, Any]:
    """Проверяет книгу Excel и возвращает отчёт валидации."""
    try:
        parsed_sheets = parse_excel_workbook(content, filename)
    except Exception as exc:
        raise ValueError(f"Не удалось прочитать Excel-файл: {type(exc).__name__}") from exc

    results: List[Dict[str, Any]] = []
    sheet_names = [s.sheet_name for s in parsed_sheets]
    unmapped_sheets = [s for s in sheet_names if s not in well_mapping]

    for s in parsed_sheets:
        if s.sheet_name in well_mapping:
            diag = s.to_diagnostic_report()
            results.append({
                "well_id": well_mapping[s.sheet_name],
                "sheet_name": s.sheet_name,
                "trajectory_status": s.status,
                "points_count": len(s.points),
                "errors_count": s.total_errors_count,
                "errors": [e.model_dump() for e in s.errors],
                "message": diag.message,
            })

    unknown_mapping = [name for name in well_mapping if name not in sheet_names]
    has_errors = any(item["trajectory_status"] == "error" for item in results)

    return {
        "filename": filename,
        "status": "processed_with_errors" if has_errors or unmapped_sheets else "processed",
        "sheets": results,
        "unmapped_sheets": unmapped_sheets,
        "mapping_for_unknown_sheets": unknown_mapping,
        "notes": [
            "DLS и Radians не используются при проверке траектории.",
            "В ответе импорта возвращается сводка, а не массив координат.",
        ],
    }
