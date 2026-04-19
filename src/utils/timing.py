"""Timing utilities for execution-time logging."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import wraps
from inspect import Signature, signature
from time import perf_counter
from typing import Any, ParamSpec, TypeVar, overload

from src.utils.color_logger import get_logger

Params = ParamSpec("Params")
ReturnType = TypeVar("ReturnType")
LOGGER = get_logger()


@overload
def log_execution_time(
    func: Callable[Params, ReturnType],
) -> Callable[Params, ReturnType]:
    """Decorate a callable and log its execution time."""


@overload
def log_execution_time(
    func: None = None,
    *,
    label: str | None = None,
    reference_arg: str | None = None,
    log_level: str = "debug",
) -> Callable[[Callable[Params, ReturnType]], Callable[Params, ReturnType]]:
    """Create a timing decorator with optional label and reference argument."""


def log_execution_time(
    func: Callable[Params, ReturnType] | None = None,
    *,
    label: str | None = None,
    reference_arg: str | None = None,
    log_level: str = "debug",
) -> (
    Callable[Params, ReturnType]
    | Callable[[Callable[Params, ReturnType]], Callable[Params, ReturnType]]
):
    """Log total execution time for sync and async callables.

    Args:
        func: Callable to decorate when used as ``@log_execution_time``.
        label: Optional static label shown in timing logs.
        reference_arg: Optional argument name included in timing logs.
        log_level: Logger level used for timing line (``debug`` or ``info``).

    Returns:
        Decorated callable, or a decorator when used with options.
    """

    def decorator(target: Callable[Params, ReturnType]) -> Callable[Params, ReturnType]:
        """Wrap one callable and emit elapsed runtime logs."""

        target_label = label or target.__qualname__
        target_signature = signature(target) if reference_arg else None
        if asyncio.iscoroutinefunction(target):

            @wraps(target)
            async def async_wrapper(*args: Params.args, **kwargs: Params.kwargs) -> ReturnType:
                """Run async callable and log elapsed runtime."""

                start = perf_counter()
                try:
                    return await target(*args, **kwargs)
                finally:
                    _log_elapsed(
                        target_label=target_label,
                        elapsed_seconds=perf_counter() - start,
                        reference=_extract_reference(
                            target_signature=target_signature,
                            reference_arg=reference_arg,
                            args=args,
                            kwargs=kwargs,
                        ),
                        log_level=log_level,
                    )

            return async_wrapper

        @wraps(target)
        def wrapper(*args: Params.args, **kwargs: Params.kwargs) -> ReturnType:
            """Run sync callable and log elapsed runtime."""

            start = perf_counter()
            try:
                return target(*args, **kwargs)
            finally:
                _log_elapsed(
                    target_label=target_label,
                    elapsed_seconds=perf_counter() - start,
                    reference=_extract_reference(
                        target_signature=target_signature,
                        reference_arg=reference_arg,
                        args=args,
                        kwargs=kwargs,
                    ),
                    log_level=log_level,
                )

        return wrapper

    if func is None:
        return decorator
    return decorator(func)


def _extract_reference(
    target_signature: Signature | None,
    reference_arg: str | None,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> str | None:
    """Extract optional timing reference from bound call arguments.

    Args:
        target_signature: Callable signature when reference extraction is enabled.
        reference_arg: Argument name used as timing reference.
        args: Positional call arguments.
        kwargs: Keyword call arguments.

    Returns:
        Stringified reference when available, otherwise ``None``.
    """

    if target_signature is None or not reference_arg:
        return None
    try:
        bound = target_signature.bind_partial(*args, **kwargs)
    except TypeError:
        return None
    reference = bound.arguments.get(reference_arg)
    if reference is None:
        return None
    return str(reference)


def _log_elapsed(
    target_label: str,
    elapsed_seconds: float,
    reference: str | None,
    log_level: str,
) -> None:
    """Emit execution-time log using the selected log level.

    Args:
        target_label: Label shown in timing output.
        elapsed_seconds: Measured runtime in seconds.
        reference: Optional reference suffix.
        log_level: Logger level name (``debug`` or ``info``).
    """

    message = f"{target_label} executed in {elapsed_seconds:.3f}s"
    if reference:
        message = f"{target_label} [{reference}] executed in {elapsed_seconds:.3f}s"
    if log_level == "info":
        LOGGER.info(message)
        return
    LOGGER.debug(message)
