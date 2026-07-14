"""Room-name normalization and requirement matching."""

from __future__ import annotations

import hashlib
import json

from .models import RequirementSlot, Vacancy


def classify_room_name(name: str) -> set[str]:
    """Return broad and normalized subtype labels for a Japanese room name."""
    compact = "".join(str(name).split()).casefold()
    if "エコノミーシングル" in compact:
        return {"single", "economy_single"}
    if any(
        token in compact
        for token in ("ワイドスペースシングル", "キングシングル", "プレミアムプラス")
    ):
        return {"single", "large_single"}
    if "シングル" in compact:
        return {"single", "standard_single"}
    if "エコノミーダブル" in compact:
        return {"multi", "economy_double"}
    if "ダブル" in compact:
        return {"multi", "double"}
    if "ツイン" in compact:
        return {"multi", "twin"}
    if any(token in compact for token in ("トリプル", "3ベッド")):
        return {"multi", "triple"}
    return set()


def match_vacancies(slot: RequirementSlot, vacancies: list[Vacancy]) -> list[Vacancy]:
    """Return vacancies matching one independently configured slot."""
    if slot.state != "active":
        return []
    exact_names = {"".join(item.split()).casefold() for item in slot.exact_names if item.strip()}
    keywords = ["".join(item.split()).casefold() for item in slot.keywords if item.strip()]
    subtypes = set(slot.subtypes)
    has_explicit_selector = bool(exact_names or keywords or subtypes)
    result: list[Vacancy] = []
    for vacancy in vacancies:
        if slot.smoking != "any" and vacancy.smoking != slot.smoking:
            continue
        if slot.inventory == "general" and vacancy.general <= 0:
            continue
        if slot.inventory == "member" and vacancy.member <= 0:
            continue
        if slot.inventory == "either" and vacancy.general <= 0 and vacancy.member <= 0:
            continue
        compact = "".join(vacancy.room.split()).casefold()
        labels = classify_room_name(vacancy.room)
        selector_match = (
            compact in exact_names
            or any(keyword in compact for keyword in keywords)
            or bool(labels & subtypes)
        )
        if has_explicit_selector and not selector_match:
            continue
        if not has_explicit_selector and slot.category not in labels:
            continue
        result.append(vacancy)
    return result


def availability_signature(vacancies: list[Vacancy]) -> str:
    """Return a stable hash for matched room, plan, inventory, and price data."""
    normalized = sorted(
        (
            item.room,
            item.smoking,
            item.plan,
            item.general,
            item.member,
            item.general_price,
            item.member_price,
        )
        for item in vacancies
    )
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
