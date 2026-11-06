import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class WellPad(Base):
    """Модель кустовой площадки."""
    __tablename__ = "well_pads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    field_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    crs: Mapped[Optional[str]] = mapped_column(String(100), default="UNKNOWN", nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    wells: Mapped[List["Well"]] = relationship(
        "Well",
        back_populates="well_pad",
        cascade="all, delete-orphan",
        order_by="Well.name",
        lazy="selectin",
    )
