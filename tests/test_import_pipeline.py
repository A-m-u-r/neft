import pytest
import asyncio
from app.services.import_service import import_service
from app.database.session import AsyncSessionLocal, init_db
from app.repositories.well_pad import WellPadRepository
from app.repositories.well import WellRepository
from app.repositories.trajectory import TrajectoryRepository
from app.repositories.import_task import ImportTaskRepository


@pytest.mark.asyncio
async def test_section_6_five_profiles_pipeline(make_excel):
    """Тестирование сценария Раздела 6 (5 профилей) и сквозного сохранения в БД.
    
    Ожидаемое поведение:
    - Профиль 1: Загружается (ошибки в лишних столбцах не влияют)
    - Профиль 2: Ошибка (строки с #REF!) -> статус 'error', скважина сохраняется, траектория = 0
    - Профиль 3: Ошибка (угол до 57650°) -> статус 'error', скважина сохраняется, траектория = 0
    - Профиль 4: Загружается (отрицательный DLS игнорируется)
    - Профиль 5: Загружается (чистые данные)
    """
    await init_db()

    data = {
        "Профиль 1": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW", "ExtraFormulaCol"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "#NAME?"],
            [10.0, 10.0, 2.5, 45.0, 0.3, 0.3, "#REF!"],
        ],
        "Профиль 2": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [10.0, "#REF!", 5.0, 45.0, 0.5, 0.5],
        ],
        "Профиль 3": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW", "DLS"],
            [1499.0, 1450.0, 15.0, 120.0, 100.0, 50.0, 0.5],
            [1500.0, 1451.0, 57650.0, 120.0, 100.5, 50.5, 120.0],  # Недостоверный угол 57650°
        ],
        "Профиль 4": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW", "DLS"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -0.15],  # Отрицательный DLS
            [10.0, 10.0, 1.0, 90.0, 0.0, 0.2, -0.25],
        ],
        "Профиль 5": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [10.0, 10.0, 1.5, 180.0, -0.3, 0.0],
            [20.0, 20.0, 3.0, 180.0, -0.8, 0.0],
        ],
    }

    content = make_excel(data)
    filename = "five_profiles_test.xlsx"

    # Создание задачи импорта
    task_id = await import_service.create_import_task(
        file_bytes=content,
        filename=filename,
        well_pad_name="Кустовая площадка 101",
    )

    # Ждём завершения обработки задачи
    for _ in range(50):
        async with AsyncSessionLocal() as session:
            repo = ImportTaskRepository(session)
            task = await repo.get_by_id(task_id)
            if task and task.status in ("completed", "completed_with_errors", "failed"):
                break
        await asyncio.sleep(0.1)

    assert task.status == "completed_with_errors"
    assert task.total_sheets == 5
    assert task.successful_sheets == 3  # Профиль 1, 4, 5
    assert task.failed_sheets == 2      # Профиль 2, 3

    # Проверка сущностей в БД
    async with AsyncSessionLocal() as session:
        pad_repo = WellPadRepository(session)
        well_repo = WellRepository(session)
        traj_repo = TrajectoryRepository(session)

        pad = await pad_repo.get_by_name("Кустовая площадка 101")
        assert pad is not None
        assert len(pad.wells) == 5

        # Профиль 1: Загружен
        w1 = await well_repo.get_by_pad_and_name(pad.id, "Профиль 1")
        assert w1.trajectory_status == "loaded"
        assert w1.points_count == 2
        pts1, _ = await traj_repo.get_points(w1.id)
        assert len(pts1) == 2

        # Профиль 2: Ошибка (NEF-27: скважина сохранена, траектория = 0)
        w2 = await well_repo.get_by_pad_and_name(pad.id, "Профиль 2")
        assert w2 is not None
        assert w2.trajectory_status == "error"
        assert w2.trajectory_error_message == "Траектория не загружена: ошибка в исходных данных"
        assert w2.points_count == 0
        pts2, _ = await traj_repo.get_points(w2.id)
        assert len(pts2) == 0

        # Профиль 3: Ошибка (NEF-27)
        w3 = await well_repo.get_by_pad_and_name(pad.id, "Профиль 3")
        assert w3 is not None
        assert w3.trajectory_status == "error"
        assert w3.trajectory_error_message == "Траектория не загружена: ошибка в исходных данных"
        assert w3.points_count == 0
        pts3, _ = await traj_repo.get_points(w3.id)
        assert len(pts3) == 0

        # Профиль 4: Загружен
        w4 = await well_repo.get_by_pad_and_name(pad.id, "Профиль 4")
        assert w4.trajectory_status == "loaded"
        assert w4.points_count == 2

        # Профиль 5: Загружен
        w5 = await well_repo.get_by_pad_and_name(pad.id, "Профиль 5")
        assert w5.trajectory_status == "loaded"
        assert w5.points_count == 3


@pytest.mark.asyncio
async def test_11_reimport_does_not_create_duplicates(make_excel):
    """11. Повторный импорт не создаёт дубликаты."""
    await init_db()

    data = {
        "Скважина 777": [
            ["MD", "TVD", "Inclination", "Azimuth", "DeviationNS", "DeviationEW"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [10.0, 10.0, 2.0, 45.0, 0.2, 0.2],
        ]
    }
    content = make_excel(data)
    pad_name = "Куст-777"

    # Первый импорт
    task_id1 = await import_service.create_import_task(content, "file.xlsx", pad_name)
    await asyncio.sleep(0.3)

    # Второй импорт того же файла
    task_id2 = await import_service.create_import_task(content, "file.xlsx", pad_name)
    await asyncio.sleep(0.3)

    async with AsyncSessionLocal() as session:
        pad_repo = WellPadRepository(session)
        well_repo = WellRepository(session)
        traj_repo = TrajectoryRepository(session)

        pads = await pad_repo.list_all()
        target_pads = [p for p in pads if p.name == pad_name]
        assert len(target_pads) == 1, "Кустовая площадка не должна дублироваться"

        pad = target_pads[0]
        wells, total_wells = await well_repo.list_wells(well_pad_id=pad.id)
        assert total_wells == 1, "Скважина не должна дублироваться при повторном импорте"

        pts, total_pts = await traj_repo.get_points(wells[0].id)
        assert total_pts == 2, "Точки не должны дублироваться при повторном импорте"
