"""Deterministic helpers for concise QQ-created monitoring tasks."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo


def _calendar_date(value: str, year: int) -> date:
    if len(value) != 4 or not value.isdigit():
        raise ValueError("日期必须使用 MMDD，例如 1106")
    try:
        return date(year, int(value[:2]), int(value[2:]))
    except ValueError as exc:
        raise ValueError(f"无效日期：{value}") from exc


def parse_quick_stay(
    checkin_mmdd: str,
    checkout_mmdd: str,
    today: date | None = None,
) -> tuple[str, str]:
    """Resolve an MMDD pair to the nearest valid future stay in Shanghai time."""
    current = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    checkin = _calendar_date(checkin_mmdd, current.year)
    if checkin < current:
        checkin = _calendar_date(checkin_mmdd, current.year + 1)
    checkout = _calendar_date(checkout_mmdd, checkin.year)
    if checkout <= checkin:
        checkout = _calendar_date(checkout_mmdd, checkin.year + 1)
    nights = (checkout - checkin).days
    if not 1 <= nights <= 30:
        raise ValueError("入住到退房必须相隔 1 至 30 晚")
    return checkin.isoformat(), checkout.isoformat()


def quick_task_id(hotel_id: str, checkin: str, checkout: str) -> str:
    """Return a stable ID that prevents duplicate hotel/date quick tasks."""
    return f"quick-{hotel_id}-{checkin.replace('-', '')}-{checkout.replace('-', '')}"


def build_quick_task(
    hotel_id: str,
    hotel_name: str,
    checkin: str,
    checkout: str,
    target_id: str,
    interval_seconds: int = 300,
) -> dict[str, Any]:
    """Build a standard editable task with broad single and multi slots."""
    return {
        "id": quick_task_id(hotel_id, checkin, checkout),
        "name": f"快捷监控 {hotel_name} {checkin} 至 {checkout}",
        "enabled": True,
        "hotel_ids": [hotel_id],
        "checkin": checkin,
        "checkout": checkout,
        "slots": [
            {
                "id": "single",
                "label": "全部单人房",
                "state": "active",
                "category": "single",
                "subtypes": ["economy_single", "standard_single", "large_single"],
                "exact_names": [],
                "keywords": [],
                "occupants": 1,
                "smoking": "any",
                "inventory": "either",
            },
            {
                "id": "multi",
                "label": "全部多人房",
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
        "target_ids": [target_id],
        "email_enabled": False,
        "notify_changes": False,
        "interval_seconds": min(3600, max(60, int(interval_seconds))),
    }
