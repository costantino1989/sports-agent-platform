"""Async task cache for league-scoped dossier payload fetches."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import partial
from typing import TypeAlias

from src.models.dossier import EndpointPayload

PayloadFactory: TypeAlias = Callable[[], Awaitable[EndpointPayload]]


class LeaguePayloadTaskCache:
    """Cache in-flight and completed payload tasks by league-scoped key."""

    def __init__(self) -> None:
        """Initialize the async cache primitives."""

        self._lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task[EndpointPayload]] = {}

    async def get_or_create(
        self,
        key: str,
        factory: PayloadFactory,
    ) -> asyncio.Task[EndpointPayload]:
        """Return a cached task for key, creating it once when missing.

        Args:
            key: Stable cache key for a league-scoped payload.
            factory: Coroutine factory used to create the task on cache miss.

        Returns:
            Cached or newly created task that resolves to ``EndpointPayload``.
        """

        async with self._lock:
            cached_task = self._tasks.get(key)
            if cached_task is not None and not cached_task.cancelled():
                return cached_task
            created_task = asyncio.create_task(factory())
            created_task.add_done_callback(partial(self._evict_failed_task, cache_key=key))
            self._tasks[key] = created_task
            return created_task

    def _evict_failed_task(
        self,
        completed_task: asyncio.Task[EndpointPayload],
        cache_key: str,
    ) -> None:
        """Remove failed tasks from cache to allow retries.

        Args:
            completed_task: Completed task to inspect.
            cache_key: Key associated with the completed task.
        """

        if completed_task.cancelled():
            self._tasks.pop(cache_key, None)
            return
        if completed_task.exception() is not None:
            self._tasks.pop(cache_key, None)
            return
        payload = completed_task.result()
        if payload.error:
            self._tasks.pop(cache_key, None)
