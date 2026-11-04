import pytest
from app.services.excel_parser import parse_excel_workbook


def test_01_valid_xlsx(make_excel):
    """1. Корректный XLSX с одной скважиной."""
    data = {
        "Скважина 1": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [1.0, 1.0, 5.0, 45.0, 0.1, 0.1],
            [2.0, 1.99, 10.0, 45.0, 0.3, 0.3],
        ]
    }
    content = make_excel(data)
    results = parse_excel_workbook(content, "test.xlsx")

    assert len(results) == 1
    sheet = results[0]
    assert sheet.sheet_name == "Скважина 1"
    assert sheet.status == "loaded"
    assert len(sheet.points) == 3
    assert sheet.total_errors_count == 0


def test_02_valid_xlsm(make_excel):
    """2. Корректный XLSM (макросы игнорируются, данные считываются)."""
    data = {
        "Well-XLSM": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [10.0, 10.0, 1.5, 90.0, 0.5, 0.2],
        ]
    }
    content = make_excel(data, is_xlsm=True)
    results = parse_excel_workbook(content, "test.xlsm")

    assert len(results) == 1
    assert results[0].status == "loaded"
    assert len(results[0].points) == 1


def test_03_multiple_sheets(make_excel):
    """3. Несколько листов в одной книге."""
    data = {
        "Скважина 101": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [10.0, 10.0, 1.0, 90.0, 0.1, 0.2],
        ],
        "Скважина 102": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [20.0, 20.0, 2.0, 180.0, 0.3, 0.4],
        ],
        "Скважина 103": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [30.0, 30.0, 3.0, 270.0, 0.5, 0.6],
        ],
    }
    content = make_excel(data)
    results = parse_excel_workbook(content, "multi.xlsx")

    assert len(results) == 3
    assert [r.sheet_name for r in results] == ["Скважина 101", "Скважина 102", "Скважина 103"]
    assert all(r.status == "loaded" for r in results)


def test_04_missing_required_column(make_excel):
    """4. Отсутствие обязательного столбца (например, нет TVD)."""
    data = {
        "Sheet_No_TVD": [
            ["MD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [10.0, 1.0, 90.0, 0.1, 0.2],
        ]
    }
    content = make_excel(data)
    results = parse_excel_workbook(content, "missing_col.xlsx")

    assert len(results) == 1
    sheet = results[0]
    assert sheet.status == "error"
    assert len(sheet.points) == 0
    assert any(e.error_type == "missing_column" and "TVD" in e.column for e in sheet.errors)


def test_05_non_numeric_values(make_excel):
    """5. Нечисловые значения в обязательных столбцах."""
    data = {
        "Sheet_Non_Numeric": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [10.0, 10.0, 1.0, 90.0, 0.1, 0.2],
            [11.0, "CORRUPTED_TEXT", 1.5, 90.0, 0.2, 0.3],
            [12.0, 12.0, 2.0, 90.0, 0.3, 0.4],
        ]
    }
    content = make_excel(data)
    results = parse_excel_workbook(content, "bad_num.xlsx")

    assert len(results) == 1
    sheet = results[0]
    assert sheet.status == "error"
    assert len(sheet.points) == 0  # Траектория целиком не загружается!
    assert any(e.error_type == "non_numeric" and e.row == 3 for e in sheet.errors)


def test_06_ref_error(make_excel):
    """6. Ошибка формулы #REF!."""
    data = {
        "Sheet_REF": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [10.0, 10.0, 1.0, 90.0, 0.1, 0.2],
            [11.0, "#REF!", 1.0, 90.0, 0.2, 0.3],
        ]
    }
    content = make_excel(data)
    results = parse_excel_workbook(content, "ref_err.xlsx")

    sheet = results[0]
    assert sheet.status == "error"
    assert len(sheet.points) == 0
    assert any(e.error_type == "ref_error" and "#REF!" in e.message for e in sheet.errors)


def test_07_inclination_out_of_range(make_excel):
    """7. Зенитный угол вне диапазона 0–180°."""
    data = {
        "Sheet_Bad_Inc": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [10.0, 10.0, -2.0, 90.0, 0.1, 0.2],  # < 0
            [11.0, 11.0, 185.0, 90.0, 0.2, 0.3],  # > 180
        ]
    }
    content = make_excel(data)
    results = parse_excel_workbook(content, "bad_inc.xlsx")

    sheet = results[0]
    assert sheet.status == "error"
    assert len(sheet.points) == 0
    assert any("Зенитный угол" in e.message for e in sheet.errors)


def test_08_azimuth_out_of_range(make_excel):
    """8. Азимут вне диапазона 0–360°."""
    data = {
        "Sheet_Bad_Azi": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [10.0, 10.0, 10.0, -15.0, 0.1, 0.2],  # < 0
            [11.0, 11.0, 10.0, 375.0, 0.2, 0.3],  # > 360
        ]
    }
    content = make_excel(data)
    results = parse_excel_workbook(content, "bad_azi.xlsx")

    sheet = results[0]
    assert sheet.status == "error"
    assert len(sheet.points) == 0
    assert any("Азимут" in e.message for e in sheet.errors)


def test_09_error_in_one_well_does_not_block_others(make_excel):
    """9. Ошибка в одной скважине не блокирует остальные."""
    data = {
        "Скважина 1 (Хорошая)": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [10.0, 10.0, 5.0, 45.0, 0.1, 0.1],
        ],
        "Скважина 2 (Сломанная)": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [10.0, "#REF!", 5.0, 45.0, 0.1, 0.1],
        ],
        "Скважина 3 (Хорошая)": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [20.0, 20.0, 10.0, 90.0, 0.2, 0.2],
        ],
    }
    content = make_excel(data)
    results = parse_excel_workbook(content, "mixed.xlsx")

    assert len(results) == 3
    assert results[0].status == "loaded"
    assert len(results[0].points) == 1

    assert results[1].status == "error"
    assert len(results[1].points) == 0

    assert results[2].status == "loaded"
    assert len(results[2].points) == 1


def test_10_damaged_trajectory_not_returned_partially(make_excel):
    """10. Повреждённая траектория не возвращается частично."""
    data = {
        "Скважина С Ошибкой В Конце": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [1.0, 1.0, 1.0, 45.0, 0.1, 0.1],
            [2.0, 2.0, 2.0, 45.0, 0.2, 0.2],
            [3.0, 3.0, 3.0, 45.0, 0.3, 0.3],
            [4.0, 4.0, 500.0, 45.0, 0.4, 0.4],  # Inc 500° > 180°
        ]
    }
    content = make_excel(data)
    results = parse_excel_workbook(content, "partial_check.xlsx")

    sheet = results[0]
    assert sheet.status == "error"
    assert len(sheet.points) == 0  # Ни одной точки!


def test_12_extra_columns_errors_do_not_block_loading(make_excel):
    """12. Ошибки в лишних столбцах (DLS, Radians и др.) не блокируют загрузку."""
    data = {
        "Скважина С Лишними Столбцами": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW", "DLS", "Radians", "CustomColumn"],
            [10.0, 10.0, 5.0, 45.0, 0.1, 0.1, -0.45, "#REF!", "SOME_ERROR_TEXT"],
            [20.0, 20.0, 10.0, 90.0, 0.2, 0.2, -1.2, "#VALUE!", None],
        ]
    }
    content = make_excel(data)
    results = parse_excel_workbook(content, "extra_cols.xlsx")

    sheet = results[0]
    assert sheet.status == "loaded"
    assert len(sheet.points) == 2
    assert sheet.total_errors_count == 0
