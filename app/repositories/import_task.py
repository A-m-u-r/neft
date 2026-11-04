from typing import Optional, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_task import ImportTask


class ImportTaskRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, task_id: str) -> Optional[ImportTask]:
        query = select(ImportTask).where(ImportTask.id == task_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create(
        self,
        filename: str,
        storage_path: Optional[str] = None,
        well_pad_id: Optional[str] = None,
        well_pad_name: Optional[str] = None,
    ) -> ImportTask:
        task = ImportTask(
            filename=filename,
            storage_path=storage_path,
            well_pad_id=well_pad_id,
            well_pad_name=well_pad_name,
            status="pending",
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def update_status(
        self,
        task_id: str,
        status: str,
        total_sheets: int = 0,
        successful_sheets: int = 0,
        failed_sheets: int = 0,
        diagnostic_report: Optional[Any] = None,
        error_message: Optional[str] = None,
        well_pad_id: Optional[str] = None,
    ) -> Optional[ImportTask]:
        task = await self.get_by_id(task_id)
        if task:
            task.status = status
            task.total_sheets = total_sheets
            task.successful_sheets = successful_sheets
            task.failed_sheets = failed_sheets
            if diagnostic_report is not None:
                task.diagnostic_report = diagnostic_report
            if error_message is not None:
                task.error_message = error_message
            if well_pad_id is not None:
                task.well_pad_id = well_pad_id
            await self.session.flush()
        return task
