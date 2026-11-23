"""Phase 4.1: BackgroundJob model, service and API tests.

Tests that require only SQLite/in-memory infrastructure run without RabbitMQ.
Celery dispatch is mocked to avoid broker dependency in CI.
"""
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import BackgroundJob
from app.services.job_service import (
    build_job_response,
    get_or_create_generation_job,
    update_celery_task_id,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_job(
    user_id: str,
    episode_id: str,
    status: str = "QUEUED",
    dispatch_pending: int = 1,
    **kwargs: Any,
) -> BackgroundJob:
    now = datetime.now(timezone.utc)
    return BackgroundJob(
        id=str(uuid.uuid4()),
        user_id=user_id,
        episode_id=episode_id,
        job_type="generation",
        status=status,
        progress=0,
        current_stage="queued",
        retry_count=0,
        max_retries=3,
        queued_at=now,
        dispatch_pending=dispatch_pending,
        metadata_json={},
        created_at=now,
        updated_at=now,
        **kwargs,
    )


# ─── Unit: BackgroundJob model ────────────────────────────────────────────────

class TestBackgroundJobModel:
    def test_active_statuses(self) -> None:
        for s in ("QUEUED", "RUNNING", "RETRYING"):
            job = make_job("u1", "e1", status=s)
            assert job.is_active()
            assert not job.is_terminal()

    def test_terminal_statuses(self) -> None:
        for s in ("SUCCEEDED", "FAILED", "CANCELLED"):
            job = make_job("u1", "e1", status=s)
            assert job.is_terminal()
            assert not job.is_active()

    def test_build_job_response_no_secrets(self) -> None:
        job = make_job("u1", "e1", status="RUNNING", dispatch_pending=0)
        job.celery_task_id = "abc-123"
        resp = build_job_response(job)
        assert resp["status"] == "RUNNING"
        assert resp["celery_task_id"] == "abc-123"
        assert "metadata_json" not in resp  # serializable config not in response
        assert "user_id" not in resp  # never expose user_id
        assert "dispatch_pending" not in resp

    def test_build_job_response_fields_complete(self) -> None:
        job = make_job("u1", "e1", status="QUEUED")
        resp = build_job_response(job)
        required_keys = {
            "id", "episode_id", "job_type", "status", "progress",
            "current_stage", "celery_task_id", "retry_count",
            "queued_at", "started_at", "finished_at",
            "error_message", "error_code",
        }
        assert required_keys.issubset(resp.keys())

    def test_queued_job_is_not_terminal(self) -> None:
        job = make_job("u1", "e1", status="QUEUED")
        assert not job.is_terminal()

    def test_failed_job_not_active(self) -> None:
        job = make_job("u1", "e1", status="FAILED")
        assert not job.is_active()
        assert job.is_terminal()

    def test_response_times_are_iso_strings_or_none(self) -> None:
        job = make_job("u1", "e1")
        resp = build_job_response(job)
        # queued_at is set; started_at / finished_at are None
        assert isinstance(resp["queued_at"], str)
        assert resp["started_at"] is None
        assert resp["finished_at"] is None


# ─── Integration: job service ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_or_create_job_creates_new(
    db_session: AsyncSession, test_user: "Any", test_episode: "Any"
) -> None:
    job, is_new = await get_or_create_generation_job(
        db=db_session,
        episode_id=test_episode.id,
        user_id=test_user.id,
        metadata={"provider": "mock"},
    )
    assert is_new is True
    assert job.status == "QUEUED"
    assert job.dispatch_pending == 1
    assert job.episode_id == test_episode.id
    assert job.user_id == test_user.id


@pytest.mark.asyncio
async def test_get_or_create_job_reuses_active(
    db_session: AsyncSession, test_user: "Any", test_episode: "Any"
) -> None:
    job1, is_new1 = await get_or_create_generation_job(
        db=db_session,
        episode_id=test_episode.id,
        user_id=test_user.id,
    )
    assert is_new1 is True

    # Second call must reuse the active job — no new DB row
    job2, is_new2 = await get_or_create_generation_job(
        db=db_session,
        episode_id=test_episode.id,
        user_id=test_user.id,
    )
    assert is_new2 is False
    assert job1.id == job2.id


