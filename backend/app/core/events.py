import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, AsyncGenerator
from redis.asyncio import Redis
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class EventHub:
    """Redis Pub/Sub event hub for cross-process SSE delivery with dev/test in-memory fallback."""

    def __init__(self) -> None:
        self.subscribers: dict[str, list[asyncio.Queue[str]]] = {}
        self._redis: Redis | None = None
        self._redis_available: bool = False

    async def initialize(self) -> None:
        """Connect to Redis. In production, Redis failure raises RuntimeError instead of silent fallback."""
        try:
            self._redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
            await self._redis.ping()
            self._redis_available = True
            logger.info("Connected to Redis Pub/Sub for SSE event streaming.")
        except Exception as exc:
            self._redis_available = False
            if settings.ENVIRONMENT == "production":
                logger.critical(f"FATAL: Redis Pub/Sub connection failed in production: {exc}", exc_info=True)
                raise RuntimeError(f"Redis Pub/Sub unavailable in production: {exc}") from exc
            logger.warning(f"Redis not available ({exc}); using in-memory EventHub fallback for dev/test.")

    async def close(self) -> None:
        """Cleanly close Redis connections."""
        if self._redis:
            try:
                await self._redis.aclose()
            except Exception as exc:
                logger.warning(f"Error closing Redis client: {exc}")
            finally:
                self._redis = None
                self._redis_available = False

    @property
    def is_healthy(self) -> bool:
        """Check if event delivery backend is healthy."""
        if settings.ENVIRONMENT == "production":
            return self._redis_available
        return True

    async def publish(
        self,
        episode_id: str,
        event_type: str,
        payload: dict[str, Any],
        node: str | None = None,
    ) -> None:
        """Publish an event to all subscribers of an episode."""
        event_data = {
            "episode_id": episode_id,
            "event_type": event_type,
            "node": node,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        serialized = json.dumps(event_data)

        # 1. In-memory delivery (for same-process subscribers in dev/test)
        if episode_id in self.subscribers:
            for queue in self.subscribers[episode_id]:
                await queue.put(serialized)

        # 2. Redis Pub/Sub delivery (cross-process delivery across FastAPI & Celery workers)
        if self._redis_available and self._redis:
            try:
                await self._redis.publish(f"episode:{episode_id}", serialized)
            except Exception as exc:
                if settings.ENVIRONMENT == "production":
                    logger.error(f"Failed to publish event to Redis in production: {exc}", exc_info=True)
                    raise
                logger.warning(f"Failed to publish event to Redis: {exc}")

    async def subscribe(self, episode_id: str) -> AsyncGenerator[str, None]:
        """Subscribe to episode events as an SSE stream."""
        TERMINAL_EVENTS = frozenset({"pipeline_completed", "pipeline_failed"})

        if self._redis_available and self._redis:
            pubsub = self._redis.pubsub()
            await pubsub.subscribe(f"episode:{episode_id}")
            try:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        data: str = message["data"]
                        yield f"data: {data}\n\n"
                        try:
                            parsed = json.loads(data)
                            if parsed.get("event_type") in TERMINAL_EVENTS:
                                break
                        except json.JSONDecodeError:
                            pass
            except Exception as exc:
                logger.error(f"Redis Pub/Sub stream error for episode {episode_id}: {exc}")
            finally:
                try:
                    await pubsub.unsubscribe(f"episode:{episode_id}")
                    await pubsub.aclose()
                except Exception:
                    pass
        else:
            queue: asyncio.Queue[str] = asyncio.Queue()
            if episode_id not in self.subscribers:
                self.subscribers[episode_id] = []
            self.subscribers[episode_id].append(queue)
            try:
                while True:
                    msg = await queue.get()
                    yield f"data: {msg}\n\n"
                    try:
                        parsed = json.loads(msg)
                        if parsed.get("event_type") in TERMINAL_EVENTS:
                            break
                    except json.JSONDecodeError:
                        pass
            finally:
                if episode_id in self.subscribers and queue in self.subscribers[episode_id]:
                    self.subscribers[episode_id].remove(queue)
                    if not self.subscribers[episode_id]:
                        del self.subscribers[episode_id]


event_hub = EventHub()
