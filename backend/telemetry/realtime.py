"""Real-time metrics broadcasting utilities.

Provides a pub/sub broker for live GPU metrics streaming to WebSocket clients.
Supports both in-memory queues (single instance) and Redis pub/sub (multi-instance).

When Redis is configured (via TELEMETRY_REDIS_URL), the broker uses Redis pub/sub
to distribute messages across all backend instances, enabling horizontal scaling
and persistence across restarts.
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Dict, Iterable, MutableMapping, Optional, Set
from uuid import UUID

logger = logging.getLogger(__name__)

# Queue settings for backpressure control
QUEUE_MAX_SIZE = 500  # Maximum messages before dropping


class BaseBroker(ABC):
    """Abstract base class for metrics brokers."""
    
    @abstractmethod
    async def register(self, run_id: UUID) -> asyncio.Queue:
        """Register a new subscriber queue for the given run."""
        pass
    
    @abstractmethod
    async def unregister(self, run_id: UUID, queue: asyncio.Queue) -> None:
        """Remove subscriber queue from the broker."""
        pass
    
    @abstractmethod
    async def publish(self, run_id: UUID, payload: Dict[str, Any]) -> None:
        """Publish a metrics payload to all subscribers."""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""
        pass


class InMemoryBroker(BaseBroker):
    """In-memory broker using asyncio.Queue for single-instance deployments.
    
    Features:
    - Bounded queues with configurable max size
    - Drop-oldest backpressure when queue is full
    - Zero external dependencies
    
    Limitations:
    - State lost on backend restart
    - No cross-instance communication
    """

    def __init__(self, queue_max_size: int = QUEUE_MAX_SIZE) -> None:
        self._subscribers: MutableMapping[UUID, Set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._queue_max_size = queue_max_size

    async def register(self, run_id: UUID) -> asyncio.Queue:
        """Register a new subscriber queue for the given run."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_max_size)
        async with self._lock:
            self._subscribers[run_id].add(queue)
        logger.debug("Registered live metrics subscriber for run %s", run_id)
        return queue

    async def unregister(self, run_id: UUID, queue: asyncio.Queue) -> None:
        """Remove subscriber queue from the broker."""
        async with self._lock:
            subscribers = self._subscribers.get(run_id)
            if subscribers and queue in subscribers:
                subscribers.remove(queue)
                if not subscribers:
                    self._subscribers.pop(run_id, None)
        logger.debug("Unregistered live metrics subscriber for run %s", run_id)

    async def publish(self, run_id: UUID, payload: Dict[str, Any]) -> None:
        """Publish a metrics payload to all subscribers with backpressure handling."""
        async with self._lock:
            subscribers: Iterable[asyncio.Queue] = list(self._subscribers.get(run_id, set()))

        if not subscribers:
            return

        for queue in subscribers:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("Dropping oldest message for run %s (queue full)", run_id)
                try:
                    # Drop oldest message and insert new one
                    queue.get_nowait()
                    queue.put_nowait(payload)
                except asyncio.QueueEmpty:
                    pass
    
    async def close(self) -> None:
        """Clean up resources."""
        async with self._lock:
            self._subscribers.clear()


