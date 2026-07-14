"""QQ delivery tracking, message formatting, and SMTP transport."""

from __future__ import annotations

import asyncio
import smtplib
from collections.abc import Awaitable, Callable
from email.message import EmailMessage
from typing import Any

from .models import NotificationTarget
from .monitor import MatchEvent


def format_availability_message(event: MatchEvent) -> str:
    """Format an availability transition for QQ and email."""
    lines = [
        "东横INN有符合条件的房间了！",
        f"任务：{event.task_name}",
        f"需求：{event.slot_label}（{event.occupants}人）",
        f"酒店：{event.hotel_name} ({event.hotel_id})",
        f"日期：{event.checkin} → {event.checkout}",
    ]
    for vacancy in event.vacancies[:8]:
        smoking = "禁烟" if vacancy.smoking == "non_smoking" else "吸烟"
        prices = []
        if vacancy.general_price is not None:
            prices.append(f"一般{vacancy.general_price}円")
        if vacancy.member_price is not None:
            prices.append(f"会员{vacancy.member_price}円")
        price_text = " / ".join(prices) if prices else "价格未提供"
        lines.append(
            f"• {vacancy.room}｜{smoking}｜{vacancy.plan or '普通方案'}｜"
            f"一般{vacancy.general} / 会员{vacancy.member}｜{price_text}"
        )
    if len(event.vacancies) > 8:
        lines.append(f"另有 {len(event.vacancies) - 8} 个匹配方案")
    lines.extend(
        [
            event.url,
            "请在实际订到后手动标记“已订到”，插件才会停止该需求。",
        ]
    )
    return "\n".join(lines)


class DeliveryTracker:
    """Persist per-event, per-target success and bounded retry state."""

    def __init__(self, max_attempts: int = 3, records: dict[str, dict[str, dict]] | None = None):
        self.max_attempts = max(1, int(max_attempts))
        self.records: dict[str, dict[str, dict]] = records or {}

    def target_state(self, event_id: str, target_id: str) -> dict:
        """Return mutable delivery state for one target."""
        return self.records.setdefault(event_id, {}).setdefault(
            target_id, {"attempts": 0, "success": False, "error": ""}
        )

    def should_attempt(self, event_id: str, target_id: str) -> bool:
        """Return whether a target still needs and may receive an attempt."""
        state = self.target_state(event_id, target_id)
        return not state["success"] and state["attempts"] < self.max_attempts

    def record(self, event_id: str, target_id: str, success: bool, error: str = "") -> None:
        """Record one delivery attempt."""
        state = self.target_state(event_id, target_id)
        state["attempts"] += 1
        state["success"] = bool(success)
        state["error"] = "" if success else error

    def pending_ids(self, event_id: str) -> list[str]:
        """Return target IDs eligible for another retry."""
        return [
            target_id
            for target_id, state in self.records.get(event_id, {}).items()
            if not state["success"] and state["attempts"] < self.max_attempts
        ]

    def failures(self, event_id: str) -> dict[str, dict]:
        """Return unsuccessful delivery records."""
        return {
            target_id: dict(state)
            for target_id, state in self.records.get(event_id, {}).items()
            if not state["success"]
        }

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe tracker state."""
        return {"max_attempts": self.max_attempts, "records": self.records}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeliveryTracker:
        """Restore persisted delivery state."""
        return cls(
            max_attempts=int(data.get("max_attempts", 3)),
            records=data.get("records", {}),
        )


async def deliver_targets(
    send: Callable[[str, str], Awaitable[bool]],
    targets: list[NotificationTarget],
    text: str,
    tracker: DeliveryTracker,
    event_id: str,
) -> dict[str, bool]:
    """Send to pending OneBot targets without resending successful targets."""
    results: dict[str, bool] = {}
    for target in targets:
        if not target.enabled:
            continue
        state = tracker.target_state(event_id, target.id)
        if state["success"]:
            results[target.id] = True
            continue
        if not tracker.should_attempt(event_id, target.id):
            results[target.id] = False
            continue
        try:
            success = bool(await send(target.umo, text))
            error = "" if success else "send returned false"
        except Exception as exc:
            success = False
            error = f"{type(exc).__name__}: {exc}"
        tracker.record(event_id, target.id, success, error)
        results[target.id] = success
    return results


def send_smtp(config: dict[str, Any], subject: str, body: str) -> None:
    """Send one UTF-8 email using configured STARTTLS or implicit SSL."""
    host = str(config.get("smtp_host", "")).strip()
    port = int(config.get("smtp_port", 0))
    user = str(config.get("smtp_user", "")).strip()
    password = str(config.get("smtp_password", ""))
    sender = str(config.get("smtp_from", "")).strip() or user
    recipients = [
        str(item).strip() for item in config.get("smtp_recipients", []) if str(item).strip()
    ]
    if not host or not port or not sender or not recipients:
        raise ValueError("SMTP host, port, sender, and recipients are required")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(body)
    smtp_class = smtplib.SMTP_SSL if config.get("smtp_ssl", False) else smtplib.SMTP
    with smtp_class(host, port, timeout=30) as smtp:
        if not config.get("smtp_ssl", False) and config.get("smtp_starttls", True):
            smtp.starttls()
        if user and password:
            smtp.login(user, password)
        smtp.send_message(message)


async def send_smtp_async(config: dict[str, Any], subject: str, body: str) -> None:
    """Run blocking SMTP delivery outside the AstrBot event loop."""
    await asyncio.to_thread(send_smtp, config, subject, body)
