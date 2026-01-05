import time
from typing import Callable, TypeVar

T = TypeVar("T")


def call_with_retries(
    fn: Callable[[], T],
    attempts: int = 3,
    backoff_sec: float = 1.0,
    sleep_fn: Callable[[float], None] = time.sleep
) -> T:
    if attempts <= 0:
        raise ValueError("attempts must be >= 1")

    last_exc = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - propagate after retries
            last_exc = exc
            if attempt == attempts - 1:
                raise
            sleep_fn(backoff_sec * (2 ** attempt))

    if last_exc:
        raise last_exc
    raise RuntimeError("Retry loop exited unexpectedly")
