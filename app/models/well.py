import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy import String, Float, Integer, ForeignKey, DateTime, func, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Well(Base):
    """Модель скважины кустовой площадки.
    
    Бизнес-правило (NEF-27):
    Если траектория повреждена:
    - скважина сохраняется;
    - карточка скважины остаётся доступной;
    - устьевые координаты сохраняются;
    - trajectory_status = "error";
    - trajectory_error_message = "Траектория не загружена: ошибка в исходных данных".
    """
    __tablename__ = "wells"
    __table_args__ = (
        UniqueConstraint("well_pad_id", "name", name="uq_well_pad_well_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    well_pad_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("well_pads.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    
    # Устьевые координаты (X, Y, Z / альтитуда)
    wellhead_x: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    wellhead_y: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    wellhead_z: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Статус траектории: "not_loaded", "loaded", "error"
    trajectory_status: Mapped[str] = mapped_column(String(50), default="not_loaded", nullable=False)
    trajectory_error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    points_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    well_pad: Mapped["WellPad"] = relationship("WellPad", back_populates="wells", lazy="selectin")
    trajectory_points: Mapped[List["TrajectoryPoint"]] = relationship(
        "TrajectoryPoint",
        back_populates="well",
        cascade="all, delete-orphan",
        order_by="TrajectoryPoint.point_index",
    )
