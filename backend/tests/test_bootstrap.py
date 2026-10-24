"""Start-up self-healing: a failed bootstrap (e.g. DB unreachable) is retried instead of leaving the API permanently unready."""
import pytest

from app import bootstrap


def test_retry_until_ready_recovers_after_transient_failures(monkeypatch):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("PostgreSQL not reachable")
        return {"forecast_rows_created": 0}

    monkeypatch.setattr(bootstrap, "initialise", flaky)
    sleeps = []
    tries = bootstrap.retry_until_ready(interval=2.5, sleep=sleeps.append)
    assert tries == 3 and calls["n"] == 3 and sleeps == [2.5, 2.5]


def test_retry_until_ready_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(bootstrap, "initialise", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    with pytest.raises(RuntimeError, match="did not succeed after 3"):
        bootstrap.retry_until_ready(interval=0, max_attempts=3, sleep=lambda _: None)


def test_background_retry_is_not_started_twice(monkeypatch):
    monkeypatch.setitem(bootstrap._state, "retrying", True)
    started = []
    monkeypatch.setattr(bootstrap.threading, "Thread", lambda *a, **k: started.append(1))
    bootstrap.start_background_retry()
    assert started == []


def test_retry_until_ready_with_exponential_backoff(monkeypatch):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 4:
            raise RuntimeError("PostgreSQL reconnecting...")
        return {"forecast_rows_created": 0}

    monkeypatch.setattr(bootstrap, "initialise", flaky)
    sleeps = []
    tries = bootstrap.retry_until_ready(interval=2.0, sleep=sleeps.append, backoff=True, max_interval=20.0)
    assert tries == 4 and calls["n"] == 4 and sleeps == [2.0, 4.0, 8.0]

