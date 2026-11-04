import os
import time
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings, BASE_DIR
from app.database.session import AsyncSessionLocal
from app.repositories.import_task import ImportTaskRepository
from app.workers.import_worker import ImportWorker
from app.services.import_service import import_service


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_01_task_creation_and_immediate_get_by_task_id(client, make_excel):
    """1. Создание задания и немедленное получение по task_id (проверка отсутствия 404)."""
    data = {
        "Скважина 1": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [10.0, 10.0, 1.0, 45.0, 0.1, 0.1],
        ]
    }
    content = make_excel(data)

    res = client.post(
        "/api/v1/imports/excel",
        data={"well_pad_name": "Куст-Немедленный-Запрос"},
        files={"file": ("test_immediate.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert res.status_code == 202
    task_id = res.json()["task_id"]

    # Немедленный запрос статуса: запись в БД УЖЕ существует, 404 исключен!
    status_res = client.get(f"/api/v1/imports/{task_id}")
    assert status_res.status_code == 200, f"Task {task_id} вернул 404 при немедленном запросе!"
    task_data = status_res.json()
    assert task_data["task_id"] == task_id
    assert task_data["filename"] == "test_immediate.xlsx"
    assert task_data["status"] in ("pending", "processing", "completed")


def test_02_diagnostic_report_retrieval(client, make_excel):
    """2. Получение диагностического отчёта со списком ошибок."""
    data = {
        "Скважина С Ошибкой": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [10.0, 10.0, 250.0, 90.0, 0.0, 0.5],  # Ошибка угла
        ]
    }
    content = make_excel(data)

    res = client.post(
        "/api/v1/imports/excel",
        files={"file": ("test_report.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    task_id = res.json()["task_id"]

    # Ожидание обработки
    for _ in range(50):
        s = client.get(f"/api/v1/imports/{task_id}").json()
        if s["status"] in ("completed", "completed_with_errors", "failed"):
            break
        time.sleep(0.1)

    report_res = client.get(f"/api/v1/imports/{task_id}/report")
    assert report_res.status_code == 200
    report = report_res.json()
    assert report["task_id"] == task_id
    assert report["failed_sheets"] == 1
    sheet_rep = report["sheets"][0]
    assert sheet_rep["trajectory_status"] == "error"
    assert len(sheet_rep["errors"]) >= 1
    assert sheet_rep["errors"][0]["column"] == "Inclination"
    assert sheet_rep["errors"][0]["row"] == 3


@pytest.mark.asyncio
async def test_03_worker_processes_task(make_excel):
    """3. Обработка задания worker через цикл ImportWorker."""
    data = {
        "Скважина Воркера": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [10.0, 10.0, 2.0, 90.0, 0.1, 0.1],
        ]
    }
    content = make_excel(data)

    # Создаем задачу без запуска фона
    with patch.object(settings, "USE_REDIS_QUEUE", True), \
         patch("app.services.task_queue.task_queue_service.enqueue_import_task", return_value=True):
        task_id = await import_service.create_import_task(content, "worker_task.xlsx", "Куст-Воркер")

    # Проверяем, что задача в статусе pending
    async with AsyncSessionLocal() as session:
        repo = ImportTaskRepository(session)
        task = await repo.get_by_id(task_id)
        assert task.status == "pending"

    # Запускаем воркер на одну итерацию
    worker = ImportWorker()

    def mock_pop(timeout=2):
        worker.running = False
        return {"task_id": task_id}

    with patch("app.workers.import_worker.task_queue_service.pop_task", side_effect=mock_pop):
        await worker.run()

    # Проверяем, что воркер обновил статус до completed
    async with AsyncSessionLocal() as session:
        repo = ImportTaskRepository(session)
        task = await repo.get_by_id(task_id)
        assert task.status == "completed"
        assert task.successful_sheets == 1


def test_04_shared_database_path_consistency():
    """4. Единая БД для API и worker: путь к SQLite файлу всегда абсолютный."""
    assert os.path.isabs(settings.LOCAL_STORAGE_DIR), "LOCAL_STORAGE_DIR должен быть абсолютным путем"
    if "sqlite" in settings.DATABASE_URL:
        # URL должен содержать абсолютный путь к проекту
        expected_part = BASE_DIR.as_posix()
        assert expected_part in settings.DATABASE_URL, (
            f"DATABASE_URL ({settings.DATABASE_URL}) должен быть привязан к BASE_DIR ({expected_part})"
        )


@pytest.mark.asyncio
async def test_05_redis_failure_keeps_task_as_failed(make_excel):
    """5. Ошибка Redis: задание не теряется, сохраняется в БД со статусом failed и описанием ошибки."""
    data = {
        "Скважина 1": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        ]
    }
    content = make_excel(data)

    # Симулируем включенный Redis и сбой подключения к Redis
    with patch.object(settings, "USE_REDIS_QUEUE", True), \
         patch("app.services.task_queue.task_queue_service.enqueue_import_task", side_effect=ConnectionError("Redis сервер недоступен")):
        
        task_id = await import_service.create_import_task(content, "redis_fail.xlsx", "Куст-Redis-Fail")

    # Проверяем, что задание НЕ исчезло и получило статус failed
    async with AsyncSessionLocal() as session:
        repo = ImportTaskRepository(session)
        task = await repo.get_by_id(task_id)
        assert task is not None, "Задание не должно исчезать при ошибке Redis"
        assert task.status == "failed"
        assert "Redis" in task.error_message


def test_06_file_level_error_missing_column_rejects_file(client, make_excel):
    """6. Ошибка уровня файла (NEF-14 Таблица 3): отсутствие обязательного столбца отклоняет файл."""
    data = {
        "Лист Без TVD": [
            ["MD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],  # Нет TVD
            [0.0, 0.0, 0.0, 0.0, 0.0],
        ],
        "Лист Валидный": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        ]
    }
    content = make_excel(data)

    res = client.post(
        "/api/v1/imports/excel",
        files={"file": ("missing_col_file.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    task_id = res.json()["task_id"]

    for _ in range(50):
        s = client.get(f"/api/v1/imports/{task_id}").json()
        if s["status"] in ("completed", "completed_with_errors", "failed"):
            break
        time.sleep(0.1)

    assert s["status"] == "failed"
    assert "отсутствуют обязательные столбцы" in s["error_message"].lower()

    # Проверяем, что в отчёте указан file_status = rejected
    report_res = client.get(f"/api/v1/imports/{task_id}/report")
    assert report_res.status_code == 200
    rep = report_res.json()
    assert rep["file_status"] == "rejected"


def test_07_corrupted_excel_processing_error(client):
    """7. Ошибка обработки повреждённого Excel-файла (невалидный zip/xml): статус failed с понятной причиной."""
    garbage_bytes = b"NOT_A_VALID_EXCEL_ZIP_CONTENT_HERE"

    res = client.post(
        "/api/v1/imports/excel",
        files={"file": ("garbage.xlsx", garbage_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    task_id = res.json()["task_id"]

    for _ in range(50):
        s = client.get(f"/api/v1/imports/{task_id}").json()
        if s["status"] in ("completed", "completed_with_errors", "failed"):
            break
        time.sleep(0.1)

    assert s["status"] == "failed"
    assert s["error_message"] is not None
    assert "ошибка" in s["error_message"].lower() or "не удалось" in s["error_message"].lower()


def test_08_successful_import_completion(client, make_excel):
    """8. Успешное завершение импорта для чистого файла."""
    data = {
        "Скважина А": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [10.0, 10.0, 1.0, 45.0, 0.1, 0.1],
        ],
        "Скважина Б": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [10.0, 10.0, 2.0, 90.0, 0.2, 0.2],
        ],
    }
    content = make_excel(data)

    res = client.post(
        "/api/v1/imports/excel",
        data={"well_pad_name": "Куст-Идеальный"},
        files={"file": ("clean_wells.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    task_id = res.json()["task_id"]

    for _ in range(50):
        s = client.get(f"/api/v1/imports/{task_id}").json()
        if s["status"] in ("completed", "completed_with_errors", "failed"):
            break
        time.sleep(0.1)

    assert s["status"] == "completed"
    assert s["total_sheets"] == 2
    assert s["successful_sheets"] == 2
    assert s["failed_sheets"] == 0
