from typing import List, Dict, Any, Tuple
from sqlalchemy import select, delete, insert, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trajectory_point import TrajectoryPoint


class TrajectoryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def delete_by_well_id(self, well_id: str) -> None:
        """Удаляет существующие точки траектории скважины (для идемпотентного переимпорта)."""
        stmt = delete(TrajectoryPoint).where(TrajectoryPoint.well_id == well_id)
        await self.session.execute(stmt)

    async def bulk_save_points(self, well_id: str, points: List[Dict[str, Any]]) -> int:
        """Массовое сохранение точек траектории с высокой производительностью."""
        await self.delete_by_well_id(well_id)

        if not points:
            return 0

        records = [
            {
                "well_id": well_id,
                "point_index": idx,
                "md": pt["MD"],
                "tvd": pt["TVD"],
                "inclination": pt["Inclination"],
                "azimuth": pt["Azimuth"],
                "deviation_ns": pt["DeviationNS"],
                "deviation_ew": pt["DeviationEW"],
                "dls": pt.get("DLS"),
            }
            for idx, pt in enumerate(points)
        ]

        batch_size = 2000
        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            await self.session.execute(insert(TrajectoryPoint), batch)

        await self.session.flush()
        return len(records)

    async def get_points(
        self,
        well_id: str,
        offset: int = 0,
        limit: int = 1000,
        step: int = 1,
    ) -> Tuple[List[TrajectoryPoint], int]:
        count_stmt = select(func.count(TrajectoryPoint.id)).where(TrajectoryPoint.well_id == well_id)
        total_points = (await self.session.execute(count_stmt)).scalar_one()

        if total_points == 0:
            return [], 0

        query = (
            select(TrajectoryPoint)
            .where(TrajectoryPoint.well_id == well_id)
            .order_by(TrajectoryPoint.point_index)
        )

        if step > 1:
            query = query.where(TrajectoryPoint.point_index % step == 0)

        query = query.offset(offset).limit(limit)
        result = await self.session.execute(query)
        points = list(result.scalars().all())
        return points, total_points