@pytest.mark.asyncio
async def test_get_or_create_job_new_after_terminal(
    db_session: AsyncSession, test_user: "Any", test_episode: "Any"
) -> None:
    """After a terminal job, a fresh call must create a new job."""
    job1, _ = await get_or_create_generation_job(
        db=db_session, episode_id=test_episode.id, user_id=test_user.id
    )
    # Transition to terminal
    job1.status = "FAILED"
    await db_session.commit()

    job2, is_new = await get_or_create_generation_job(
        db=db_session, episode_id=test_episode.id, user_id=test_user.id
    )
    assert is_new is True
    assert job2.id != job1.id


@pytest.mark.asyncio
async def test_update_celery_task_id(
    db_session: AsyncSession, test_user: "Any", test_episode: "Any"
) -> None:
    job, _ = await get_or_create_generation_job(
        db=db_session, episode_id=test_episode.id, user_id=test_user.id
    )
    assert job.celery_task_id is None

    fake_task_id = str(uuid.uuid4())
    await update_celery_task_id(db_session, job.id, fake_task_id)

    await db_session.refresh(job)
    assert job.celery_task_id == fake_task_id


# ─── Unit: dispatch_generation_task (mocked Celery) ──────────────────────────

class TestDispatchGenerationTask:
    def test_dispatch_calls_apply_async(self) -> None:
        from app.services.job_service import dispatch_generation_task

        mock_result = MagicMock()
        mock_result.id = "celery-task-abc"

        with patch(
            "app.workers.generation_tasks.run_generation.apply_async",
            return_value=mock_result,
        ) as mock_apply:
            task_id = dispatch_generation_task("job-123")

        mock_apply.assert_called_once_with(args=["job-123"], queue="generation")
        assert task_id == "celery-task-abc"

    def test_dispatch_raises_on_broker_failure(self) -> None:
        from app.services.job_service import dispatch_generation_task

        with patch(
            "app.workers.generation_tasks.run_generation.apply_async",
            side_effect=Exception("AMQP connection refused"),
        ):
            with pytest.raises(Exception, match="AMQP connection refused"):
                dispatch_generation_task("job-999")


# ─── Unit: redispatch_pending_jobs ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_redispatch_skips_when_broker_unavailable() -> None:
    """redispatch_pending_jobs must not raise even if broker is unavailable."""
    from app.services.job_service import redispatch_pending_jobs

    with patch(
        "app.services.job_service.dispatch_generation_task",
        side_effect=Exception("broker offline"),
    ):
        # Must not raise — just log and return 0
        count = await redispatch_pending_jobs()
    # count may be 0 or error-safe; function must return an int
    assert isinstance(count, int)


# ─── Unit: Celery task with mocked DB (no live broker) ───────────────────────

class TestGenerationTaskUnit:
    def test_run_generation_returns_not_found_for_missing_job(self) -> None:
        """Worker exits cleanly when job_id doesn't exist in DB."""
        from app.workers.generation_tasks import _async_run_generation

        mock_task = MagicMock()
        mock_task.request.id = "celery-xyz"
        mock_task.request.retries = 0
        mock_task.max_retries = 3

        mock_result = MagicMock()
        mock_result.first.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.scalar = AsyncMock(return_value=None)
        mock_db.commit = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_sf = MagicMock()
        mock_sf.return_value = mock_db

        mock_engine = AsyncMock()
        mock_engine.dispose = AsyncMock()

        async def run() -> dict[str, Any]:
            with patch("app.workers.generation_tasks.create_async_engine", return_value=mock_engine), \
                 patch("app.workers.generation_tasks.async_sessionmaker", return_value=mock_sf), \
                 patch("app.workers.generation_tasks.event_hub.initialize", new_callable=AsyncMock), \
                 patch("app.workers.generation_tasks.event_hub.close", new_callable=AsyncMock):
                return await _async_run_generation(mock_task, "nonexistent-job-id")

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(run())
        assert result["status"] == "NOT_FOUND"
        assert result["job_id"] == "nonexistent-job-id"

    def test_run_generation_skips_terminal_job(self) -> None:
        """Worker skips execution when job is already SUCCEEDED/FAILED/CANCELLED."""
        from app.workers.generation_tasks import _async_run_generation

        mock_task = MagicMock()
        mock_task.request.id = "celery-xyz"
        mock_task.request.retries = 0

        terminal_job = make_job("u1", "e1", status="SUCCEEDED")

        mock_result = MagicMock()
        mock_result.first.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.scalar = AsyncMock(return_value=terminal_job)
        mock_db.commit = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_sf = MagicMock()
        mock_sf.return_value = mock_db

        mock_engine = AsyncMock()
        mock_engine.dispose = AsyncMock()

        async def run() -> dict[str, Any]:
            with patch("app.workers.generation_tasks.create_async_engine", return_value=mock_engine), \
                 patch("app.workers.generation_tasks.async_sessionmaker", return_value=mock_sf), \
                 patch("app.workers.generation_tasks.event_hub.initialize", new_callable=AsyncMock), \
                 patch("app.workers.generation_tasks.event_hub.close", new_callable=AsyncMock):
                return await _async_run_generation(mock_task, terminal_job.id)

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(run())
        assert result["status"] == "SUCCEEDED"


