from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class WellPadBase(BaseModel):
    name: str = Field(..., description="Название кустовой площадки")
    field_name: Optional[str] = Field(None, description="Месторождение")
    crs: Optional[str] = Field("UNKNOWN", description="Система координат (уточняется у заказчика)")


class WellPadCreate(WellPadBase):
    pass


class WellPadSummaryResponse(WellPadBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    wells_count: int = 0
    created_at: datetime
    updated_at: datetime


class WellPadDetailResponse(WellPadBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    wells_count: int = 0
    wells: List["WellSummaryResponse"] = []
    created_at: datetime
    updated_at: datetime


# Forward reference will be resolved in __init__.py
from app.schemas.well import WellSummaryResponse  # noqa: E402
WellPadDetailResponse.model_rebuild()
