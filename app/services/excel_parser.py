import math
import re
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple, Set
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from app.schemas.imports import DiagnosticErrorItem, DiagnosticSheetReport

REQUIRED_COLUMNS = [
    "MD",
    "TVD",
    "Inclination",
    "Azimuth",
    "DeviationNS",
    "DeviationEW",
]

HEADER_ALIASES: Dict[str, str] = {
    # MD
    "md": "MD",
    "глубина": "MD",
    "глубинапостволу": "MD",
    "глубинапостволум": "MD",
    "глубинам": "MD",
    "mdm": "MD",
    "measureddepth": "MD",
    # TVD
    "tvd": "TVD",
    "истиннаявертикальнаяглубина": "TVD",
    "вертикальнаяглубина": "TVD",
    "tvdm": "TVD",
    "trueverticaldepth": "TVD",
    # Inclination
    "inclination": "Inclination",
    "inc": "Inclination",
    "зенитныйугол": "Inclination",
    "зенитныйуголград": "Inclination",
    "зенитныйуголградусы": "Inclination",
    "угол": "Inclination",
    "incdeg": "Inclination",
    # Azimuth
    "azimuth": "Azimuth",
    "azimuthdeg": "Azimuth",
    "azimuthdeg)": "Azimuth",
    "азимут": "Azimuth",
    "азимутград": "Azimuth",
    "азимутградусы": "Azimuth",
    "azi": "Azimuth",
    "azideg": "Azimuth",
    # DeviationNS
    "deviationns": "DeviationNS",
    "deviation_ns": "DeviationNS",
    "смещениеns": "DeviationNS",
    "смещениесеверюг": "DeviationNS",
    "смещениесю": "DeviationNS",
    "ns": "DeviationNS",
    "nsm": "DeviationNS",
    "dx": "DeviationNS",
    # DeviationEW
    "deviationew": "DeviationEW",
    "deviation_ew": "DeviationEW",
    "смещениеew": "DeviationEW",
    "смещениевостокзапад": "DeviationEW",
    "смещениевз": "DeviationEW",
    "ew": "DeviationEW",
    "ewm": "DeviationEW",
    "dy": "DeviationEW",
    # DLS
    "dls": "DLS",
    "dogleg": "DLS",
    "doglegseverity": "DLS",
    # Radians
    "radians": "Radians",
    "радиан": "Radians",
    "радианы": "Radians",
    # i (Index)
    "i": "i",
    "№": "i",
    "номер": "i",
}

EXCEL_ERROR_CODES = {
    "#REF!",
    "#VALUE!",
    "#N/A",
    "#DIV/0!",
    "#NAME?",
    "#NULL!",
    "#NUM!",
}

MAX_DIAGNOSTIC_ITEMS_PER_SHEET = 100


def normalise_header(value: Any) -> str:
    """Нормализует заголовок столбца для поиска синонимов."""
    if value is None:
        return ""
    text = str(value).lower()
    return re.sub(r"[\s\-_(),./\\]+", "", text)


def is_numeric_value(val: Any) -> Tuple[bool, Optional[float], Optional[str], Optional[str]]:
    """Проверяет значение на конечное число и возвращает (is_valid, float_val, error_type, error_msg)."""
    if val is None:
        return False, None, "missing_value", "Пустое значение в обязательной ячейке"

    if isinstance(val, str):
        val_strip = val.strip().upper()
        if val_strip in EXCEL_ERROR_CODES or val_strip.startswith("#"):
            return False, None, "ref_error", f"Ошибка формулы Excel: {val_strip}"
        try:
            num = float(val.strip().replace(",", "."))
        except (ValueError, TypeError):
            return False, None, "non_numeric", f"Нечисловое значение: '{val}'"
    elif isinstance(val, (int, float)):
        num = float(val)
    else:
        return False, None, "non_numeric", f"Нечисловой тип данных: {type(val).__name__}"

    if math.isnan(num) or math.isinf(num):
        return False, None, "nan_or_inf", "Значение не является конечным числом (NaN/Inf)"

    return True, num, None, None


