"""Application service shared by AstrBot commands and the plugin WebUI."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiohttp

from .catalog import parse_hotel_catalog, search_hotels, validate_catalog
from .client import ToyokoClient
from .models import NotificationTarget, WatchTask, validate_task
from .monitor import AvailabilityState, MatchEvent, MonitorService
from .notifiers import (
    DeliveryTracker,
    deliver_targets,
    format_availability_message,
    send_smtp_async,
)
from .storage import JsonStore

CATALOG_URL = "https://www.toyoko-inn.com/hotel_list/"


def starter_tasks(interval_seconds: int = 300) -> list[dict[str, Any]]:
    """Return safe paused tasks that preserve the standalone watcher's dates."""
    result = []
    for task_id, name, checkin, checkout in (
        ("yokohama-sat", "横滨周六晚 11/7", "2026-11-07", "2026-11-08"),
        ("yokohama-sun", "横滨周日晚 11/8", "2026-11-08", "2026-11-09"),
    ):
        result.append(
            {
                "id": task_id,
                "name": name,
                "enabled": False,
                "hotel_ids": ["00075", "00073"],
                "checkin": checkin,
                "checkout": checkout,
                "slots": [
                    {
                        "id": "single",
                        "label": "单人房",
                        "state": "active",
                        "category": "single",
                        "subtypes": [
                            "economy_single",
                            "standard_single",
                            "large_single",
                        ],
                        "exact_names": [],
                        "keywords": [],
                        "occupants": 1,
                        "smoking": "any",
                        "inventory": "either",
                    },
                    {
                        "id": "multi",
                        "label": "双人房",
                        "state": "active",
                        "category": "multi",
                        "subtypes": ["economy_double", "double", "twin", "triple"],
                        "exact_names": [],
                        "keywords": [],
                        "occupants": 2,
                        "smoking": "any",
                        "inventory": "either",
                    },
                ],
                "target_ids": [],
                "email_enabled": False,
                "notify_changes": False,
                "interval_seconds": min(3600, max(60, int(interval_seconds))),
            }
        )
    return result


