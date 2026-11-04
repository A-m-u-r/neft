from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.repositories.well_pad import WellPadRepository
from app.schemas.well_pad import (
    WellPadSummaryResponse,
    WellPadDetailResponse,
    WellPadCreate,
)
from app.schemas.well import WellSummaryResponse

router = APIRouter(prefix="/well-pads", tags=["well-pads"])


@router.get("", response_model=List[WellPadSummaryResponse])
async def list_well_pads(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Получение списка кустовых площадок."""
    repo = WellPadRepository(db)
    pads = await repo.list_all(skip=skip, limit=limit)
    response = []
    for pad in pads:
        response.append(
            WellPadSummaryResponse(
                id=pad.id,
                name=pad.name,
                field_name=pad.field_name,
                crs=pad.crs,
                wells_count=len(pad.wells),
                created_at=pad.created_at,
                updated_at=pad.updated_at,
            )
        )
    return response


@router.post("", response_model=WellPadSummaryResponse, status_code=status.HTTP_201_CREATED)
async def create_well_pad(
    payload: WellPadCreate,
    db: AsyncSession = Depends(get_db),
):
    """Создание новой кустовой площадки вручную."""
    repo = WellPadRepository(db)
    existing = await repo.get_by_name(payload.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Кустовая площадка с именем '{payload.name}' уже существует",
        )
    pad = await repo.create(
        name=payload.name,
        field_name=payload.field_name,
        crs=payload.crs or "UNKNOWN",
    )
    await db.commit()
    return WellPadSummaryResponse(
        id=pad.id,
        name=pad.name,
        field_name=pad.field_name,
        crs=pad.crs,
        wells_count=0,
        created_at=pad.created_at,
        updated_at=pad.updated_at,
    )


@router.get("/{pad_id}", response_model=WellPadDetailResponse)
async def get_well_pad_structure(
    pad_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Получение структуры кустовой площадки вместе со списком скважин."""
    repo = WellPadRepository(db)
    pad = await repo.get_by_id(pad_id, load_wells=True)
    if not pad:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кустовая площадка не найдена")

    wells_summary = [
        WellSummaryResponse(
            id=w.id,
            well_pad_id=w.well_pad_id,
            name=w.name,
            wellhead_x=w.wellhead_x,
            wellhead_y=w.wellhead_y,
            wellhead_z=w.wellhead_z,
            trajectory_status=w.trajectory_status,
            trajectory_error_message=w.trajectory_error_message,
            points_count=w.points_count,
            created_at=w.created_at,
            updated_at=w.updated_at,
        )
        for w in pad.wells
    ]

    return WellPadDetailResponse(
        id=pad.id,
        name=pad.name,
        field_name=pad.field_name,
        crs=pad.crs,
        wells_count=len(wells_summary),
        wells=wells_summary,
        created_at=pad.created_at,
        updated_at=pad.updated_at,
    )
