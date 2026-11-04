import pytest
import asyncio
from unittest.mock import MagicMock, patch
from app.workers.import_worker import ImportWorker


@pytest.mark.asyncio
async def test_worker_processes_task():
    worker = ImportWorker()
    processed_tasks = []

    async def mock_process(task_id):
        processed_tasks.append(task_id)
        worker.running = False

    with patch("app.workers.import_worker.task_queue_service.pop_task") as mock_pop, \
         patch("app.workers.import_worker.import_service.process_import_task", side_effect=mock_process), \
         patch("app.workers.import_worker.init_db"):
        
        mock_pop.return_value = {"task_id": "test-task-123"}
        await worker.run()

    assert processed_tasks == ["test-task-123"]
