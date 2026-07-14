"""Serializable domain models and validation rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


@dataclass(slots=True)
class RequirementSlot:
    """One independently managed room requirement."""

    id: str
    label: str
    state: str = "active"
    category: str = "single"
    subtypes: list[str] = field(default_factory=list)
    exact_names: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    occupants: int = 1
    smoking: str = "any"
    inventory: str = "either"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RequirementSlot:
        """Create a slot from persisted JSON data."""
        return cls(
            id=str(data.get("id", "")),
            label=str(data.get("label", "")),
            state=str(data.get("state", "active")),
            category=str(data.get("category", "single")),
            subtypes=[str(item) for item in data.get("subtypes", [])],
            exact_names=[str(item) for item in data.get("exact_names", [])],
            keywords=[str(item) for item in data.get("keywords", [])],
            occupants=int(data.get("occupants", 1)),
            smoking=str(data.get("smoking", "any")),
            inventory=str(data.get("inventory", "either")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe slot data."""
        return asdict(self)


@dataclass(slots=True)
class WatchTask:
    """A multi-hotel monitoring task."""

    id: str
    name: str
    enabled: bool
    hotel_ids: list[str]
    checkin: str
    checkout: str
    slots: list[RequirementSlot]
    target_ids: list[str] = field(default_factory=list)
    email_enabled: bool = False
    notify_changes: bool = False
    interval_seconds: int = 300

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WatchTask:
        """Create a task from persisted JSON data."""
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            enabled=bool(data.get("enabled", False)),
            hotel_ids=[str(item).zfill(5) for item in data.get("hotel_ids", [])],
            checkin=str(data.get("checkin", "")),
            checkout=str(data.get("checkout", "")),
            slots=[RequirementSlot.from_dict(item) for item in data.get("slots", [])],
            target_ids=[str(item) for item in data.get("target_ids", [])],
            email_enabled=bool(data.get("email_enabled", False)),
            notify_changes=bool(data.get("notify_changes", False)),
            interval_seconds=int(data.get("interval_seconds", 300)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe task data."""
        result = asdict(self)
        result["slots"] = [slot.to_dict() for slot in self.slots]
        return result


@dataclass(slots=True)
class NotificationTarget:
    """A OneBot private-chat or group destination."""

    id: str
    label: str
    kind: str
    number: str
    enabled: bool = True

    @property
    def umo(self) -> str:
        """Return the AstrBot UMO for this target."""
        message_type = {
            "private": "FriendMessage",
            "group": "GroupMessage",
        }.get(self.kind)
        if message_type is None:
            raise ValueError("target kind must be private or group")
        if not self.number.isdigit():
            raise ValueError("target number must contain digits only")
        return f"aiocqhttp:{message_type}:{self.number}"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NotificationTarget:
        """Create a target from persisted JSON data."""
        return cls(
            id=str(data.get("id", "")),
            label=str(data.get("label", "")),
            kind=str(data.get("kind", "private")),
            number=str(data.get("number", "")),
            enabled=bool(data.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe target data including derived UMO."""
        result = asdict(self)
        result["umo"] = self.umo
        return result


@dataclass(slots=True)
class Vacancy:
    """One available Toyoko plan for a room type."""

    room: str
    smoking: str
    plan: str
    general: int
    member: int
    general_price: int | None = None
    member_price: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Vacancy:
        """Create a vacancy from JSON-like data."""
        return cls(
            room=str(data.get("room", "")),
            smoking=str(data.get("smoking", "")),
            plan=str(data.get("plan", "")),
            general=int(data.get("general", 0)),
            member=int(data.get("member", 0)),
            general_price=data.get("general_price"),
            member_price=data.get("member_price"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe vacancy data."""
        return asdict(self)


def validate_task(task: WatchTask, enabled_target_ids: set[str], smtp_ready: bool) -> None:
    """Validate a monitoring task before persistence or execution."""
    if not task.id or not task.name.strip():
        raise ValueError("task id and name are required")
    if not task.hotel_ids or any(len(item) != 5 or not item.isdigit() for item in task.hotel_ids):
        raise ValueError("at least one valid hotel id is required")
    try:
        checkin = date.fromisoformat(task.checkin)
        checkout = date.fromisoformat(task.checkout)
    except ValueError as exc:
        raise ValueError("checkin and checkout must use YYYY-MM-DD") from exc
    nights = (checkout - checkin).days
    if not 1 <= nights <= 30:
        raise ValueError("checkout must be 1 through 30 nights after checkin")
    active_slots = [slot for slot in task.slots if slot.state == "active"]
    if not active_slots:
        raise ValueError("at least one active requirement slot is required")
    for slot in task.slots:
        if slot.state not in {"active", "paused", "fulfilled"}:
            raise ValueError("slot state must be active, paused, or fulfilled")
        if slot.category not in {"single", "multi"}:
            raise ValueError("slot category must be single or multi")
        if not 1 <= slot.occupants <= 4:
            raise ValueError("slot occupants must be between 1 and 4")
        if slot.smoking not in {"any", "non_smoking", "smoking"}:
            raise ValueError("slot smoking filter is invalid")
        if slot.inventory not in {"either", "general", "member"}:
            raise ValueError("slot inventory filter is invalid")
    if not 60 <= task.interval_seconds <= 3600:
        raise ValueError("interval_seconds must be between 60 and 3600")
    if task.enabled:
        has_qq = bool(set(task.target_ids) & enabled_target_ids)
        has_email = task.email_enabled and smtp_ready
        if not (has_qq or has_email):
            raise ValueError("enabled task requires a notification destination")
