"""Regression tests for cross-directory orderbook request fanout."""

from __future__ import annotations

import pytest

from maker.rate_limiting import OrderbookRateLimiter


class MonotonicClock:
    """Manually advanced monotonic clock for deterministic rate-limit tests."""

    def __init__(self, start: float = 3_601.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> MonotonicClock:
    """Replace the limiter clock without waiting in real time."""
    clock = MonotonicClock()
    monkeypatch.setattr("maker.rate_limiting.time.monotonic", clock)
    return clock


@pytest.mark.parametrize("source_count", [6, 7])
def test_cross_directory_fanout_does_not_accumulate_violations(
    clock: MonotonicClock, source_count: int
) -> None:
    sources = tuple(f"directory-{index}" for index in range(source_count))
    limiter = OrderbookRateLimiter(directory_sources=frozenset(sources))

    rounds = 50
    for _ in range(rounds):
        assert limiter.check("J5sharednick", sources[0]) is True
        for source in sources[1:]:
            assert limiter.check("J5sharednick", source) is False
        assert limiter.get_violation_count("J5sharednick") == 0
        assert not limiter.is_banned("J5sharednick")
        clock.advance(30 * 60)

    statistics = limiter.get_statistics()
    assert statistics["fanout_duplicates"] == rounds * (source_count - 1)
    assert statistics["total_violations"] == 0


def test_legacy_requests_without_sources_keep_existing_behavior(clock: MonotonicClock) -> None:
    limiter = OrderbookRateLimiter(interval=10.0)

    assert limiter.check("J5legacy") is True
    assert limiter.check("J5legacy") is False
    assert limiter.get_violation_count("J5legacy") == 1
    assert limiter.get_statistics()["fanout_duplicates"] == 0


@pytest.mark.parametrize("unknown_source", [None, "unconfigured-directory", "direct"])
def test_unknown_sources_do_not_earn_a_fanout_exemption(
    clock: MonotonicClock, unknown_source: str | None
) -> None:
    limiter = OrderbookRateLimiter(directory_sources=frozenset({"directory-a", "directory-b"}))

    assert limiter.check("J5known", "directory-a") is True
    assert limiter.check("J5known", "directory-b") is False
    assert limiter.check("J5known", unknown_source) is False
    assert limiter.get_violation_count("J5known") == 1

    assert limiter.check("J5unknown-first", unknown_source) is True
    assert limiter.check("J5unknown-first", "directory-a") is False
    assert limiter.get_violation_count("J5unknown-first") == 1


def test_duplicate_source_only_receives_one_fanout_exemption(clock: MonotonicClock) -> None:
    limiter = OrderbookRateLimiter(directory_sources=frozenset({"directory-a", "directory-b"}))

    assert limiter.check("J5duplicate", "directory-a") is True
    assert limiter.check("J5duplicate", "directory-b") is False
    assert limiter.get_violation_count("J5duplicate") == 0
    assert limiter.check("J5duplicate", "directory-b") is False
    assert limiter.get_violation_count("J5duplicate") == 1
    assert limiter.get_statistics()["fanout_duplicates"] == 1


def test_fanout_duplicates_do_not_extend_the_admission_window(clock: MonotonicClock) -> None:
    limiter = OrderbookRateLimiter(
        interval=10.0,
        directory_sources=frozenset({"directory-a", "directory-b", "directory-c"}),
    )

    assert limiter.check("J5anchored", "directory-a") is True
    clock.advance(9.0)
    assert limiter.check("J5anchored", "directory-b") is False
    clock.advance(1.0)
    assert limiter.check("J5anchored", "directory-c") is True
    assert limiter.get_violation_count("J5anchored") == 0


def test_fanout_exemption_does_not_apply_during_severe_backoff(clock: MonotonicClock) -> None:
    limiter = OrderbookRateLimiter(
        interval=10.0,
        violation_warning_threshold=1,
        violation_severe_threshold=2,
        violation_ban_threshold=10,
        directory_sources=frozenset({"directory-a", "directory-b", "directory-c"}),
    )

    assert limiter.check("J5backoff", "directory-a") is True
    assert limiter.check("J5backoff", "directory-a") is False
    assert limiter.check("J5backoff", "directory-a") is False
    assert limiter.check("J5backoff", "directory-b") is False
    clock.advance(11.0)
    assert limiter.check("J5backoff", "directory-c") is False
    assert limiter.get_violation_count("J5backoff") == 4
    assert limiter.get_statistics()["fanout_duplicates"] == 0


def test_fanout_exemption_cannot_bypass_a_ban(clock: MonotonicClock) -> None:
    limiter = OrderbookRateLimiter(
        violation_ban_threshold=1,
        ban_duration=60.0,
        directory_sources=frozenset({"directory-a", "directory-b", "directory-c"}),
    )

    assert limiter.check("J5banned", "directory-a") is True
    assert limiter.check("J5banned", "directory-a") is False
    assert limiter.check("J5banned", "directory-b") is False
    assert limiter.is_banned("J5banned")
    assert limiter.check("J5banned", "directory-c") is False
    assert limiter.get_violation_count("J5banned") == 2
    assert limiter.get_statistics()["fanout_duplicates"] == 0


def test_repeated_source_rotation_still_reaches_ban(clock: MonotonicClock) -> None:
    sources = tuple(f"directory-{index}" for index in range(7))
    limiter = OrderbookRateLimiter(directory_sources=frozenset(sources))

    assert limiter.check("J5spammer", sources[0]) is True
    for source in sources[1:]:
        assert limiter.check("J5spammer", source) is False
    for index in range(101):
        assert limiter.check("J5spammer", sources[index % len(sources)]) is False
    assert limiter.is_banned("J5spammer")
    assert limiter.get_violation_count("J5spammer") == 100
    assert limiter.get_statistics()["fanout_duplicates"] == 6


def test_identity_eviction_releases_fanout_source_state(clock: MonotonicClock) -> None:
    limiter = OrderbookRateLimiter(
        max_tracked_identities=1,
        directory_sources=frozenset({"directory-a", "directory-b"}),
    )

    assert limiter.check("J5evicted", "directory-a") is True
    assert limiter.check("J5evicted", "directory-b") is False
    assert limiter._fanout_sources["J5evicted"] == {"directory-a", "directory-b"}
    assert limiter.check("J5other", "directory-a") is True
    assert "J5evicted" not in limiter._fanout_sources
    assert limiter.check("J5evicted", "directory-b") is True


def test_stale_cleanup_releases_fanout_source_state(clock: MonotonicClock) -> None:
    limiter = OrderbookRateLimiter(
        directory_sources=frozenset({"directory-a", "directory-b"}),
    )

    assert limiter.check("J5stale", "directory-a") is True
    assert limiter.check("J5stale", "directory-b") is False
    clock.advance(11.0)
    limiter.cleanup_old_entries(max_age=10.0)
    assert "J5stale" not in limiter._fanout_sources
    assert limiter.check("J5stale", "directory-b") is True


def test_ban_expiration_releases_fanout_source_state(clock: MonotonicClock) -> None:
    limiter = OrderbookRateLimiter(
        violation_ban_threshold=1,
        ban_duration=10.0,
        directory_sources=frozenset({"directory-a", "directory-b"}),
    )

    assert limiter.check("J5expired-ban", "directory-a") is True
    assert limiter.check("J5expired-ban", "directory-a") is False
    assert limiter.check("J5expired-ban", "directory-b") is False
    assert limiter.is_banned("J5expired-ban")
    clock.advance(10.1)
    assert not limiter.is_banned("J5expired-ban")
    assert "J5expired-ban" not in limiter._fanout_sources
    assert limiter.check("J5expired-ban", "directory-b") is True
