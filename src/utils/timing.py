"""Timing utilities for execution-time logging."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from time import perf_counter
from typing import ParamSpec, TypeVar

from src.utils.color_logger import get_logger

Params = ParamSpec("Params")
ReturnType = TypeVar("ReturnType")
LOGGER = get_logger()


def log_execution_time(
    func: Callable[Params, ReturnType],
) -> Callable[Params, ReturnType]:
    """Log total execution time for the decorated callable.

    Args:
        func: Callable to decorate.

    Returns:
        Wrapped callable that logs elapsed seconds after execution.
    """

    @wraps(func)
    def wrapper(*args: Params.args, **kwargs: Params.kwargs) -> ReturnType:
        """Run decorated callable and log elapsed runtime."""

        start = perf_counter()
        result = func(*args, **kwargs)
        elapsed_seconds = perf_counter() - start
        LOGGER.debug(f"{func.__qualname__} executed in {elapsed_seconds:.3f}s")
        return result

    return wrapper
