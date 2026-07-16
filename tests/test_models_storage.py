import json
from pathlib import Path

import pytest

from toyoko_watch.models import NotificationTarget, WatchTask, validate_task
from toyoko_watch.storage import JsonStore


def task_data(**overrides):
    data = {
        "id": "task-1",
        "name": "横滨",
        "enabled": True,
        "hotel_ids": ["00075", "00073"],
        "checkin": "2026-11-07",
        "checkout": "2026-11-08",
        "slots": [
            {
                "id": "single",
                "label": "单人房",
                "state": "active",
                "category": "single",
                "subtypes": ["standard_single"],
                "exact_names": [],
                "keywords": [],
                "occupants": 1,
                "smoking": "any",
                "inventory": "either",
            }
        ],
        "target_ids": ["private-1"],
        "email_enabled": False,
        "notify_changes": False,
        "interval_seconds": 300,
    }
    data.update(overrides)
    return data


def test_enabled_task_requires_notification_destination():
    task = WatchTask.from_dict(task_data(target_ids=[]))

    with pytest.raises(ValueError, match="notification"):
        validate_task(task, enabled_target_ids=set(), smtp_ready=False)


def test_enabled_task_accepts_ready_email_without_qq_target():
    task = WatchTask.from_dict(task_data(target_ids=[], email_enabled=True))

    validate_task(task, enabled_target_ids=set(), smtp_ready=True)


def test_task_rejects_checkout_before_checkin():
    task = WatchTask.from_dict(task_data(checkout="2026-11-07"))

    with pytest.raises(ValueError, match="checkout"):
        validate_task(task, enabled_target_ids={"private-1"}, smtp_ready=False)


def test_task_rejects_invalid_occupant_count():
    data = task_data()
    data["slots"][0]["occupants"] = 0
    task = WatchTask.from_dict(data)

    with pytest.raises(ValueError, match="occupants"):
        validate_task(task, enabled_target_ids={"private-1"}, smtp_ready=False)


@pytest.mark.parametrize(
    ("kind", "number", "expected"),
    [
        ("private", "12345", "aiocqhttp:FriendMessage:12345"),
        ("group", "67890", "aiocqhttp:GroupMessage:67890"),
    ],
)
def test_notification_target_builds_onebot_umo(kind, number, expected):
    target = NotificationTarget(id="target", label="测试", kind=kind, number=number, enabled=True)

    assert target.umo == expected


def test_notification_target_uses_platform_instance_id():
    target = NotificationTarget(
        id="private",
        label="自己",
        kind="private",
        number="1686448912",
        enabled=True,
        platform_id="default-qq",
    )
    assert target.umo == "default-qq:FriendMessage:1686448912"
    assert target.to_dict()["platform_id"] == "default-qq"


def test_notification_target_loads_legacy_record_without_platform_id():
    target = NotificationTarget.from_dict(
        {"id": "group", "label": "群", "kind": "group", "number": "378075060"}
    )
    assert target.platform_id == "aiocqhttp"
    assert target.umo == "aiocqhttp:GroupMessage:378075060"


@pytest.mark.parametrize("platform_id", ["", "bad:id"])
def test_notification_target_rejects_invalid_platform_id(platform_id):
    target = NotificationTarget(
        id="private",
        label="自己",
        kind="private",
        number="1686448912",
        platform_id=platform_id,
    )
    with pytest.raises(ValueError, match="platform_id"):
        _ = target.umo


def test_json_store_round_trip_uses_atomic_replace(tmp_path: Path):
    store = JsonStore(tmp_path / "tasks.json", default_factory=list)

    store.save([{"id": "task-1", "name": "横滨"}])

    assert store.load() == [{"id": "task-1", "name": "横滨"}]
    assert not list(tmp_path.glob("*.tmp"))


def test_json_store_backs_up_corrupt_file(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text("{broken", encoding="utf-8")
    store = JsonStore(path, default_factory=dict)

    assert store.load() == {}
    backups = list(tmp_path.glob("state.json.corrupt-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{broken"
    assert json.loads(path.read_text(encoding="utf-8")) == {}
