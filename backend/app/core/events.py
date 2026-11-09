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
    """Hybrid Redis and In-Memory event hub for streaming pipeline progress via SSE."""

    def __init__(self) -> None:
        self.subscribers: dict[str, list[asyncio.Queue[str]]] = {}
        self._redis: Redis | None = None
        self._redis_available: bool = False

    async def initialize(self) -> None:
        """Attempt connection to Redis; fall back to in-memory event bus if unavailable."""
        try:
            self._redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
            await self._redis.ping()
            self._redis_available = True
            logger.info("Connected to Redis Pub/Sub for SSE event streaming.")
        except Exception as exc:
            logger.info(f"Redis not available ({exc}); using in-memory EventHub.")
            self._redis_available = False

    async def publish(
        self,
        episode_id: str,
        event_type: str,
        payload: dict[str, Any],
        node: str | None = None,
    ) -> None:
        """Publish an event to subscribers of an episode."""
        event_data = {
            "episode_id": episode_id,
            "event_type": event_type,
            "node": node,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        serialized = json.dumps(event_data)

        # 1. In-memory delivery
        if episode_id in self.subscribers:
            for queue in self.subscribers[episode_id]:
                await queue.put(serialized)

        # 2. Redis delivery if active
        if self._redis_available and self._redis:
            try:
                await self._redis.publish(f"episode:{episode_id}", serialized)
            except Exception as exc:
                logger.warning(f"Failed to publish event to Redis: {exc}")

    async def subscribe(self, episode_id: str) -> AsyncGenerator[str, None]:
        """Subscribe to live events for a given episode as an SSE stream."""
        queue: asyncio.Queue[str] = asyncio.Queue()
        if episode_id not in self.subscribers:
            self.subscribers[episode_id] = []
        self.subscribers[episode_id].append(queue)

        try:
            while True:
                msg = await queue.get()
                yield f"data: {msg}\n\n"
                parsed = json.loads(msg)
                # Terminate stream on terminal events
                if parsed.get("event_type") in ("pipeline_completed", "pipeline_failed"):
                    break
        finally:
            if episode_id in self.subscribers and queue in self.subscribers[episode_id]:
                self.subscribers[episode_id].remove(queue)
                if not self.subscribers[episode_id]:
                    del self.subscribers[episode_id]


event_hub = EventHub()