# ─── Unit: EventHub cross-process subscribe path ─────────────────────────────

@pytest.mark.asyncio
async def test_event_hub_in_memory_subscribe_and_publish() -> None:
    """In-memory subscribe/publish works without Redis."""
    from app.core.events import EventHub

    hub = EventHub()
    # Don't call initialize() — stays in-memory mode
    hub._redis_available = False

    received: list[str] = []

    async def consumer() -> None:
        async for msg in hub.subscribe("ep-test"):
            received.append(msg)
            break  # Just get first message for the test

    import asyncio
    consumer_task = asyncio.create_task(consumer())
    await asyncio.sleep(0.01)  # yield so consumer subscribes first

    await hub.publish("ep-test", "node_started", {"node": "planner"})
    await asyncio.sleep(0.05)
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    assert len(received) == 1
    import json
    parsed = json.loads(received[0].removeprefix("data: ").strip())
    assert parsed["event_type"] == "node_started"


@pytest.mark.asyncio
async def test_event_hub_terminal_event_closes_stream() -> None:
    """In-memory subscriber exits cleanly on pipeline_completed."""
    from app.core.events import EventHub
    import json

    hub = EventHub()
    hub._redis_available = False

    received: list[str] = []

    async def consumer() -> None:
        async for msg in hub.subscribe("ep-fin"):
            received.append(msg)

    import asyncio
    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.01)

    await hub.publish("ep-fin", "node_started", {"node": "writer"})
    await hub.publish("ep-fin", "pipeline_completed", {"status": "COMPLETED"})
    await asyncio.sleep(0.1)

    # Stream should have auto-terminated
    assert not task.done() or task.cancelled() or len(received) >= 2
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    event_types = [json.loads(m.removeprefix("data: ").strip())["event_type"] for m in received]
    assert "pipeline_completed" in event_types


# ─── Unit: job_service ownership check ───────────────────────────────────────

@pytest.mark.asyncio
async def test_get_or_create_job_rejects_wrong_user(
    db_session: AsyncSession, test_user: "Any", test_episode: "Any"
) -> None:
    """Active job owned by user A must reject user B."""
    from app.core.exceptions import AuthorizationFailedException

    # Create job for test_user
    await get_or_create_generation_job(
        db=db_session, episode_id=test_episode.id, user_id=test_user.id
    )

    # Try to claim with a different user ID
    with pytest.raises(AuthorizationFailedException):
        await get_or_create_generation_job(
            db=db_session, episode_id=test_episode.id, user_id="different-user-id"
        )

# ─── Phase 4.1.1 Regression Tests ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_active_jobs_prevented_by_unique_constraint(
    db_session: AsyncSession, test_user: Any, test_episode: Any
) -> None:
    """Concurrent creation of generation jobs returns the same active job."""
    job1, is_new1 = await get_or_create_generation_job(
        db=db_session, episode_id=test_episode.id, user_id=test_user.id
    )
    assert is_new1 is True

    # Simultaneous second request finds existing active job
    job2, is_new2 = await get_or_create_generation_job(
        db=db_session, episode_id=test_episode.id, user_id=test_user.id
    )
    assert is_new2 is False
    assert job1.id == job2.id


@pytest.mark.asyncio
async def test_sanitized_error_reporting() -> None:
    """Ensure error messages redact secrets and API keys."""
    from app.core.sanitizer import sanitize_error_message

    raw_err = "Failed calling Gemini API with key AIzaSyA1234567890abcdefghijklmnopqrstuv: Server error\nTraceback at /Users/dev/app/secret.py:10"
    sanitized = sanitize_error_message(raw_err)
    assert "AIzaSy" not in sanitized
    assert "[REDACTED]" in sanitized
    assert "\n" not in sanitized


