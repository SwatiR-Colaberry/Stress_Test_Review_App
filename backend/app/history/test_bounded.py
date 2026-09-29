"""STORY-013: every call to the index or the model is bounded."""
import threading
import time

import pytest

from app.history.bounded import bounded_call


class Boom(Exception):
    pass


class Permanent(Exception):
    pass


def call(fn, **kw):
    return bounded_call(fn, what="thing", error=Boom, timeout_s=kw.pop("timeout_s", 1.0),
                        attempts=kw.pop("attempts", 3), backoff_s=0, **kw)


def test_returns_the_value():
    assert call(lambda: 42) == 42


def test_retries_then_succeeds():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise OSError("transient")
        return "ok"

    assert call(flaky) == "ok" and len(calls) == 3


def test_gives_up_after_the_capped_attempts_naming_the_cause():
    calls = []

    def always_fails():
        calls.append(1)
        raise OSError("down")

    with pytest.raises(Boom, match="failed after 3 attempts: OSError"):
        call(always_fails)
    assert len(calls) == 3


def test_a_hang_times_out_instead_of_blocking():
    release = threading.Event()
    started = time.monotonic()
    with pytest.raises(Boom, match="timed out after 0.05s"):
        call(lambda: release.wait(5), timeout_s=0.05, attempts=2)
    assert time.monotonic() - started < 1.0
    release.set()


def test_a_permanent_error_is_raised_at_once_unchanged():
    calls = []

    def not_built():
        calls.append(1)
        raise Permanent("never built")

    with pytest.raises(Permanent, match="never built"):
        call(not_built, no_retry=(Permanent,))
    assert len(calls) == 1


def test_attempts_must_be_positive():
    with pytest.raises(ValueError):
        call(lambda: 1, attempts=0)