class RedisBroker(BaseBroker):
    """Redis-backed broker for multi-instance deployments.
    
    Uses Redis pub/sub to distribute messages across all backend instances,
    enabling horizontal scaling and message persistence during restarts.
    
    Features:
    - Cross-instance message distribution
    - Survives backend restarts (subscribers reconnect)
    - Supports horizontal scaling of backend
    
    Note: Requires 'redis' package to be installed.
    """

    def __init__(
        self,
        redis_url: str,
        queue_max_size: int = QUEUE_MAX_SIZE,
    ) -> None:
        self._redis_url = redis_url
        self._queue_max_size = queue_max_size
        self._subscribers: MutableMapping[UUID, Set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._redis: Optional[Any] = None
        self._pubsub: Optional[Any] = None
        self._listener_task: Optional[asyncio.Task] = None
        self._channel_prefix = "omniference:metrics:"

    async def _ensure_connected(self) -> None:
        """Ensure Redis connection is established."""
        if self._redis is not None:
            return
        
        try:
            import redis.asyncio as aioredis
        except ImportError:
            logger.error("redis package not installed. Install with: pip install redis")
            raise RuntimeError("Redis broker requires 'redis' package")
        
        self._redis = await aioredis.from_url(
            self._redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        self._pubsub = self._redis.pubsub()
        logger.info("Connected to Redis for live metrics pub/sub")

    async def _start_listener(self) -> None:
        """Start background task to listen for Redis messages."""
        if self._listener_task is not None:
            return
        
        self._listener_task = asyncio.create_task(self._listen_loop())

    async def _listen_loop(self) -> None:
        """Background loop to receive messages from Redis."""
        try:
            while True:
                if self._pubsub is None:
                    await asyncio.sleep(0.1)
                    continue
                
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message is None:
                    continue
                
                channel = message.get("channel", "")
                if not channel.startswith(self._channel_prefix):
                    continue
                
                run_id_str = channel[len(self._channel_prefix):]
                try:
                    run_id = UUID(run_id_str)
                except ValueError:
                    continue
                
                data = message.get("data")
                if not data:
                    continue
                
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                
                # Distribute to local subscribers
                await self._distribute_locally(run_id, payload)
                
        except asyncio.CancelledError:
            logger.debug("Redis listener task cancelled")
        except Exception as e:
            logger.exception("Error in Redis listener loop: %s", e)

    async def _distribute_locally(self, run_id: UUID, payload: Dict[str, Any]) -> None:
        """Distribute message to local subscribers only."""
        async with self._lock:
            subscribers: Iterable[asyncio.Queue] = list(self._subscribers.get(run_id, set()))

        for queue in subscribers:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("Dropping oldest message for run %s (queue full)", run_id)
                try:
                    queue.get_nowait()
                    queue.put_nowait(payload)
                except asyncio.QueueEmpty:
                    pass

    async def register(self, run_id: UUID) -> asyncio.Queue:
        """Register a new subscriber queue for the given run."""
        await self._ensure_connected()
        await self._start_listener()
        
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_max_size)
        channel = f"{self._channel_prefix}{run_id}"
        
        async with self._lock:
            is_first = run_id not in self._subscribers or len(self._subscribers[run_id]) == 0
            self._subscribers[run_id].add(queue)
            
            if is_first and self._pubsub is not None:
                await self._pubsub.subscribe(channel)
                logger.debug("Subscribed to Redis channel for run %s", run_id)
        
        logger.debug("Registered live metrics subscriber for run %s", run_id)
        return queue

    async def unregister(self, run_id: UUID, queue: asyncio.Queue) -> None:
        """Remove subscriber queue from the broker."""
        channel = f"{self._channel_prefix}{run_id}"
        
        async with self._lock:
            subscribers = self._subscribers.get(run_id)
            if subscribers and queue in subscribers:
                subscribers.remove(queue)
                if not subscribers:
                    self._subscribers.pop(run_id, None)
                    if self._pubsub is not None:
                        await self._pubsub.unsubscribe(channel)
                        logger.debug("Unsubscribed from Redis channel for run %s", run_id)
        
        logger.debug("Unregistered live metrics subscriber for run %s", run_id)

    async def publish(self, run_id: UUID, payload: Dict[str, Any]) -> None:
        """Publish a metrics payload to Redis for distribution."""
        await self._ensure_connected()
        
        if self._redis is None:
            logger.warning("Redis not connected, falling back to local distribution")
            await self._distribute_locally(run_id, payload)
            return
        
        channel = f"{self._channel_prefix}{run_id}"
        message = json.dumps(payload)
        
        try:
            await self._redis.publish(channel, message)
        except Exception as e:
            logger.error("Failed to publish to Redis: %s", e)
            # Fall back to local distribution
            await self._distribute_locally(run_id, payload)

    async def close(self) -> None:
        """Clean up Redis resources."""
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        
        if self._pubsub is not None:
            await self._pubsub.close()
        
        if self._redis is not None:
            await self._redis.close()
        
        async with self._lock:
            self._subscribers.clear()
        
        logger.info("Redis broker closed")


def create_broker() -> BaseBroker:
    """Factory function to create the appropriate broker based on configuration.
    
    Returns RedisBroker if TELEMETRY_REDIS_URL is set, otherwise InMemoryBroker.
    """
    from .config import get_settings
    
    settings = get_settings()
    
    if settings.redis_url:
        logger.info("Using Redis broker for live metrics (URL: %s)", settings.redis_url)
        return RedisBroker(settings.redis_url)
    else:
        logger.info("Using in-memory broker for live metrics (Redis not configured)")
        return InMemoryBroker()


# Global broker instance - lazily initialized
_live_broker: Optional[BaseBroker] = None


def get_live_broker() -> BaseBroker:
    """Get or create the global live metrics broker."""
    global _live_broker
    if _live_broker is None:
        _live_broker = create_broker()
    return _live_broker


# For backwards compatibility, expose as module-level attribute
# This creates the broker on first import
class _LazyBroker:
    """Lazy wrapper for the live broker to defer initialization."""
    
    def __getattr__(self, name: str) -> Any:
        return getattr(get_live_broker(), name)


live_broker = _LazyBroker()

