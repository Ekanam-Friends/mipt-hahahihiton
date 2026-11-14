"""Cooperative whole-question deadline, shared by successive provider calls."""
from contextlib import contextmanager
from contextvars import ContextVar
import time

_deadline = ContextVar('regnav_deadline', default=None)


def remaining_timeout(default):
    deadline = _deadline.get()
    if deadline is None:
        return default
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Question budget exhausted')
    return min(default, remaining)


@contextmanager
def question_budget(seconds):
    token = _deadline.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _deadline.reset(token)
