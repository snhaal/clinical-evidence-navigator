"""Unit tests for app.rate_limit.InMemoryRateLimiter."""

import time

from app.rate_limit import InMemoryRateLimiter


def test_allows_requests_up_to_the_limit():
    limiter = InMemoryRateLimiter(max_requests=3, window_seconds=3600)

    assert limiter.check_and_record("1.2.3.4") is True
    assert limiter.check_and_record("1.2.3.4") is True
    assert limiter.check_and_record("1.2.3.4") is True


def test_rejects_requests_over_the_limit():
    limiter = InMemoryRateLimiter(max_requests=2, window_seconds=3600)

    assert limiter.check_and_record("1.2.3.4") is True
    assert limiter.check_and_record("1.2.3.4") is True
    assert (
        limiter.check_and_record("1.2.3.4") is False
    )  # third request within the window is rejected


def test_different_ips_have_independent_limits():
    limiter = InMemoryRateLimiter(max_requests=1, window_seconds=3600)

    assert limiter.check_and_record("1.1.1.1") is True
    assert limiter.check_and_record("2.2.2.2") is True  # unaffected by 1.1.1.1's usage
    assert limiter.check_and_record("1.1.1.1") is False


def test_requests_outside_the_window_are_no_longer_counted():
    limiter = InMemoryRateLimiter(max_requests=1, window_seconds=0.05)

    assert limiter.check_and_record("1.2.3.4") is True
    assert limiter.check_and_record("1.2.3.4") is False
    time.sleep(0.1)
    assert limiter.check_and_record("1.2.3.4") is True  # window has expired


def test_remaining_reflects_current_usage():
    limiter = InMemoryRateLimiter(max_requests=3, window_seconds=3600)

    assert limiter.remaining("1.2.3.4") == 3
    limiter.check_and_record("1.2.3.4")
    assert limiter.remaining("1.2.3.4") == 2
