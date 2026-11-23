"""BackgroundJob model — persistent Celery job tracking. PostgreSQL is source of truth."""
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin, UUIDMixin


class BackgroundJob(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "background_jobs"
    __table_args__ = (
        Index("ix_background_jobs_episode_active", "episode_id", "job_type", "status"),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    episode_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(String(50), nullable=False, default="generation")

    # Status: QUEUED → RUNNING → SUCCEEDED | FAILED | RETRYING | CANCELLED
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="QUEUED", index=True)

    # Celery reference — set after dispatch
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # Progress 0–100
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_stage: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Retry state
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    # Timing
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Safe error info (no stack traces or secrets)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Serializable provider/generation config
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Outbox flag: 1 = pending dispatch, 0 = dispatched
    dispatch_pending: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    TERMINAL_STATUSES: frozenset[str] = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})
    ACTIVE_STATUSES: frozenset[str] = frozenset({"QUEUED", "RUNNING", "RETRYING"})

    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES

    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL_STATUSES
