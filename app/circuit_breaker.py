import time
import asyncio
import logging
from enum import Enum
from typing import Callable, Any

logger = logging.getLogger("circuit_breaker")

class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

class CircuitBreakerOpenException(Exception):
    pass

class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 10.0,
        call_timeout: float = 0.02, # 20ms max latency budget for Redis
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.call_timeout = call_timeout

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_state_change = time.monotonic()

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        now = time.monotonic()

        # Check state transitions
        if self.state == CircuitState.OPEN:
            if now - self.last_state_change > self.recovery_timeout:
                logger.info("Circuit breaker entering HALF_OPEN probe state.")
                self.state = CircuitState.HALF_OPEN
            else:
                raise CircuitBreakerOpenException("Circuit open: Redis temporarily bypassed")

        try:
            # Enforce hard call deadline
            result = await asyncio.wait_for(func(*args, **kwargs), timeout=self.call_timeout)
            
            if self.state == CircuitState.HALF_OPEN:
                logger.info("Probe succeeded. Resetting circuit breaker to CLOSED.")
                self.state = CircuitState.CLOSED
                self.failure_count = 0

            return result

        except Exception as exc:
            self._handle_failure(exc)
            raise

    def _handle_failure(self, exc: Exception):
        self.failure_count += 1
        logger.warning(f"Circuit Breaker recorded failure ({self.failure_count}/{self.failure_threshold}): {exc}")

        if self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN) and self.failure_count >= self.failure_threshold:
            logger.error("Failure threshold reached. Opening circuit breaker (Fail-Open active).")
            self.state = CircuitState.OPEN
            self.last_state_change = time.monotonic()