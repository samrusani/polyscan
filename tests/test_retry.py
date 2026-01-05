import pytest

from src.infra.retry import call_with_retries


def test_call_with_retries_success_after_failures():
    calls = {"count": 0}
    sleeps = []

    def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise ValueError("fail")
        return "ok"

    def fake_sleep(seconds):
        sleeps.append(seconds)

    result = call_with_retries(flaky, attempts=3, backoff_sec=1, sleep_fn=fake_sleep)
    assert result == "ok"
    assert calls["count"] == 3
    assert sleeps == [1, 2]


def test_call_with_retries_raises_after_exhaustion():
    def always_fail():
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        call_with_retries(always_fail, attempts=2, backoff_sec=0, sleep_fn=lambda _: None)
