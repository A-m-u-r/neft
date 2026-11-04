from typing import List, Optional, Tuple
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.well import Well
from app.models.well_pad import WellPad


class WellRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, well_id: str, load_pad: bool = False) -> Optional[Well]:
        """Возвращает скважину по ID с опциональной загрузкой кустовой площадки."""
        query = select(Well).where(Well.id == well_id)
        if load_pad:
            query = query.options(selectinload(Well.well_pad))
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_pad_and_name(self, well_pad_id: str, name: str) -> Optional[Well]:
        """Поиск скважины по ID куста и имени."""
        query = select(Well).where(Well.well_pad_id == well_pad_id, Well.name == name)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        well_pad_id: str,
        name: str,
        wellhead_x: float = 0.0,
        wellhead_y: float = 0.0,
        wellhead_z: float = 0.0,
    ) -> Tuple[Well, bool]:
        """Возвращает (well, created). Если скважина уже существует, дубликат не создаётся."""
        well = await self.get_by_pad_and_name(well_pad_id, name)
        if well:
            return well, False

        well = Well(
            well_pad_id=well_pad_id,
            name=name,
            wellhead_x=wellhead_x,
            wellhead_y=wellhead_y,
            wellhead_z=wellhead_z,
            trajectory_status="not_loaded",
        )
        self.session.add(well)
        await self.session.flush()
        return well, True

    async def list_wells(
        self,
        well_pad_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Tuple[List[Well], int]:
        """Возвращает список скважин и общее количество с поддержкой фильтрации и пагинации."""
        query = select(Well)
        if well_pad_id:
            query = query.where(Well.well_pad_id == well_pad_id)

        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.session.execute(count_query)).scalar_one()

        query = query.order_by(Well.name).offset(skip).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all()), total

    async def update_trajectory_status(
        self,
        well_id: str,
        status: str,
        points_count: int,
        error_message: Optional[str] = None,
    ) -> Optional[Well]:
        """Обновляет статус траектории, число точек и текст ошибки скважины."""
        well = await self.get_by_id(well_id)
        if well:
            well.trajectory_status = status
            well.points_count = points_count
            well.trajectory_error_message = error_message
            await self.session.flush()
        return well

    async def update_wellhead(
        self,
        well_id: str,
        wellhead_x: Optional[float] = None,
        wellhead_y: Optional[float] = None,
        wellhead_z: Optional[float] = None,
    ) -> Optional[Well]:
        """Обновляет координаты устья скважины."""
        well = await self.get_by_id(well_id)
        if well:
            if wellhead_x is not None:
                wellhead_x_val = float(wellhead_x)
                well.wellhead_x = wellhead_x_val
            if wellhead_y is not None:
                wellhead_y_val = float(wellhead_y)
                well.wellhead_y = wellhead_y_val
            if wellhead_z is not None:
                wellhead_z_val = float(wellhead_z)
                well.wellhead_z = wellhead_z_val
            await self.session.flush()
        return well