class ToyokoWatchService:
    """Own persistent configuration, checks, and delivery retries."""

    def __init__(
        self,
        data_dir: Path,
        seed_catalog: list[dict[str, Any]],
        config: dict[str, Any],
        client: ToyokoClient | None = None,
        qq_sender: Callable[[str, str], Awaitable[bool]] | None = None,
        smtp_sender: Callable[[dict, str, str], Awaitable[None]] | None = None,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.qq_sender = qq_sender or self._unavailable_qq_sender
        self.smtp_sender = smtp_sender or send_smtp_async
        self.hotels_store = JsonStore(self.data_dir / "hotels.json", lambda: list(seed_catalog))
        self.tasks_store = JsonStore(
            self.data_dir / "tasks.json",
            lambda: starter_tasks(int(config.get("interval_seconds", 300))),
        )
        self.targets_store = JsonStore(self.data_dir / "targets.json", list)
        self.state_store = JsonStore(
            self.data_dir / "state.json",
            lambda: {
                "availability": {},
                "delivery": {},
                "pending_events": {},
                "last_check": "",
                "task_last_checks": {},
                "last_errors": [],
            },
        )
        self.hotels: list[dict[str, Any]] = self.hotels_store.load()
        self.tasks: list[WatchTask] = [
            WatchTask.from_dict(item) for item in self.tasks_store.load()
        ]
        self.targets: list[NotificationTarget] = [
            NotificationTarget.from_dict(item) for item in self.targets_store.load()
        ]
        raw_state = self.state_store.load()
        self.availability = AvailabilityState.from_dict(raw_state.get("availability", {}))
        self.delivery = DeliveryTracker.from_dict(raw_state.get("delivery", {}))
        self.pending_events: dict[str, dict[str, Any]] = dict(raw_state.get("pending_events", {}))
        self.last_check = str(raw_state.get("last_check", ""))
        self.task_last_checks: dict[str, str] = dict(raw_state.get("task_last_checks", {}))
        self.last_errors: list[dict[str, str]] = list(raw_state.get("last_errors", []))
        self.client = client or ToyokoClient(timeout=int(config.get("request_timeout", 30)))
        self.monitor = MonitorService(
            self.client,
            self.availability,
            max_concurrency=int(config.get("max_concurrency", 3)),
        )

    async def _unavailable_qq_sender(self, _umo: str, _text: str) -> bool:
        raise RuntimeError("AstrBot QQ sender is not configured")

    def smtp_ready(self) -> bool:
        """Return whether global SMTP fields permit a delivery attempt."""
        return bool(
            self.config.get("smtp_enabled", False)
            and self.config.get("smtp_host")
            and self.config.get("smtp_port")
            and self.config.get("smtp_recipients")
        )

    def search_hotels(self, query: str, limit: int = 100) -> list[dict[str, Any]]:
        """Search the last known-good local hotel catalog."""
        return search_hotels(self.hotels, query, limit)

    def snapshot(self) -> dict[str, Any]:
        """Return editable plugin data without sensitive global configuration."""
        return {
            "status": self.status(),
            "tasks": [item.to_dict() for item in self.tasks],
            "targets": [item.to_dict() for item in self.targets],
            "smtp_ready": self.smtp_ready(),
        }

    async def probe_rooms(
        self,
        hotel_ids: list[str],
        checkin: str,
        checkout: str,
        occupants: int,
    ) -> list[dict[str, Any]]:
        """Fetch exact room names for filter setup without requiring inventory."""
        results: list[dict[str, Any]] = []
        for hotel_id in hotel_ids[:20]:
            normalized = str(hotel_id).zfill(5)
            hotel_name, rooms, url = await self.client.fetch_room_types(
                normalized, checkin, checkout, int(occupants)
            )
            results.append(
                {
                    "hotel_id": normalized,
                    "hotel_name": hotel_name,
                    "rooms": rooms,
                    "url": url,
                }
            )
        return results

    def replace_catalog(self, html_text: str) -> dict[str, Any]:
        """Validate and atomically replace the local catalog."""
        records = parse_hotel_catalog(html_text)
        validate_catalog(records, self.hotels)
        self.hotels_store.save(records)
        self.hotels = records
        return {"hotels": len(records)}

    async def refresh_catalog(self) -> dict[str, Any]:
        """Refresh the local hotel catalog from the official hotel list."""
        timeout = aiohttp.ClientTimeout(total=int(self.config.get("request_timeout", 30)))
        headers = {"User-Agent": "Mozilla/5.0 ToyokoWatch/0.1"}
        async with (
            aiohttp.ClientSession(timeout=timeout, headers=headers) as session,
            session.get(CATALOG_URL) as response,
        ):
            response.raise_for_status()
            content = await response.text()
        return self.replace_catalog(content)

    async def test_target(self, target_id: str) -> dict[str, Any]:
        """Send a proactive test message to one configured QQ target."""
        target = next((item for item in self.targets if item.id == target_id), None)
        if target is None:
            raise KeyError(f"target not found: {target_id}")
        success = bool(
            await self.qq_sender(target.umo, "【测试】东横INN空房监控主动消息发送成功。")
        )
        return {"success": success, "umo": target.umo}

    async def test_email(self) -> dict[str, bool]:
        """Send one SMTP test using the current AstrBot plugin configuration."""
        if not self.smtp_ready():
            raise ValueError("SMTP configuration is incomplete")
        await self.smtp_sender(
            self.config,
            "东横INN空房监控测试",
            "东横INN空房监控邮件发送成功。",
        )
        return {"success": True}

    def save_target(self, data: dict[str, Any]) -> NotificationTarget:
        """Create or replace one reusable QQ destination."""
        target = NotificationTarget.from_dict(data)
        _ = target.umo
        if not target.id or not target.label.strip():
            raise ValueError("target id and label are required")
        self.targets = [item for item in self.targets if item.id != target.id]
        self.targets.append(target)
        self.targets_store.save([item.to_dict() for item in self.targets])
        return target

    def delete_target(self, target_id: str) -> None:
        """Delete a target and remove it from tasks."""
        self.targets = [item for item in self.targets if item.id != target_id]
        for task in self.tasks:
            task.target_ids = [item for item in task.target_ids if item != target_id]
        self.targets_store.save([item.to_dict() for item in self.targets])
        self.tasks_store.save([item.to_dict() for item in self.tasks])

    def save_task(self, data: dict[str, Any]) -> WatchTask:
        """Validate, create, or replace one monitoring task."""
        task = WatchTask.from_dict(data)
        enabled_target_ids = {item.id for item in self.targets if item.enabled}
        validate_task(task, enabled_target_ids, self.smtp_ready())
        self.tasks = [item for item in self.tasks if item.id != task.id]
        self.tasks.append(task)
        self.tasks_store.save([item.to_dict() for item in self.tasks])
        return task

    def delete_task(self, task_id: str) -> None:
        """Delete one task and its runtime observations."""
        self.tasks = [item for item in self.tasks if item.id != task_id]
        self.tasks_store.save([item.to_dict() for item in self.tasks])
        prefixes = [key for key in self.availability.values if key.startswith(f"{task_id}:")]
        for key in prefixes:
            self.availability.restore(key)
        self._save_state()

    def set_slot_state(self, task_id: str, slot_id: str, state: str) -> WatchTask:
        """Fulfill, pause, or restore exactly one requirement slot."""
        if state not in {"active", "paused", "fulfilled"}:
            raise ValueError("slot state must be active, paused, or fulfilled")
        task = self._task(task_id)
        slot = next((item for item in task.slots if item.id == slot_id), None)
        if slot is None:
            raise KeyError(f"slot not found: {slot_id}")
        slot.state = state
        prefix = f"{task.id}:"
        suffix = f":{slot.id}"
        for key in list(self.availability.values):
            if key.startswith(prefix) and key.endswith(suffix):
                self.availability.restore(key)
        for event_id, pending in list(self.pending_events.items()):
            event = pending.get("event", {})
            if event.get("task_id") == task.id and event.get("slot_id") == slot.id:
                self.pending_events.pop(event_id, None)
        self.tasks_store.save([item.to_dict() for item in self.tasks])
        self._save_state()
        return task

    async def check_all(self, task_id: str | None = None) -> dict[str, Any]:
        """Run enabled tasks, add transition events, and retry pending delivery."""
        tasks = [self._task(task_id)] if task_id else [item for item in self.tasks if item.enabled]
        new_events = 0
        errors: list[dict[str, str]] = []
        for task in tasks:
            if not task.enabled and task_id is None:
                continue
            events, task_errors = await self.monitor.run_task(task)
            errors.extend(task_errors)
            for event in events:
                event_id = self._event_id(event)
                self.pending_events[event_id] = {
                    "event": event.to_dict(),
                    "target_ids": list(task.target_ids),
                    "email_enabled": task.email_enabled,
                }
                new_events += 1
        await self._deliver_pending()
        self.last_check = datetime.now(timezone.utc).isoformat()
        for task in tasks:
            self.task_last_checks[task.id] = self.last_check
        self.last_errors = errors[-50:]
        self._save_state()
        return {
            "checked_tasks": len(tasks),
            "new_events": new_events,
            "errors": errors,
            "pending_events": len(self.pending_events),
            "last_check": self.last_check,
        }

    async def check_due(self, now: datetime | None = None) -> dict[str, Any]:
        """Run only enabled tasks whose individual interval has elapsed."""
        current = now or datetime.now(timezone.utc)
        due: list[WatchTask] = []
        for task in self.tasks:
            if not task.enabled:
                continue
            previous = self.task_last_checks.get(task.id)
            if not previous:
                due.append(task)
                continue
            try:
                elapsed = (current - datetime.fromisoformat(previous)).total_seconds()
            except ValueError:
                elapsed = task.interval_seconds
            if elapsed >= task.interval_seconds:
                due.append(task)

        new_events = 0
        errors: list[dict[str, str]] = []
        for task in due:
            events, task_errors = await self.monitor.run_task(task)
            errors.extend(task_errors)
            for event in events:
                event_id = self._event_id(event)
                self.pending_events[event_id] = {
                    "event": event.to_dict(),
                    "target_ids": list(task.target_ids),
                    "email_enabled": task.email_enabled,
                }
                new_events += 1
            self.task_last_checks[task.id] = current.isoformat()
        await self._deliver_pending()
        self.last_check = current.isoformat()
        self.last_errors = errors[-50:]
        self._save_state()
        return {
            "checked_tasks": len(due),
            "new_events": new_events,
            "errors": errors,
            "pending_events": len(self.pending_events),
            "last_check": self.last_check,
        }

    async def _deliver_pending(self) -> None:
        targets = {item.id: item for item in self.targets if item.enabled}
        for event_id, pending in list(self.pending_events.items()):
            event = MatchEvent.from_dict(pending["event"])
            text = format_availability_message(event)
            selected = [
                targets[target_id]
                for target_id in pending.get("target_ids", [])
                if target_id in targets
            ]
            await deliver_targets(self.qq_sender, selected, text, self.delivery, event_id)
            required_ids = [item.id for item in selected]
            if pending.get("email_enabled") and self.smtp_ready():
                email_id = "email"
                required_ids.append(email_id)
                if self.delivery.should_attempt(event_id, email_id):
                    try:
                        await self.smtp_sender(
                            self.config,
                            f"东横INN有房了: {event.task_name} {event.hotel_name}",
                            text,
                        )
                        self.delivery.record(event_id, email_id, True)
                    except Exception as exc:
                        self.delivery.record(
                            event_id,
                            email_id,
                            False,
                            f"{type(exc).__name__}: {exc}",
                        )
            if not required_ids or all(
                self.delivery.target_state(event_id, target_id)["success"]
                for target_id in required_ids
            ):
                self.pending_events.pop(event_id, None)

    def status(self) -> dict[str, Any]:
        """Return public operational status without SMTP secrets."""
        return {
            "enabled": bool(self.config.get("enabled", True)),
            "tasks": len(self.tasks),
            "enabled_tasks": sum(item.enabled for item in self.tasks),
            "active_slots": sum(
                slot.state == "active" for task in self.tasks for slot in task.slots
            ),
            "targets": len(self.targets),
            "hotels": len(self.hotels),
            "last_check": self.last_check,
            "next_check": self._next_check(),
            "last_errors": self.last_errors,
            "pending_events": len(self.pending_events),
        }

    def _next_check(self) -> str:
        """Return the earliest per-task due time for status display."""
        next_values: list[datetime] = []
        for task in self.tasks:
            if not task.enabled:
                continue
            previous = self.task_last_checks.get(task.id)
            if not previous:
                return "due"
            try:
                checked = datetime.fromisoformat(previous)
            except ValueError:
                return "due"
            next_values.append(checked + timedelta(seconds=task.interval_seconds))
        return min(next_values).isoformat() if next_values else ""

    def _task(self, task_id: str | None) -> WatchTask:
        task = next((item for item in self.tasks if item.id == task_id), None)
        if task is None:
            raise KeyError(f"task not found: {task_id}")
        return task

    @staticmethod
    def _event_id(event: MatchEvent) -> str:
        payload = json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _save_state(self) -> None:
        self.state_store.save(
            {
                "availability": self.availability.to_dict(),
                "delivery": self.delivery.to_dict(),
                "pending_events": self.pending_events,
                "last_check": self.last_check,
                "task_last_checks": self.task_last_checks,
                "last_errors": self.last_errors,
            }
        )