class ParsedSheetData:
    """Результат парсинга одного листа Excel (одной скважины)."""

    def __init__(self, sheet_name: str):
        self.sheet_name = sheet_name
        self.status = "loaded"  # loaded, error, missing
        self.points: List[Dict[str, Any]] = []
        self.errors: List[DiagnosticErrorItem] = []
        self.total_errors_count = 0
        self.total_warnings_count = 0
        self.has_file_level_error = False
        self.message: Optional[str] = None

    def add_error(
        self,
        row: Optional[int],
        column: str,
        error_type: str,
        message: str,
        level: str = "error",
        scope: str = "well_trajectory",
    ) -> None:
        if level == "error":
            self.total_errors_count += 1
            self.status = "error"
            if scope == "file":
                self.has_file_level_error = True
        else:
            self.total_warnings_count += 1

        if len(self.errors) < MAX_DIAGNOSTIC_ITEMS_PER_SHEET:
            self.errors.append(
                DiagnosticErrorItem(
                    sheet=self.sheet_name,
                    row=row,
                    column=column,
                    error_type=error_type,
                    level=level,
                    scope=scope,
                    message=message,
                )
            )

    def to_diagnostic_report(self) -> DiagnosticSheetReport:
        msg = self.message
        if self.status == "error":
            msg = "Траектория не загружена: ошибка в исходных данных"
        elif self.status == "missing":
            msg = "На листе не найдены точки траектории"

        return DiagnosticSheetReport(
            sheet_name=self.sheet_name,
            trajectory_status=self.status,
            points_count=len(self.points) if self.status == "loaded" else 0,
            errors_count=self.total_errors_count,
            warnings_count=self.total_warnings_count,
            errors=self.errors,
            message=msg,
        )


