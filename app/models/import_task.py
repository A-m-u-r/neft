import uuid
from datetime import datetime
from typing import Optional, Any
from sqlalchemy import String, Integer, DateTime, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ImportTask(Base):
    """Задача на асинхронную обработку импорта Excel."""
    __tablename__ = "import_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    well_pad_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("well_pads.id", ondelete="SET NULL"), nullable=True
    )
    well_pad_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Статус задания: "pending", "processing", "completed", "completed_with_errors", "failed"
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    
    total_sheets: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successful_sheets: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_sheets: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Полный диагностический отчёт в формате JSON
    diagnostic_report: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
