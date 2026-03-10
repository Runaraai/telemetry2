"""In-memory rate limiter for protecting high-throughput endpoints.

Implements a sliding window rate limiter that tracks request counts
per client (identified by IP or run_id). Designed for the remote_write
endpoint which can receive 200+ req/s at scale.

Features:
- Sliding window algorithm (more accurate than fixed window)
- Per-client limiting (by IP or custom key)
- Configurable burst allowance
- Automatic cleanup of stale entries

Usage:
    limiter = RateLimiter(requests_per_second=50, burst=100)
    
    @app.post("/api/endpoint")
    async def endpoint(request: Request):
        client_ip = request.client.host
        if not await limiter.allow(client_ip):
            raise HTTPException(429, "Rate limit exceeded")
        # ... handle request
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class RateLimiterStats:
    """Statistics for monitoring rate limiter behavior."""
    total_requests: int = 0
    allowed_requests: int = 0
    rejected_requests: int = 0
    unique_clients: int = 0


@dataclass
class SlidingWindowEntry:
    """Tracks request counts for a sliding window."""
    current_window_count: int = 0
    previous_window_count: int = 0
    window_start: float = 0.0


class RateLimiter:
    """Sliding window rate limiter with burst support.
    
    Uses a sliding window algorithm that interpolates between the current
    and previous window to provide smoother rate limiting than fixed windows.
    
    Attributes:
        requests_per_second: Base rate limit per client
        burst: Maximum requests allowed in a burst (sliding window size)
        window_size: Size of each window in seconds (default 1.0)
        cleanup_interval: How often to clean up stale entries (seconds)
    """
    
    def __init__(
        self,
        requests_per_second: float = 50.0,
        burst: int = 100,
        window_size: float = 1.0,
        cleanup_interval: float = 60.0,
    ):
        self.requests_per_second = requests_per_second
        self.burst = burst
        self.window_size = window_size
        self.cleanup_interval = cleanup_interval
        
        self._entries: Dict[str, SlidingWindowEntry] = defaultdict(SlidingWindowEntry)
        self._lock = asyncio.Lock()
        self._stats = RateLimiterStats()
        self._last_cleanup = time.monotonic()
    
    @property
    def stats(self) -> RateLimiterStats:
        """Get current statistics."""
        return self._stats
    
    def _get_window_key(self, now: float) -> float:
        """Get the start time of the current window."""
        return (now // self.window_size) * self.window_size
    
    def _calculate_rate(self, entry: SlidingWindowEntry, now: float) -> float:
        """Calculate the current request rate using sliding window interpolation."""
        window_start = self._get_window_key(now)
        
        # If we're in a new window, rotate counts
        if entry.window_start < window_start:
            if entry.window_start == window_start - self.window_size:
                # Previous window is the one we were tracking
                entry.previous_window_count = entry.current_window_count
            else:
                # Gap in requests, reset previous count
                entry.previous_window_count = 0
            entry.current_window_count = 0
            entry.window_start = window_start
        
        # Calculate position within current window (0.0 to 1.0)
        window_progress = (now - window_start) / self.window_size
        
        # Sliding window: weighted average of current and previous window
        # As we progress through the window, we weight current more heavily
        estimated_count = (
            entry.current_window_count +
            entry.previous_window_count * (1.0 - window_progress)
        )
        
        return estimated_count
    
    async def allow(self, client_key: str) -> Tuple[bool, Optional[float]]:
        """Check if a request from this client should be allowed.
        
        Args:
            client_key: Identifier for the client (IP, run_id, etc.)
        
        Returns:
            Tuple of (allowed: bool, retry_after: Optional[float])
            If not allowed, retry_after indicates seconds to wait.
        """
        now = time.monotonic()
        
        async with self._lock:
            self._stats.total_requests += 1
            
            # Periodic cleanup
            if now - self._last_cleanup > self.cleanup_interval:
                await self._cleanup(now)
            
            entry = self._entries[client_key]
            current_rate = self._calculate_rate(entry, now)
            
            # Check against burst limit
            if current_rate >= self.burst:
                self._stats.rejected_requests += 1
                # Calculate retry_after based on how long until rate drops
                retry_after = self.window_size * (current_rate - self.burst + 1) / self.burst
                logger.debug(
                    "Rate limit exceeded for %s: %.1f requests (limit: %d)",
                    client_key, current_rate, self.burst
                )
                return False, retry_after
            
            # Allow request and increment counter
            entry.current_window_count += 1
            self._stats.allowed_requests += 1
            
            return True, None
    
    async def _cleanup(self, now: float) -> None:
        """Remove stale entries to prevent memory growth."""
        stale_threshold = now - (self.window_size * 2)
        stale_keys = [
            key for key, entry in self._entries.items()
            if entry.window_start < stale_threshold
        ]
        
        for key in stale_keys:
            del self._entries[key]
        
        self._stats.unique_clients = len(self._entries)
        self._last_cleanup = now
        
        if stale_keys:
            logger.debug("Rate limiter cleanup: removed %d stale entries", len(stale_keys))
    
    def reset(self) -> None:
        """Reset all rate limiting state."""
        self._entries.clear()
        self._stats = RateLimiterStats()
        logger.info("Rate limiter reset")


# Global rate limiter instances for different endpoints
# remote_write: 200 req/s with burst of 400 (2 seconds worth)
remote_write_limiter = RateLimiter(
    requests_per_second=200.0,
    burst=400,
    window_size=1.0,
)

# General API: 100 req/s with burst of 200
api_limiter = RateLimiter(
    requests_per_second=100.0,
    burst=200,
    window_size=1.0,
)



