from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.repositories.well import WellRepository
from app.repositories.trajectory import TrajectoryRepository
from app.schemas.well import (
    WellSummaryResponse,
    WellCardResponse,
    WellUpdate,
)
from app.schemas.trajectory import (
    TrajectoryPointResponse,
    TrajectoryResponse,
)

router = APIRouter(prefix="/wells", tags=["wells"])


@router.get("", response_model=List[WellSummaryResponse])
async def list_wells(
    well_pad_id: Optional[str] = Query(None, description="Фильтр по ID кустовой площадки"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Получение списка скважин."""
    repo = WellRepository(db)
    wells, _ = await repo.list_wells(well_pad_id=well_pad_id, skip=skip, limit=limit)
    return wells


@router.get("/{well_id}", response_model=WellCardResponse)
async def get_well_card(
    well_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Получение карточки скважины.
    
    Карточка скважины всегда доступна, даже если профиль повреждён.
    """
    repo = WellRepository(db)
    well = await repo.get_by_id(well_id, load_pad=True)
    if not well:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Скважина не найдена")

    return WellCardResponse(
        id=well.id,
        well_pad_id=well.well_pad_id,
        well_pad_name=well.well_pad.name if well.well_pad else None,
        name=well.name,
        wellhead_x=well.wellhead_x,
        wellhead_y=well.wellhead_y,
        wellhead_z=well.wellhead_z,
        trajectory_status=well.trajectory_status,
        trajectory_error_message=well.trajectory_error_message,
        points_count=well.points_count,
        created_at=well.created_at,
        updated_at=well.updated_at,
    )


@router.patch("/{well_id}", response_model=WellCardResponse)
async def update_well(
    well_id: str,
    payload: WellUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Обновление параметров скважины (например, устьевых координат)."""
    repo = WellRepository(db)
    well = await repo.get_by_id(well_id, load_pad=True)
    if not well:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Скважина не найдена")

    await repo.update_wellhead(
        well_id=well_id,
        wellhead_x=payload.wellhead_x,
        wellhead_y=payload.wellhead_y,
        wellhead_z=payload.wellhead_z,
    )
    await db.commit()
    updated_well = await repo.get_by_id(well_id, load_pad=True)

    return WellCardResponse(
        id=updated_well.id,
        well_pad_id=updated_well.well_pad_id,
        well_pad_name=updated_well.well_pad.name if updated_well.well_pad else None,
        name=updated_well.name,
        wellhead_x=updated_well.wellhead_x,
        wellhead_y=updated_well.wellhead_y,
        wellhead_z=updated_well.wellhead_z,
        trajectory_status=updated_well.trajectory_status,
        trajectory_error_message=updated_well.trajectory_error_message,
        points_count=updated_well.points_count,
        created_at=updated_well.created_at,
        updated_at=updated_well.updated_at,
    )


@router.get("/{well_id}/trajectory", response_model=TrajectoryResponse)
async def get_well_trajectory(
    well_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=10000),
    step: int = Query(1, ge=1, le=100, description="Шаг прореживания (1 = все точки)"),
    db: AsyncSession = Depends(get_db),
):
    """Получение точек траектории скважины с вычисленными геопривязанными координатами.
    
    Геопривязка (Раздел 8):
    - X = wellhead_x + DeviationEW
    - Y = wellhead_y + DeviationNS
    - Z = wellhead_z - TVD (отметка по вертикали)
    
    Если статус траектории 'error', точки не возвращаются.
    """
    well_repo = WellRepository(db)
    well = await well_repo.get_by_id(well_id)
    if not well:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Скважина не найдена")

    # Если траектория повреждена или не загружена, возвращаем пустой массив точек
    if well.trajectory_status != "loaded":
        return TrajectoryResponse(
            well_id=well.id,
            well_name=well.name,
            wellhead_x=well.wellhead_x,
            wellhead_y=well.wellhead_y,
            wellhead_z=well.wellhead_z,
            trajectory_status=well.trajectory_status,
            total_points=0,
            returned_points=0,
            offset=offset,
            limit=limit,
            step=step,
            points=[],
        )

    trajectory_repo = TrajectoryRepository(db)
    raw_points, total_points = await trajectory_repo.get_points(
        well_id=well.id,
        offset=offset,
        limit=limit,
        step=step,
    )

    # Вычисление абсолютных координат X, Y, Z
    point_responses = [
        TrajectoryPointResponse(
            point_index=pt.point_index,
            md=pt.md,
            tvd=pt.tvd,
            inclination=pt.inclination,
            azimuth=pt.azimuth,
            deviation_ns=pt.deviation_ns,
            deviation_ew=pt.deviation_ew,
            ns=pt.deviation_ns,
            ew=pt.deviation_ew,
            dls=pt.dls,
            x=well.wellhead_x + pt.deviation_ew,
            y=well.wellhead_y + pt.deviation_ns,
            z=well.wellhead_z - pt.tvd,
        )
        for pt in raw_points
    ]

    return TrajectoryResponse(
        well_id=well.id,
        well_name=well.name,
        wellhead_x=well.wellhead_x,
        wellhead_y=well.wellhead_y,
        wellhead_z=well.wellhead_z,
        trajectory_status=well.trajectory_status,
        total_points=total_points,
        returned_points=len(point_responses),
        offset=offset,
        limit=limit,
        step=step,
        points=point_responses,
    )
