from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class WellBase(BaseModel):
    name: str = Field(..., description="Название / номер скважины")
    wellhead_x: float = Field(default=0.0, description="Координата устья X")
    wellhead_y: float = Field(default=0.0, description="Координата устья Y")
    wellhead_z: float = Field(default=0.0, description="Координата устья Z (альтитуда устья)")


class WellSummaryResponse(WellBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    well_pad_id: str
    trajectory_status: str = Field(..., description="not_loaded, loaded, error")
    trajectory_error_message: Optional[str] = None
    points_count: int = 0
    created_at: datetime
    updated_at: datetime


class WellCardResponse(WellSummaryResponse):
    well_pad_name: Optional[str] = None


class WellUpdate(BaseModel):
    wellhead_x: Optional[float] = None
    wellhead_y: Optional[float] = None
    wellhead_z: Optional[float] = None
