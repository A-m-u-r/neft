from typing import List, Optional
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.well_pad import WellPad
from app.models.well import Well


class WellPadRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, pad_id: str, load_wells: bool = False) -> Optional[WellPad]:
        """Возвращает кустовую площадку по ID с опциональной загрузкой связанных скважин."""
        query = select(WellPad).where(WellPad.id == pad_id)
        if load_wells:
            query = query.options(selectinload(WellPad.wells))
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str, load_wells: bool = True) -> Optional[WellPad]:
        """Поиск кустовой площадки по уникальному названию."""
        query = select(WellPad).where(WellPad.name == name)
        if load_wells:
            query = query.options(selectinload(WellPad.wells))
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_or_create(self, name: str, field_name: Optional[str] = None) -> WellPad:
        """Возвращает существующую кустовую площадку или создает новую."""
        pad = await self.get_by_name(name)
        if not pad:
            pad = WellPad(name=name, field_name=field_name)
            self.session.add(pad)
            await self.session.flush()
        return pad

    async def list_all(self, skip: int = 0, limit: int = 100) -> List[WellPad]:
        """Возвращает список всех кустовых площадок."""
        query = select(WellPad).options(selectinload(WellPad.wells)).offset(skip).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(self, name: str, field_name: Optional[str] = None, crs: Optional[str] = "UNKNOWN") -> WellPad:
        """Создает новую запись кустовой площадки."""
        pad = WellPad(name=name, field_name=field_name, crs=crs)
        self.session.add(pad)
        await self.session.flush()
        return pad
