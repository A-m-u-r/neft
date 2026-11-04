import os
import pytest
from io import BytesIO
import openpyxl

# Обеспечиваем запуск тестов в тестовом окружении
os.environ["APP_ENV"] = "test"
os.environ["USE_REDIS_QUEUE"] = "false"
os.environ["USE_S3_STORAGE"] = "false"

from app.database.session import init_db, engine
from app.database.base import Base


@pytest.fixture(autouse=True)
async def clean_database():
    """Очищает базу данных перед каждым тестом для полной изоляции."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
def make_excel():
    """Фабрика для генерации байтов Excel-файлов с заданными листами и данными."""

    def _factory(sheets_data: dict, is_xlsm: bool = False) -> bytes:
        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        for sheet_name, rows in sheets_data.items():
            ws = wb.create_sheet(title=sheet_name)
            for row in rows:
                ws.append(row)

        bio = BytesIO()
        wb.save(bio)
        return bio.getvalue()

    return _factory
