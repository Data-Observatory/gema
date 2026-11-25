from __future__ import annotations

from intake_app.ratelimit import RateLimiter


def test_sliding_window_per_key() -> None:
    now = [0.0]
    limiter = RateLimiter(limit=2, window=60, clock=lambda: now[0])
    assert limiter.allow("1.1.1.1")
    assert limiter.allow("1.1.1.1")
    assert not limiter.allow("1.1.1.1")
    assert limiter.allow("2.2.2.2")  # another address has its own bucket
    now[0] = 59.0
    assert not limiter.allow("1.1.1.1")
    now[0] = 61.0
    assert limiter.allow("1.1.1.1")
