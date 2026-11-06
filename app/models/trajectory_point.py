from typing import Optional
from sqlalchemy import Float, Integer, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class TrajectoryPoint(Base):
    """Точка ствола скважины.
    
    Шаг MD: ~1 метр.
    Координаты X/Y в базе отдельно не хранятся, а вычисляются:
    X = wellhead_x + DeviationEW
    Y = wellhead_y + DeviationNS
    Z = wellhead_z - TVD
    """
    __tablename__ = "trajectory_points"
    __table_args__ = (
        Index("ix_trajectory_points_well_id_point_index", "well_id", "point_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    well_id: Mapped[str] = mapped_column(
        ForeignKey("wells.id", ondelete="CASCADE"), index=True, nullable=False
    )
    point_index: Mapped[int] = mapped_column(Integer, nullable=False)
    
    md: Mapped[float] = mapped_column(Float, nullable=False)
    tvd: Mapped[float] = mapped_column(Float, nullable=False)
    inclination: Mapped[float] = mapped_column(Float, nullable=False)
    azimuth: Mapped[float] = mapped_column(Float, nullable=False)
    deviation_ns: Mapped[float] = mapped_column(Float, nullable=False)
    deviation_ew: Mapped[float] = mapped_column(Float, nullable=False)
    dls: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    well: Mapped["Well"] = relationship("Well", back_populates="trajectory_points")
