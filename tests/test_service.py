from pathlib import Path

import pytest

from toyoko_watch.models import Vacancy
from toyoko_watch.service import ToyokoWatchService

SEED = [
    {
        "hotel_id": "00075",
        "name": "東横INN横浜スタジアム前1",
        "region": "関東",
        "prefecture": "神奈川県",
        "city": "横浜市",
        "address": "神奈川県横浜市中区山下町205-1",
        "detail_url": "https://www.toyoko-inn.com/search/detail/00075/",
    },
    {
        "hotel_id": "00073",
        "name": "東横INN横浜スタジアム前2",
        "region": "関東",
        "prefecture": "神奈川県",
        "city": "横浜市",
        "address": "神奈川県横浜市中区山下町205-3",
        "detail_url": "https://www.toyoko-inn.com/search/detail/00073/",
    },
]


class FakeClient:
    def __init__(self):
        self.vacancies = [Vacancy("エコノミーシングル", "non_smoking", "通常", 1, 1, 7410, 6935)]

    async def fetch_availability(self, hotel_id, checkin, checkout, occupants, session=None):
        values = self.vacancies if occupants == 1 else []
        return "横浜", values, f"https://booking/{hotel_id}/{occupants}"


def target(target_id="private", kind="private", number="12345"):
    return {
        "id": target_id,
        "label": target_id,
        "kind": kind,
        "number": number,
        "enabled": True,
    }


def enabled_task():
    return {
        "id": "task",
        "name": "横滨",
        "enabled": True,
        "hotel_ids": ["00075"],
        "checkin": "2026-11-07",
        "checkout": "2026-11-08",
        "slots": [
            {
                "id": "single",
                "label": "单人房",
                "state": "active",
                "category": "single",
                "subtypes": ["economy_single"],
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
                "subtypes": ["double", "twin"],
                "exact_names": [],
                "keywords": [],
                "occupants": 2,
                "smoking": "any",
                "inventory": "either",
            },
        ],
        "target_ids": ["private"],
        "email_enabled": False,
        "notify_changes": False,
        "interval_seconds": 300,
    }


def make_service(tmp_path: Path, qq_sender=None):
    async def default_sender(_umo, _text):
        return True

    return ToyokoWatchService(
        data_dir=tmp_path,
        seed_catalog=SEED,
        config={"smtp_enabled": False, "max_concurrency": 2},
        client=FakeClient(),
        qq_sender=qq_sender or default_sender,
    )


def test_first_start_creates_paused_yokohama_tasks_and_local_catalog(tmp_path):
    service = make_service(tmp_path)

    assert len(service.hotels) == 2
    assert [task.enabled for task in service.tasks] == [False, False]
    assert [task.hotel_ids for task in service.tasks] == [
        ["00075", "00073"],
        ["00075", "00073"],
    ]
    assert (tmp_path / "hotels.json").exists()
    assert (tmp_path / "tasks.json").exists()


def test_manual_fulfillment_changes_only_selected_slot(tmp_path):
    service = make_service(tmp_path)
    service.save_target(target())
    service.save_task(enabled_task())

    updated = service.set_slot_state("task", "single", "fulfilled")

    assert [slot.state for slot in updated.slots] == ["fulfilled", "active"]
    restored = service.set_slot_state("task", "single", "active")
    assert restored.slots[0].state == "active"


@pytest.mark.asyncio
async def test_first_hit_sends_once_and_unchanged_inventory_does_not_resend(tmp_path):
    calls = []

    async def sender(umo, text):
        calls.append((umo, text))
        return True

    service = make_service(tmp_path, sender)
    service.save_target(target())
    service.save_task(enabled_task())

    first = await service.check_all()
    second = await service.check_all()

    assert first["new_events"] == 1
    assert second["new_events"] == 0
    assert len(calls) == 1
    assert calls[0][0] == "aiocqhttp:FriendMessage:12345"


@pytest.mark.asyncio
async def test_failed_target_retries_without_resending_successful_target(tmp_path):
    calls = []
    group_attempts = 0

    async def sender(umo, text):
        nonlocal group_attempts
        calls.append((umo, text))
        if "GroupMessage" in umo:
            group_attempts += 1
            if group_attempts == 1:
                raise RuntimeError("offline")
        return True

    service = make_service(tmp_path, sender)
    service.save_target(target())
    service.save_target(target("group", "group", "67890"))
    data = enabled_task()
    data["target_ids"] = ["private", "group"]
    service.save_task(data)

    await service.check_all()
    await service.check_all()

    private_umo = "aiocqhttp:FriendMessage:12345"
    group_umo = "aiocqhttp:GroupMessage:67890"
    assert [umo for umo, _ in calls].count(private_umo) == 1
    assert [umo for umo, _ in calls].count(group_umo) == 2
    assert service.pending_events == {}
