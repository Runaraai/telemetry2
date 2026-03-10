"""Circuit breaker pattern for protecting against cascading failures.

Implements a circuit breaker that tracks failure rates and temporarily
blocks requests when the failure threshold is exceeded. This prevents
overwhelming a failing service and allows time for recovery.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Failure threshold exceeded, requests are blocked
- HALF_OPEN: Testing if service has recovered

Usage:
    breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
    
    async with breaker:
        await some_risky_operation()
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Blocking requests
    HALF_OPEN = "half_open" # Testing recovery


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open and blocking requests."""
    
    def __init__(self, breaker_name: str, retry_after: float):
        self.breaker_name = breaker_name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker '{breaker_name}' is open. Retry after {retry_after:.1f}s"
        )


@dataclass
class CircuitBreakerStats:
    """Statistics for monitoring circuit breaker behavior."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rejected_requests: int = 0  # Requests blocked by open circuit
    state_changes: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None


@dataclass
class CircuitBreaker:
    """Async circuit breaker for protecting against cascading failures.
    
    Attributes:
        name: Identifier for this breaker (for logging/monitoring)
        failure_threshold: Number of consecutive failures before opening
        success_threshold: Number of consecutive successes in half-open to close
        recovery_timeout: Seconds to wait before trying again (half-open)
        half_open_max_calls: Max concurrent calls allowed in half-open state
    """
    name: str = "default"
    failure_threshold: int = 5
    success_threshold: int = 2
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 1
    
    # Internal state
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _half_open_calls: int = field(default=0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _stats: CircuitBreakerStats = field(default_factory=CircuitBreakerStats, init=False)
    
    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state
    
    @property
    def stats(self) -> CircuitBreakerStats:
        """Get current statistics."""
        return self._stats
    
    @property
    def is_closed(self) -> bool:
        return self._state == CircuitState.CLOSED
    
    @property
    def is_open(self) -> bool:
        return self._state == CircuitState.OPEN
    
    @property
    def is_half_open(self) -> bool:
        return self._state == CircuitState.HALF_OPEN
    
    def _time_since_last_failure(self) -> float:
        """Seconds since last recorded failure."""
        if self._last_failure_time == 0:
            return float("inf")
        return time.monotonic() - self._last_failure_time
    
    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has passed to try recovery."""
        return self._time_since_last_failure() >= self.recovery_timeout
    
    async def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state with logging."""
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            self._stats.state_changes += 1
            logger.warning(
                "Circuit breaker '%s' state change: %s -> %s",
                self.name, old_state.value, new_state.value
            )
            
            if new_state == CircuitState.HALF_OPEN:
                self._half_open_calls = 0
                self._success_count = 0
            elif new_state == CircuitState.CLOSED:
                self._failure_count = 0
    
    async def _record_success(self) -> None:
        """Record a successful call."""
        async with self._lock:
            self._stats.total_requests += 1
            self._stats.successful_requests += 1
            self._stats.last_success_time = time.monotonic()
            
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                self._half_open_calls -= 1
                
                if self._success_count >= self.success_threshold:
                    await self._transition_to(CircuitState.CLOSED)
                    logger.info(
                        "Circuit breaker '%s' recovered after %d successful calls",
                        self.name, self._success_count
                    )
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0
    
    async def _record_failure(self, exc: Exception) -> None:
        """Record a failed call."""
        async with self._lock:
            self._stats.total_requests += 1
            self._stats.failed_requests += 1
            self._stats.last_failure_time = time.monotonic()
            self._last_failure_time = time.monotonic()
            
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_calls -= 1
                # Any failure in half-open reopens the circuit
                await self._transition_to(CircuitState.OPEN)
                logger.warning(
                    "Circuit breaker '%s' reopened due to failure in half-open: %s",
                    self.name, str(exc)
                )
            elif self._state == CircuitState.CLOSED:
                self._failure_count += 1
                
                if self._failure_count >= self.failure_threshold:
                    await self._transition_to(CircuitState.OPEN)
                    logger.error(
                        "Circuit breaker '%s' opened after %d consecutive failures",
                        self.name, self._failure_count
                    )
    
    async def _check_state(self) -> None:
        """Check and potentially update circuit state before a call."""
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_recovery():
                    await self._transition_to(CircuitState.HALF_OPEN)
    
    async def _can_execute(self) -> bool:
        """Check if a call can be executed."""
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            
            if self._state == CircuitState.OPEN:
                if self._should_attempt_recovery():
                    await self._transition_to(CircuitState.HALF_OPEN)
                    self._half_open_calls += 1
                    return True
                
                self._stats.rejected_requests += 1
                return False
            
            # Half-open: allow limited concurrent calls
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                
                self._stats.rejected_requests += 1
                return False
            
            return False
    
    async def __aenter__(self) -> "CircuitBreaker":
        """Context manager entry - check if call is allowed."""
        await self._check_state()
        
        if not await self._can_execute():
            retry_after = self.recovery_timeout - self._time_since_last_failure()
            raise CircuitBreakerOpen(self.name, max(0, retry_after))
        
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context manager exit - record result."""
        if exc_val is None:
            await self._record_success()
        else:
            await self._record_failure(exc_val)
        
        # Don't suppress exceptions
        return False
    
    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        logger.info("Circuit breaker '%s' manually reset", self.name)


# Global circuit breaker instances for different services
db_write_breaker = CircuitBreaker(
    name="db_write",
    failure_threshold=5,      # Open after 5 consecutive failures
    success_threshold=2,      # Close after 2 successes in half-open
    recovery_timeout=30.0,    # Wait 30s before testing recovery
    half_open_max_calls=1,    # Allow 1 test call in half-open
)

db_read_breaker = CircuitBreaker(
    name="db_read",
    failure_threshold=10,     # More tolerant for reads
    success_threshold=3,
    recovery_timeout=15.0,    # Faster recovery for reads
    half_open_max_calls=3,
)



