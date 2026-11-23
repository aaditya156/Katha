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
    """Redis Pub/Sub event hub for cross-process SSE delivery."""

    def __init__(self) -> None:
        self.subscribers: dict[str, list[asyncio.Queue[str]]] = {}
        self._redis: Redis | None = None
        self._redis_available: bool = False

    async def initialize(self) -> None:
        """Connect to Redis; fall back to in-memory only if unavailable."""
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
        """Publish an event to all subscribers of an episode."""
        event_data = {
            "episode_id": episode_id,
            "event_type": event_type,
            "node": node,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        serialized = json.dumps(event_data)

        # In-memory delivery (for same-process subscribers in dev/test)
        if episode_id in self.subscribers:
            for queue in self.subscribers[episode_id]:
                await queue.put(serialized)

        # Redis Pub/Sub delivery (cross-process — workers publish here)
        if self._redis_available and self._redis:
            try:
                await self._redis.publish(f"episode:{episode_id}", serialized)
            except Exception as exc:
                logger.warning(f"Failed to publish event to Redis: {exc}")

    async def subscribe(self, episode_id: str) -> AsyncGenerator[str, None]:
        """Subscribe to episode events as an SSE stream.

        When Redis is available: uses Redis Pub/Sub (works across processes).
        When Redis is unavailable: uses in-memory queue (dev/test only).
        """
        TERMINAL_EVENTS = frozenset({"pipeline_completed", "pipeline_failed"})

        if self._redis_available and self._redis:
            # Real Redis Pub/Sub — cross-process safe
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
            # In-memory fallback — dev/test only (breaks across processes)
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
