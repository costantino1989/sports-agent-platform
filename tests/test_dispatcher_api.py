"""Guard tests for the scheduler dispatcher public API surface.

These pin the contract that survives the dead-code cleanup: the module must
import and ``ScheduleDispatcherService`` must keep exposing ``sync_only``.
"""

from __future__ import annotations

from src.schedule.services.dispatcher import ScheduleDispatcherService


def test_module_imports_and_exposes_sync_only() -> None:
    assert callable(ScheduleDispatcherService.sync_only)


def test_dispatcher_exports_from_package() -> None:
    from src.schedule import ScheduleDispatcherService as Exported

    assert Exported is ScheduleDispatcherService
