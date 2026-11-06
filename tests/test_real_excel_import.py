import os
import time
import tracemalloc
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.database.session import AsyncSessionLocal
from app.repositories.well_pad import WellPadRepository
from app.repositories.well import WellRepository
from app.repositories.trajectory import TrajectoryRepository

FIXTURE_PATH = Path("tests/fixtures/Профили_скважин_3D.xlsm")


def test_real_excel_import_nef_14():
    """Интеграционный тест на реальном файле 'Профили_скважин_3D.xlsm' (NEF-14).
    
    Ожидаемый результат:
    - Профиль 1 — загружается полностью (5706 точек).
    - Профиль 2 — скважина сохраняется, траектория = 0 из-за строк с #REF! (начиная со строки 3336).
    - Профиль 3 — скважина сохраняется, траектория = 0 из-за недостоверного угла (> 180°, со строки 1503).
    - Профиль 4 — загружается полностью (2755 точек), отрицательный DLS проигнорирован.
    - Профиль 5 — загружается полностью (6044 точек).
    - Ошибки в профилях 2 и 3 не блокируют загрузку остальных скважин.
    - Измеряется время обработки и потребление памяти.
    """
    assert FIXTURE_PATH.exists(), f"Файл фикстуры {FIXTURE_PATH} не найден"

    with open(FIXTURE_PATH, "rb") as f:
        file_bytes = f.read()

    client = TestClient(app)

    # Замер времени и памяти
    tracemalloc.start()
    start_time = time.perf_counter()

    # 1. Загрузка через API
    response = client.post(
        "/api/v1/imports/excel",
        data={"well_pad_name": "КП-7 (Реальный тест)"},
        files={"file": ("Профили_скважин_3D.xlsm", file_bytes, "application/vnd.ms-excel.sheet.macroEnabled.12")},
    )
    assert response.status_code == 202
    resp_data = response.json()
    task_id = resp_data["task_id"]

    # 2. Ожидание завершения обработки
    status_data = None
    for _ in range(100):
        status_res = client.get(f"/api/v1/imports/{task_id}")
        assert status_res.status_code == 200, f"Task {task_id} returned 404!"
        status_data = status_res.json()
        if status_data["status"] in ("completed", "completed_with_errors", "failed"):
            break
        time.sleep(0.2)

    elapsed_time = time.perf_counter() - start_time
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak_mem / (1024 * 1024)
    print(f"\n[BENCHMARK] Время обработки: {elapsed_time:.2f} сек. Пиковое потребление памяти: {peak_mb:.2f} МБ.")

    # Проверка общего статуса
    assert status_data["status"] == "completed_with_errors"
    assert status_data["total_sheets"] == 5
    assert status_data["successful_sheets"] == 3  # Профиль 1, 4, 5
    assert status_data["failed_sheets"] == 2      # Профиль 2, 3
    pad_id = status_data["well_pad_id"]
    assert pad_id is not None

    # 3. Проверка диагностического отчёта (NEF-14)
    report_res = client.get(f"/api/v1/imports/{task_id}/report")
    assert report_res.status_code == 200
    report = report_res.json()
    assert report["file_status"] == "accepted"
    assert len(report["sheets"]) == 5

    sheets_by_name = {s["sheet_name"]: s for s in report["sheets"]}

    # Профиль 1
    p1 = sheets_by_name["Профиль 1"]
    assert p1["trajectory_status"] == "loaded"
    assert p1["points_count"] == 5706
    assert p1["warnings_count"] > 0, "Лишние столбцы должны быть зафиксированы как предупреждения"

    # Профиль 2
    p2 = sheets_by_name["Профиль 2"]
    assert p2["trajectory_status"] == "error"
    assert p2["points_count"] == 0
    assert p2["message"] == "Траектория не загружена: ошибка в исходных данных"
    # Должна присутствовать ошибка #REF! со строки 3336
    ref_errors = [e for e in p2["errors"] if e["error_type"] == "ref_error" and e["row"] == 3336]
    assert len(ref_errors) >= 1, "В Профиле 2 должна быть зафиксирована ошибка #REF! на строке 3336"

    # Профиль 3
    p3 = sheets_by_name["Профиль 3"]
    assert p3["trajectory_status"] == "error"
    assert p3["points_count"] == 0
    assert p3["message"] == "Траектория не загружена: ошибка в исходных данных"
    # Должна присутствовать ошибка угла вне диапазона со строки 1503
    inc_errors = [e for e in p3["errors"] if e["error_type"] == "out_of_range" and e["column"] == "Inclination"]
    assert len(inc_errors) >= 1, "В Профиле 3 должна быть зафиксирована ошибка зенитного угла"
    assert inc_errors[0]["row"] == 1503, f"Первая ошибка угла ожидалась на строке 1503, получена: {inc_errors[0]['row']}"

    # Профиль 4
    p4 = sheets_by_name["Профиль 4"]
    assert p4["trajectory_status"] == "loaded"
    assert p4["points_count"] == 2755

    # Профиль 5
    p5 = sheets_by_name["Профиль 5"]
    assert p5["trajectory_status"] == "loaded"
    assert p5["points_count"] == 6044

    # 4. Проверка структуры кустовой площадки
    pad_res = client.get(f"/api/v1/well-pads/{pad_id}")
    assert pad_res.status_code == 200
    pad_data = pad_res.json()
    assert pad_data["wells_count"] == 5
    wells = {w["name"]: w for w in pad_data["wells"]}

    # Все 5 скважин сохранены!
    assert "Профиль 1" in wells
    assert "Профиль 2" in wells
    assert "Профиль 3" in wells
    assert "Профиль 4" in wells
    assert "Профиль 5" in wells

    # Проверка карточки скважины Профиль 2
    w2_id = wells["Профиль 2"]["id"]
    w2_card_res = client.get(f"/api/v1/wells/{w2_id}")
    assert w2_card_res.status_code == 200
    w2_card = w2_card_res.json()
    assert w2_card["trajectory_status"] == "error"
    assert w2_card["trajectory_error_message"] == "Траектория не загружена: ошибка в исходных данных"
    assert w2_card["points_count"] == 0

    # Проверка эндпоинта траектории для Профиля 2: возвращается 0 точек
    w2_traj_res = client.get(f"/api/v1/wells/{w2_id}/trajectory")
    assert w2_traj_res.status_code == 200
    w2_traj = w2_traj_res.json()
    assert w2_traj["trajectory_status"] == "error"
    assert w2_traj["total_points"] == 0
    assert len(w2_traj["points"]) == 0

    # Проверка эндпоинта траектории для Профиля 1: возвращаются точки с атрибутами NEF-14
    w1_id = wells["Профиль 1"]["id"]
    w1_traj_res = client.get(f"/api/v1/wells/{w1_id}/trajectory?limit=10")
    assert w1_traj_res.status_code == 200
    w1_traj = w1_traj_res.json()
    assert w1_traj["trajectory_status"] == "loaded"
    assert w1_traj["total_points"] == 5706
    assert len(w1_traj["points"]) == 10
    first_pt = w1_traj["points"][0]
    assert "md" in first_pt
    assert "tvd" in first_pt
    assert "inclination" in first_pt
    assert "azimuth" in first_pt
    assert "ns" in first_pt
    assert "ew" in first_pt
    assert "x" in first_pt
    assert "y" in first_pt
    assert "z" in first_pt
