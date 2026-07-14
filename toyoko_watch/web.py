"""Framework-neutral operations exposed by the AstrBot plugin page."""

from __future__ import annotations

from typing import Any

from .service import ToyokoWatchService


class WebService:
    """Translate plugin page actions into application service operations."""

    def __init__(self, service: ToyokoWatchService):
        self.service = service

    def snapshot(self) -> dict[str, Any]:
        """Return status and editable configuration."""
        return self.service.snapshot()

    def hotels(self, query: str = "", limit: int = 100) -> list[dict[str, Any]]:
        """Search the local last-known-good hotel catalog."""
        return self.service.search_hotels(query, min(200, max(1, int(limit))))

    def save_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate and persist one task."""
        return self.service.save_task(payload).to_dict()

    def delete_task(self, task_id: str) -> dict[str, bool]:
        """Delete one task."""
        self.service.delete_task(task_id)
        return {"deleted": True}

    async def check_task(self, task_id: str) -> dict[str, Any]:
        """Run one task immediately."""
        return await self.service.check_all(task_id)

    def set_slot_state(self, task_id: str, slot_id: str, state: str) -> dict[str, Any]:
        """Update one independent requirement slot state."""
        return self.service.set_slot_state(task_id, slot_id, state).to_dict()

    def save_target(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create or replace one reusable QQ target."""
        return self.service.save_target(payload).to_dict()

    def delete_target(self, target_id: str) -> dict[str, bool]:
        """Delete one reusable QQ target."""
        self.service.delete_target(target_id)
        return {"deleted": True}