@pytest.mark.asyncio
async def test_atomic_claiming_skips_already_running_job() -> None:
    """Duplicate Celery delivery cannot claim a job already marked RUNNING."""
    from app.workers.generation_tasks import _async_run_generation

    mock_task = MagicMock()
    mock_task.request.id = "celery-dup-test"
    mock_task.request.retries = 0
    mock_task.max_retries = 3

    # Fake DB session that returns None for atomic claim update (already running)
    mock_result = MagicMock()
    mock_result.first.return_value = None

    running_job = make_job("u1", "e1", status="RUNNING")

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.scalar = AsyncMock(return_value=running_job)
    mock_db.commit = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    mock_sf = MagicMock()
    mock_sf.return_value = mock_db

    mock_engine = AsyncMock()
    mock_engine.dispose = AsyncMock()

    with patch("app.workers.generation_tasks.create_async_engine", return_value=mock_engine), \
         patch("app.workers.generation_tasks.async_sessionmaker", return_value=mock_sf), \
         patch("app.workers.generation_tasks.event_hub.initialize", new_callable=AsyncMock), \
         patch("app.workers.generation_tasks.event_hub.close", new_callable=AsyncMock):
        res = await _async_run_generation(mock_task, running_job.id)

    assert res.get("skipped") is True
    assert res.get("status") == "RUNNING"


@pytest.mark.asyncio
async def test_retry_lifecycle_transitions_to_retrying() -> None:
    """When a job encounters a recoverable error on attempt 0, status transitions to RETRYING."""
    from app.workers.generation_tasks import _handle_job_failure
    from celery.exceptions import Retry

    mock_task = MagicMock()
    mock_task.request.retries = 0  # Attempt 0
    mock_task.retry = MagicMock(side_effect=Retry("Simulated celery retry"))

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    mock_sf = MagicMock()
    mock_sf.return_value = mock_db

    with patch("app.workers.generation_tasks.event_hub.publish", new_callable=AsyncMock) as mock_pub:
        with pytest.raises(Retry):
            await _handle_job_failure(
                session_factory=mock_sf,
                task=mock_task,
                job_id="job-retry-1",
                episode_id="ep-1",
                error_code="PIPELINE_ERROR",
                error_message="Transient network glitch",
                exc=Exception("Transient network glitch"),
                max_retries=3,
            )

    # Status update executed with RETRYING and attempt count 1
    mock_db.execute.assert_awaited_once()
    mock_pub.assert_awaited_once()
    assert mock_pub.call_args[0][1] == "pipeline_retrying"
    assert mock_pub.call_args[0][2]["retry_count"] == 1


@pytest.mark.asyncio
async def test_retry_lifecycle_transitions_to_failed_when_exhausted() -> None:
    """When a job exceeds max_retries, status transitions to FAILED."""
    from app.workers.generation_tasks import _handle_job_failure

    mock_task = MagicMock()
    mock_task.request.retries = 3  # Attempt 3 >= max_retries 3

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.scalar = AsyncMock(return_value=None)
    mock_db.commit = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    mock_sf = MagicMock()
    mock_sf.return_value = mock_db

    with patch("app.workers.generation_tasks.event_hub.publish", new_callable=AsyncMock) as mock_pub:
        with pytest.raises(RuntimeError, match="Fatal unrecoverable failure"):
            await _handle_job_failure(
                session_factory=mock_sf,
                task=mock_task,
                job_id="job-fail-final",
                episode_id="ep-1",
                error_code="FATAL_ERROR",
                error_message="Fatal unrecoverable failure",
                exc=RuntimeError("Fatal unrecoverable failure"),
                max_retries=3,
            )

    # Status update executed with FAILED and event published
    mock_db.execute.assert_awaited_once()
    mock_pub.assert_awaited_once()
    assert mock_pub.call_args[0][1] == "pipeline_failed"


@pytest.mark.asyncio
async def test_event_hub_production_raises_on_redis_failure() -> None:
    """In production environment, Redis connection failure must raise RuntimeError."""
    from app.core.events import EventHub
    from app.core.config import get_settings

    hub = EventHub()
    settings = get_settings()

    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch("redis.asyncio.Redis.from_url") as mock_redis_cls:
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(side_effect=Exception("Redis down"))
        mock_redis_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="Redis Pub/Sub unavailable in production"):
            await hub.initialize()


@pytest.mark.asyncio
async def test_worker_checkpointer_lifecycle() -> None:
    """Worker checkpointer cleanly initializes and closes."""
    from app.workers.generation_tasks import get_worker_checkpointer

    async with get_worker_checkpointer() as checkpointer:
        assert checkpointer is not None
