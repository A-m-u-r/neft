from typing import List
from pydantic import BaseModel, Field


class TrajectoryPointResponse(BaseModel):
    point_index: int
    md: float = Field(..., description="Измеренная глубина (Measured Depth), м")
    tvd: float = Field(..., description="Истинная вертикальная глубина (True Vertical Depth), м")
    inclination: float = Field(..., description="Зенитный угол, град [0-180]")
    azimuth: float = Field(..., description="Азимут, град [0-360]")
    deviation_ns: float = Field(..., description="Смещение Север-Юг, м")
    deviation_ew: float = Field(..., description="Смещение Восток-Запад, м")
    x: float = Field(..., description="Вычисленная координата X = wellhead_x + DeviationEW")
    y: float = Field(..., description="Вычисленная координата Y = wellhead_y + DeviationNS")
    z: float = Field(..., description="Вычисленная отметка Z = wellhead_z - TVD")


class TrajectoryResponse(BaseModel):
    well_id: str
    well_name: str
    wellhead_x: float
    wellhead_y: float
    wellhead_z: float
    trajectory_status: str
    total_points: int
    returned_points: int
    offset: int
    limit: int
    step: int = Field(default=1, description="Шаг прореживания (1 = все точки)")
    points: List[TrajectoryPointResponse] = []
