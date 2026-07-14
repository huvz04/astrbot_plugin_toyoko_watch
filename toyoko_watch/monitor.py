"""Polling coordination and availability transition state."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Any

from .matching import availability_signature, match_vacancies
from .models import Vacancy, WatchTask


class AvailabilityState:
    """Track last successful signatures without treating errors as absence."""

    def __init__(
        self,
        values: dict[str, str | None] | None = None,
        errors: dict[str, str] | None = None,
    ):
        self.values = dict(values or {})
        self.errors = dict(errors or {})

    def apply_success(self, key: str, signature: str | None, notify_changes: bool = False) -> bool:
        """Record a successful observation and return whether to notify."""
        known = key in self.values
        previous = self.values.get(key)
        self.values[key] = signature
        self.errors.pop(key, None)
        if signature is None:
            return False
        if not known or previous is None:
            return True
        return notify_changes and previous != signature

    def apply_error(self, key: str, error: str) -> None:
        """Record an error without changing the last successful value."""
        self.errors[key] = error

    def restore(self, key: str) -> None:
        """Return one slot observation to unknown state."""
        self.values.pop(key, None)
        self.errors.pop(key, None)

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe runtime state."""
        return {"values": self.values, "errors": self.errors}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AvailabilityState:
        """Restore state from persisted JSON."""
        return cls(values=data.get("values", {}), errors=data.get("errors", {}))


@dataclass(slots=True)
class MatchEvent:
    """A transition to matching inventory for one requirement slot."""

    task_id: str
    task_name: str
    slot_id: str
    slot_label: str
    hotel_id: str
    hotel_name: str
    checkin: str
    checkout: str
    occupants: int
    vacancies: list[Vacancy]
    url: str

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe event data."""
        result = asdict(self)
        result["vacancies"] = [item.to_dict() for item in self.vacancies]
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MatchEvent:
        """Restore a persisted match event."""
        return cls(
            task_id=str(data.get("task_id", "")),
            task_name=str(data.get("task_name", "")),
            slot_id=str(data.get("slot_id", "")),
            slot_label=str(data.get("slot_label", "")),
            hotel_id=str(data.get("hotel_id", "")),
            hotel_name=str(data.get("hotel_name", "")),
            checkin=str(data.get("checkin", "")),
            checkout=str(data.get("checkout", "")),
            occupants=int(data.get("occupants", 1)),
            vacancies=[Vacancy.from_dict(item) for item in data.get("vacancies", [])],
            url=str(data.get("url", "")),
        )


class MonitorService:
    """Run one task with bounded hotel-request concurrency."""

    def __init__(self, client, state: AvailabilityState, max_concurrency: int = 3):
        self.client = client
        self.state = state
        self.semaphore = asyncio.Semaphore(max(1, max_concurrency))

    @staticmethod
    def state_key(task: WatchTask, hotel_id: str, slot_id: str) -> str:
        """Build the stable state key for one task/hotel/slot."""
        return f"{task.id}:{hotel_id}:{task.checkin}:{task.checkout}:{slot_id}"

    async def run_task(self, task: WatchTask) -> tuple[list[MatchEvent], list[dict[str, str]]]:
        """Check all active slots, reusing responses by occupant count."""
        active_slots = [slot for slot in task.slots if slot.state == "active"]
        occupant_groups: dict[int, list] = {}
        for slot in active_slots:
            occupant_groups.setdefault(slot.occupants, []).append(slot)
        jobs = [
            self._run_group(task, hotel_id, occupants, slots)
            for hotel_id in task.hotel_ids
            for occupants, slots in occupant_groups.items()
        ]
        if not jobs:
            return [], []
        results = await asyncio.gather(*jobs)
        events: list[MatchEvent] = []
        errors: list[dict[str, str]] = []
        for group_events, group_errors in results:
            events.extend(group_events)
            errors.extend(group_errors)
        return events, errors

    async def _run_group(
        self, task: WatchTask, hotel_id: str, occupants: int, slots: list
    ) -> tuple[list[MatchEvent], list[dict[str, str]]]:
        async with self.semaphore:
            try:
                hotel_name, vacancies, url = await self.client.fetch_availability(
                    hotel_id,
                    task.checkin,
                    task.checkout,
                    occupants,
                    session=None,
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                for slot in slots:
                    self.state.apply_error(self.state_key(task, hotel_id, slot.id), error)
                return [], [{"hotel_id": hotel_id, "occupants": str(occupants), "error": error}]

        events: list[MatchEvent] = []
        for slot in slots:
            matches = match_vacancies(slot, vacancies)
            signature = availability_signature(matches) if matches else None
            if self.state.apply_success(
                self.state_key(task, hotel_id, slot.id),
                signature,
                notify_changes=task.notify_changes,
            ):
                events.append(
                    MatchEvent(
                        task_id=task.id,
                        task_name=task.name,
                        slot_id=slot.id,
                        slot_label=slot.label,
                        hotel_id=hotel_id,
                        hotel_name=hotel_name or hotel_id,
                        checkin=task.checkin,
                        checkout=task.checkout,
                        occupants=occupants,
                        vacancies=matches,
                        url=url,
                    )
                )
        return events, []
