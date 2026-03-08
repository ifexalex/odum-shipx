"""Circuit breaker for external service calls.

Prevents cascade failures when Africa's Talking, Meta WhatsApp, or SES
are experiencing outages. Implements the CLOSED → OPEN → HALF_OPEN state
machine described in 00_CROSS_CUTTING_STANDARDS.md §5.

Usage:
    from shared.circuit_breaker import get_circuit_breaker

    cb = get_circuit_breaker("africas_talking")
    result = cb.call(send_sms, recipient, message)
"""

import logging
import time
from enum import Enum
from typing import Any, Callable

from shared.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"       # Normal operation — calls pass through
    OPEN = "open"           # Failing — calls rejected immediately
    HALF_OPEN = "half_open" # Testing recovery — one call allowed through


class CircuitBreaker:
    """Per-service circuit breaker.

    Args:
        name: Human-readable service name (used in log messages and errors).
        failure_threshold: Number of consecutive failures before opening the circuit.
        recovery_timeout: Seconds to wait in OPEN state before trying HALF_OPEN.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count: int = 0
        self.state: CircuitState = CircuitState.CLOSED
        self.last_failure_time: float = 0.0

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute func through the circuit breaker.

        Raises:
            ExternalServiceError: If the circuit is OPEN (fast-fail) or if func raises.
        """
        if self.state == CircuitState.OPEN:
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info(
                    "Circuit breaker '%s' → HALF_OPEN (elapsed=%.1fs)",
                    self.name,
                    elapsed,
                )
            else:
                raise ExternalServiceError(
                    self.name,
                    f"Circuit breaker open — retry after {self.recovery_timeout - elapsed:.0f}s",
                )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except ExternalServiceError:
            # Don't double-wrap our own errors; still count as failure
            self._on_failure()
            raise
        except Exception:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        if self.state != CircuitState.CLOSED:
            logger.info("Circuit breaker '%s' → CLOSED", self.name)
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def _on_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            if self.state != CircuitState.OPEN:
                logger.warning(
                    "Circuit breaker '%s' → OPEN (failures=%d)",
                    self.name,
                    self.failure_count,
                )
            self.state = CircuitState.OPEN

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    def reset(self) -> None:
        """Manually reset the circuit to CLOSED state (for testing)."""
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.last_failure_time = 0.0


# ---------------------------------------------------------------------------
# Module-level registry — one breaker instance per named service per Lambda
# container, reused across warm invocations.
# ---------------------------------------------------------------------------

_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: int = 60,
) -> CircuitBreaker:
    """Return the singleton CircuitBreaker for the given service name.

    Args:
        name: Unique service identifier (e.g. "africas_talking", "meta_whatsapp").
        failure_threshold: Failures before OPEN (ignored on subsequent calls).
        recovery_timeout: Seconds before HALF_OPEN attempt (ignored on subsequent calls).

    Returns:
        The CircuitBreaker instance for that name.
    """
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name, failure_threshold, recovery_timeout)
    return _breakers[name]