def parse_sheet(ws) -> ParsedSheetData:
    """Парсит один лист скважины в потоковом режиме с openpyxl iter_rows(values_only=True).
    
    Требования NEF-14:
    - Отсутствие обязательного столбца: уровень 'file', файл отклоняется.
    - Ошибка в обязательных столбцах: уровень 'well_trajectory', траектория скважины не загружается целиком.
    - Лишние столбцы (Radians, DLS, формулы в заголовках) фиксируются как предупреждения (warning).
    """
    result = ParsedSheetData(ws.title)
    rows_iter = ws.iter_rows(values_only=True)

    # 1. Поиск строки заголовка
    header_map: Dict[str, int] = {}
    extra_columns: List[str] = []
    header_row_idx = 0

    for row_idx, row in enumerate(rows_iter, start=1):
        if not row:
            continue

        candidate_map: Dict[str, int] = {}
        row_extra: List[str] = []

        for col_idx, cell_value in enumerate(row):
            norm = normalise_header(cell_value)
            canonical = HEADER_ALIASES.get(norm)
            if canonical and canonical in REQUIRED_COLUMNS:
                candidate_map[canonical] = col_idx
            elif canonical == "DLS":
                candidate_map["DLS"] = col_idx
            elif cell_value is not None:
                str_val = str(cell_value).strip()
                if str_val:
                    row_extra.append(str_val)

        if len([c for c in REQUIRED_COLUMNS if c in candidate_map]) >= 3:
            header_map = candidate_map
            extra_columns = row_extra
            header_row_idx = row_idx
            break

        if row_idx >= 10:
            break

    # Фиксация предупреждений о лишних столбцах (NEF-14, Таблица 3)
    for extra_col in extra_columns[:20]:
        result.add_error(
            row=header_row_idx or 1,
            column=extra_col,
            error_type="extra_column",
            message=f"Лишний столбец '{extra_col}' не используется для построения траектории",
            level="warning",
            scope="well_trajectory",
        )
    if len(extra_columns) > 20:
        result.add_error(
            row=header_row_idx or 1,
            column=f"+{len(extra_columns) - 20} столбцов",
            error_type="extra_columns_overflow",
            message=f"На листе обнаружено ещё {len(extra_columns) - 20} лишних столбцов",
            level="warning",
            scope="well_trajectory",
        )

    # Проверка наличия всех обязательных столбцов (Уровень: Файл!)
    missing_columns = [col for col in REQUIRED_COLUMNS if col not in header_map]
    if missing_columns:
        result.add_error(
            row=header_row_idx or 1,
            column=", ".join(missing_columns),
            error_type="missing_column",
            message=f"Отсутствуют обязательные столбцы: {', '.join(missing_columns)}. Файл отклоняется.",
            level="error",
            scope="file",
        )
        return result

    # 2. Потоковое чтение точек траектории
    raw_points: List[Dict[str, Any]] = []
    has_critical_error = False

    for row_idx, row in enumerate(rows_iter, start=header_row_idx + 1):
        if not row:
            continue

        # Значения обязательных столбцов
        row_values: Dict[str, Any] = {}
        for col_name in REQUIRED_COLUMNS:
            idx = header_map[col_name]
            val = row[idx] if idx < len(row) else None
            row_values[col_name] = val

        # Пропуск пустых строк
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in row_values.values()):
            continue

        row_has_error = False
        parsed_row: Dict[str, Any] = {}

        for col_name in REQUIRED_COLUMNS:
            val = row_values[col_name]
            is_valid, num_val, err_type, err_msg = is_numeric_value(val)
            if not is_valid:
                result.add_error(
                    row=row_idx,
                    column=col_name,
                    error_type=err_type or "invalid_value",
                    message=err_msg or f"Некорректное значение в столбце {col_name}",
                    level="error",
                    scope="well_trajectory",
                )
                row_has_error = True
                has_critical_error = True
            else:
                parsed_row[col_name] = num_val

        # Опциональный столбец DLS (если есть, считываем как float или None)
        if "DLS" in header_map:
            dls_idx = header_map["DLS"]
            dls_val = row[dls_idx] if dls_idx < len(row) else None
            if dls_val is not None:
                is_valid_dls, num_dls, _, _ = is_numeric_value(dls_val)
                parsed_row["DLS"] = num_dls if is_valid_dls else None
            else:
                parsed_row["DLS"] = None
        else:
            parsed_row["DLS"] = None

        if row_has_error:
            continue

        # Проверка диапазонов физических углов
        inclination = parsed_row["Inclination"]
        azimuth = parsed_row["Azimuth"]

        if not (0.0 <= inclination <= 180.0):
            result.add_error(
                row=row_idx,
                column="Inclination",
                error_type="out_of_range",
                message=f"Зенитный угол ({inclination}°) вне допустимого диапазона 0–180°",
                level="error",
                scope="well_trajectory",
            )
            has_critical_error = True

        if not (0.0 <= azimuth <= 360.0):
            result.add_error(
                row=row_idx,
                column="Azimuth",
                error_type="out_of_range",
                message=f"Азимут ({azimuth}°) вне допустимого диапазона 0–360°",
                level="error",
                scope="well_trajectory",
            )
            has_critical_error = True

        if not has_critical_error:
            raw_points.append(parsed_row)

    # 3. Финальная валидация листа
    if has_critical_error or result.total_errors_count > 0:
        result.status = "error"
        result.points = []  # Не допускается частичная загрузка!
        result.message = "Траектория не загружена: ошибка в исходных данных"
    elif len(raw_points) == 0:
        result.status = "missing"
        result.points = []
        result.message = "На листе не найдены точки траектории"
    else:
        result.status = "loaded"
        result.points = raw_points
        result.message = None

    return result


def parse_excel_workbook(file_bytes: bytes, filename: str) -> List[ParsedSheetData]:
    """Открывает книгу openpyxl в оптимальном режиме для чтения больших данных."""
    try:
        wb = load_workbook(
            filename=BytesIO(file_bytes),
            read_only=True,
            data_only=True,
            keep_vba=False,
        )
    except (InvalidFileException, OSError, ValueError) as exc:
        raise ValueError(f"Не удалось открыть Excel-файл {filename}: {exc}") from exc

    sheet_results: List[ParsedSheetData] = []
    try:
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            sheet_data = parse_sheet(ws)
            sheet_results.append(sheet_data)
    finally:
        wb.close()

    return sheet_results
