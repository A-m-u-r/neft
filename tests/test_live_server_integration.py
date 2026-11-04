import os
import socket
import time
import threading
import pytest
import uvicorn
import httpx
from pathlib import Path

from app.main import app
from app.core.config import settings, BASE_DIR

FIXTURE_PATH = Path("tests/fixtures/Профили_скважин_3D.xlsm")


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveServerThread(threading.Thread):
    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.port = port
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self.server = uvicorn.Server(config)

    def run(self):
        self.server.run()

    def stop(self):
        self.server.should_exit = True


def test_live_server_post_get_workflow():
    """Интеграционный тест через реальный запущенный HTTP-сервер uvicorn.
    
    Проверяет:
    1. POST /api/v1/imports/excel -> HTTP 202 и task_id.
    2. Немедленный GET /api/v1/imports/{task_id} -> HTTP 200 (отсутствие 404!).
    3. Ожидание завершения обработки.
    4. GET /api/v1/imports/{task_id}/report -> HTTP 200 и отчёт по 5 скважинам.
    """
    assert FIXTURE_PATH.exists(), f"Файл {FIXTURE_PATH} не найден"
    with open(FIXTURE_PATH, "rb") as f:
        file_bytes = f.read()

    port = get_free_port()
    server_thread = LiveServerThread(port)
    server_thread.start()

    base_url = f"http://127.0.0.1:{port}"
    client = httpx.Client(base_url=base_url, timeout=30.0)

    # Ожидание готовности сервера
    server_ready = False
    for _ in range(30):
        try:
            r = client.get("/health")
            if r.status_code == 200:
                server_ready = True
                break
        except Exception:
            time.sleep(0.1)

    assert server_ready, "Сервер не ответил на /health"

    try:
        # 1. POST /api/v1/imports/excel
        post_res = client.post(
            "/api/v1/imports/excel",
            data={"well_pad_name": "КП-LiveServer"},
            files={"file": ("Профили_скважин_3D.xlsm", file_bytes, "application/vnd.ms-excel.sheet.macroEnabled.12")},
        )
        assert post_res.status_code == 202
        post_data = post_res.json()
        task_id = post_data["task_id"]
        assert task_id is not None

        # 2. Немедленный GET /api/v1/imports/{task_id}
        # Проверяем, что в реальном HTTP-вызове запись в БД уже зафиксирована и не возвращает 404
        immediate_get = client.get(f"/api/v1/imports/{task_id}")
        assert immediate_get.status_code == 200, (
            f"Немедленный GET по task_id={task_id} вернул {immediate_get.status_code}: {immediate_get.text}"
        )
        imm_data = immediate_get.json()
        assert imm_data["task_id"] == task_id
        assert imm_data["status"] in ("pending", "processing", "completed_with_errors", "completed")

        # 3. Ожидание завершения обработки
        completed_data = None
        for _ in range(60):
            poll_res = client.get(f"/api/v1/imports/{task_id}")
            assert poll_res.status_code == 200
            data = poll_res.json()
            if data["status"] in ("completed", "completed_with_errors", "failed"):
                completed_data = data
                break
            time.sleep(0.3)

        assert completed_data is not None, "Превышено время ожидания завершения задачи"
        assert completed_data["status"] == "completed_with_errors"
        assert completed_data["total_sheets"] == 5
        assert completed_data["successful_sheets"] == 3
        assert completed_data["failed_sheets"] == 2

        # 4. GET /api/v1/imports/{task_id}/report
        report_res = client.get(f"/api/v1/imports/{task_id}/report")
        assert report_res.status_code == 200
        report = report_res.json()
        assert report["file_status"] == "accepted"
        assert len(report["sheets"]) == 5

        # Проверка листов
        sheets = {s["sheet_name"]: s for s in report["sheets"]}
        assert sheets["Профиль 1"]["trajectory_status"] == "loaded"
        assert sheets["Профиль 1"]["points_count"] == 5706

        assert sheets["Профиль 2"]["trajectory_status"] == "error"
        assert sheets["Профиль 2"]["points_count"] == 0

        assert sheets["Профиль 3"]["trajectory_status"] == "error"
        assert sheets["Профиль 3"]["points_count"] == 0

        assert sheets["Профиль 4"]["trajectory_status"] == "loaded"
        assert sheets["Профиль 4"]["points_count"] == 2755

        assert sheets["Профиль 5"]["trajectory_status"] == "loaded"
        assert sheets["Профиль 5"]["points_count"] == 6044

    finally:
        server_thread.stop()
