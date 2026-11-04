import pytest
import time
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_api_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    res_v1 = client.get("/api/v1/health")
    assert res_v1.status_code == 200
    assert res_v1.json() == {"status": "ok"}


def test_api_import_validation(client):
    # Неверный формат файла
    res = client.post(
        "/api/v1/imports/excel",
        files={"file": ("test.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert res.status_code == 415

    # Пустой файл
    res = client.post(
        "/api/v1/imports/excel",
        files={"file": ("test.xlsx", b"", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert res.status_code == 400


def test_api_full_workflow(client, make_excel):
    # 1. Генерируем тестовый файл с 2 скважинами: одной валидной и одной с ошибкой
    data = {
        "Скважина Валидная": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [10.0, 10.0, 5.0, 90.0, 0.0, 0.87],
        ],
        "Скважина С Ошибкой": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [10.0, 10.0, 250.0, 90.0, 0.0, 0.5],  # Зенитный угол 250° > 180°
        ],
    }
    content = make_excel(data)

    # 2. Загрузка файла через API
    response = client.post(
        "/api/v1/imports/excel",
        data={"well_pad_name": "Тестовый Куст API"},
        files={"file": ("test_cluster.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 202
    resp_data = response.json()
    task_id = resp_data["task_id"]
    assert task_id is not None

    # 3. Ожидание завершения обработки
    status_data = None
    for _ in range(30):
        res = client.get(f"/api/v1/imports/{task_id}")
        assert res.status_code == 200
        status_data = res.json()
        if status_data["status"] in ("completed", "completed_with_errors", "failed"):
            break
        time.sleep(0.1)

    assert status_data["status"] == "completed_with_errors"
    assert status_data["total_sheets"] == 2
    assert status_data["successful_sheets"] == 1
    assert status_data["failed_sheets"] == 1
    pad_id = status_data["well_pad_id"]
    assert pad_id is not None

    # 4. Проверка диагностического отчёта
    report_res = client.get(f"/api/v1/imports/{task_id}/report")
    assert report_res.status_code == 200
    report_data = report_res.json()
    assert report_data["task_id"] == task_id
    assert len(report_data["sheets"]) == 2
    err_sheet = next(s for s in report_data["sheets"] if s["sheet_name"] == "Скважина С Ошибкой")
    assert err_sheet["trajectory_status"] == "error"
    assert err_sheet["errors_count"] >= 1
    assert err_sheet["errors"][0]["column"] == "Inclination"

    # 5. Проверка структуры кустовой площадки
    pad_res = client.get(f"/api/v1/well-pads/{pad_id}")
    assert pad_res.status_code == 200
    pad_data = pad_res.json()
    assert pad_data["name"] == "Тестовый Куст API"
    assert pad_data["wells_count"] == 2
    wells = pad_data["wells"]

    valid_well = next(w for w in wells if w["name"] == "Скважина Валидная")
    assert valid_well["trajectory_status"] == "loaded"
    assert valid_well["points_count"] == 2

    broken_well = next(w for w in wells if w["name"] == "Скважина С Ошибкой")
    assert broken_well["trajectory_status"] == "error"
    assert broken_well["trajectory_error_message"] == "Траектория не загружена: ошибка в исходных данных"
    assert broken_well["points_count"] == 0

    # 6. Получение карточки скважины
    card_res = client.get(f"/api/v1/wells/{valid_well['id']}")
    assert card_res.status_code == 200
    card_data = card_res.json()
    assert card_data["wellhead_x"] == 0.0
    assert card_data["wellhead_y"] == 0.0
    assert card_data["wellhead_z"] == 0.0

    # 7. Обновление устьевых координат
    patch_res = client.patch(
        f"/api/v1/wells/{valid_well['id']}",
        json={"wellhead_x": 500000.0, "wellhead_y": 6500000.0, "wellhead_z": 120.0},
    )
    assert patch_res.status_code == 200
    patched_data = patch_res.json()
    assert patched_data["wellhead_x"] == 500000.0
    assert patched_data["wellhead_y"] == 6500000.0
    assert patched_data["wellhead_z"] == 120.0

    # 8. Проверка геопривязки траектории (Раздел 8)
    # X = wellhead_x + DeviationEW (500000.0 + 0.87 = 500000.87)
    # Y = wellhead_y + DeviationNS (6500000.0 + 0.0 = 6500000.0)
    # Z = wellhead_z - TVD (120.0 - 10.0 = 110.0)
    traj_res = client.get(f"/api/v1/wells/{valid_well['id']}/trajectory")
    assert traj_res.status_code == 200
    traj_data = traj_res.json()
    assert traj_data["trajectory_status"] == "loaded"
    assert traj_data["total_points"] == 2
    assert len(traj_data["points"]) == 2

    pt2 = traj_data["points"][1]
    assert pt2["x"] == pytest.approx(500000.87)
    assert pt2["y"] == pytest.approx(6500000.0)
    assert pt2["z"] == pytest.approx(110.0)

    # 9. Проверка повреждённой траектории: точки не возвращаются
    broken_traj_res = client.get(f"/api/v1/wells/{broken_well['id']}/trajectory")
    assert broken_traj_res.status_code == 200
    broken_traj_data = broken_traj_res.json()
    assert broken_traj_data["trajectory_status"] == "error"
    assert broken_traj_data["total_points"] == 0
    assert broken_traj_data["points"] == []
