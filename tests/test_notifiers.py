from unittest.mock import MagicMock, patch

import pytest

from toyoko_watch.models import NotificationTarget, Vacancy
from toyoko_watch.monitor import MatchEvent
from toyoko_watch.notifiers import (
    DeliveryTracker,
    deliver_targets,
    format_availability_message,
    send_smtp,
)


def match_event():
    return MatchEvent(
        task_id="task",
        task_name="横滨周六",
        slot_id="single",
        slot_label="单人房",
        hotel_id="00075",
        hotel_name="東横INN横浜スタジアム前1",
        checkin="2026-11-07",
        checkout="2026-11-08",
        occupants=1,
        vacancies=[
            Vacancy(
                room="エコノミーシングル",
                smoking="non_smoking",
                plan="スタンダードプラン",
                general=1,
                member=2,
                general_price=7410,
                member_price=6935,
            )
        ],
        url="https://www.toyoko-inn.com/search/result/room_plan/?hotel=00075",
    )


def targets():
    return [
        NotificationTarget("private", "自己", "private", "12345", True),
        NotificationTarget("group", "旅行群", "group", "67890", True),
    ]


def test_message_contains_all_booking_details_and_manual_confirmation_hint():
    text = format_availability_message(match_event())

    assert "横滨周六" in text
    assert "单人房" in text
    assert "東横INN横浜スタジアム前1 (00075)" in text
    assert "2026-11-07 → 2026-11-08" in text
    assert "エコノミーシングル" in text
    assert "禁烟" in text
    assert "一般1 / 会员2" in text
    assert "7410円" in text
    assert "6935円" in text
    assert "请在实际订到后手动标记“已订到”" in text


@pytest.mark.asyncio
async def test_partial_failure_retries_only_failed_target():
    tracker = DeliveryTracker(max_attempts=3)
    calls = []
    group_attempt = 0

    async def send(umo, text):
        nonlocal group_attempt
        calls.append((umo, text))
        if "GroupMessage" in umo:
            group_attempt += 1
            if group_attempt == 1:
                raise RuntimeError("offline")
        return True

    first = await deliver_targets(send, targets(), "hello", tracker, "event-1")
    second = await deliver_targets(send, targets(), "hello", tracker, "event-1")

    assert first == {"private": True, "group": False}
    assert second == {"private": True, "group": True}
    assert [umo for umo, _text in calls].count(targets()[0].umo) == 1
    assert [umo for umo, _text in calls].count(targets()[1].umo) == 2
    assert tracker.pending_ids("event-1") == []


@pytest.mark.asyncio
async def test_delivery_stops_after_three_failures():
    tracker = DeliveryTracker(max_attempts=3)
    target = targets()[:1]
    attempts = 0

    async def send(_umo, _text):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("offline")

    for _ in range(5):
        await deliver_targets(send, target, "hello", tracker, "event-2")

    assert attempts == 3
    assert tracker.pending_ids("event-2") == []
    assert tracker.failures("event-2")["private"]["error"] == "RuntimeError: offline"


def test_smtp_starttls_login_and_send_without_logging_password():
    smtp = MagicMock()
    config = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_ssl": False,
        "smtp_starttls": True,
        "smtp_user": "bot@example.com",
        "smtp_password": "secret",
        "smtp_from": "bot@example.com",
        "smtp_recipients": ["user@example.com"],
    }

    with patch("toyoko_watch.notifiers.smtplib.SMTP") as smtp_class:
        smtp_class.return_value.__enter__.return_value = smtp
        send_smtp(config, "有房", "body")

    smtp_class.assert_called_once_with("smtp.example.com", 587, timeout=30)
    smtp.starttls.assert_called_once_with()
    smtp.login.assert_called_once_with("bot@example.com", "secret")
    message = smtp.send_message.call_args.args[0]
    assert message["To"] == "user@example.com"
    assert "secret" not in message.as_string()
