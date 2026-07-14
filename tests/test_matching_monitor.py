from copy import deepcopy

import pytest

from toyoko_watch.matching import (
    availability_signature,
    classify_room_name,
    match_vacancies,
)
from toyoko_watch.models import RequirementSlot, Vacancy, WatchTask
from toyoko_watch.monitor import AvailabilityState, MatchEvent, MonitorService


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("エコノミーシングル", {"single", "economy_single"}),
        ("シングル", {"single", "standard_single"}),
        ("ワイドスペースシングル", {"single", "large_single"}),
        ("エコノミーダブル", {"multi", "economy_double"}),
        ("ダブル", {"multi", "double"}),
        ("ツイン", {"multi", "twin"}),
        ("トリプル", {"multi", "triple"}),
    ],
)
def test_room_name_classification(name, expected):
    assert classify_room_name(name) == expected


def slot_data(**overrides):
    data = {
        "id": "single",
        "label": "单人房",
        "state": "active",
        "category": "single",
        "subtypes": ["economy_single"],
        "exact_names": [],
        "keywords": [],
        "occupants": 1,
        "smoking": "non_smoking",
        "inventory": "general",
    }
    data.update(overrides)
    return RequirementSlot.from_dict(data)


def vacancies():
    return [
        Vacancy("エコノミーシングル", "non_smoking", "通常", 1, 1, 7410, 6935),
        Vacancy("シングル", "smoking", "通常", 2, 2, 7600, 7100),
        Vacancy("ツイン", "non_smoking", "通常", 0, 1, 12000, 11500),
    ]


def test_matching_honors_subtype_smoking_and_inventory():
    assert match_vacancies(slot_data(), vacancies()) == [vacancies()[0]]
    member_twin = slot_data(
        id="multi",
        category="multi",
        subtypes=["twin"],
        occupants=2,
        inventory="member",
    )
    assert match_vacancies(member_twin, vacancies()) == [vacancies()[2]]


def test_exact_names_and_custom_keywords_extend_filters():
    exact = slot_data(subtypes=[], exact_names=["シングル"], smoking="any")
    keyword = slot_data(subtypes=[], keywords=["エコノミー"], smoking="any")

    assert [item.room for item in match_vacancies(exact, vacancies())] == ["シングル"]
    assert [item.room for item in match_vacancies(keyword, vacancies())] == ["エコノミーシングル"]


def test_signature_is_stable_regardless_of_vacancy_order():
    items = vacancies()
    assert availability_signature(items) == availability_signature(list(reversed(items)))


def test_match_event_round_trip_restores_vacancies():
    event = MatchEvent(
        task_id="task",
        task_name="横滨",
        slot_id="single",
        slot_label="单人",
        hotel_id="00075",
        hotel_name="横浜1",
        checkin="2026-11-07",
        checkout="2026-11-08",
        occupants=1,
        vacancies=vacancies()[:1],
        url="https://booking",
    )

    restored = MatchEvent.from_dict(event.to_dict())

    assert restored == event


def test_first_present_notifies_and_reappearance_notifies_again():
    state = AvailabilityState()

    assert state.apply_success("key", "sig") is True
    assert state.apply_success("key", "sig") is False
    assert state.apply_success("key", None) is False
    assert state.apply_success("key", "sig") is True


def test_change_notification_is_optional_but_state_is_updated():
    state = AvailabilityState()
    state.apply_success("key", "first")

    assert state.apply_success("key", "second", notify_changes=False) is False
    assert state.apply_success("key", "third", notify_changes=True) is True
    assert state.values["key"] == "third"


def test_error_does_not_clear_present_state():
    state = AvailabilityState()
    state.apply_success("key", "sig")

    state.apply_error("key", "timeout")

    assert state.values["key"] == "sig"
    assert state.errors["key"] == "timeout"


class FakeClient:
    def __init__(self):
        self.calls = []
        self.responses = {}

    async def fetch_availability(self, hotel_id, checkin, checkout, occupants, session=None):
        self.calls.append((hotel_id, checkin, checkout, occupants))
        response = self.responses[(hotel_id, occupants)]
        if isinstance(response, Exception):
            raise response
        return response


def watch_task():
    single = slot_data()
    multi = slot_data(
        id="multi",
        label="双人房",
        category="multi",
        subtypes=["twin"],
        occupants=2,
        smoking="any",
        inventory="either",
    )
    return WatchTask(
        id="task",
        name="横滨",
        enabled=True,
        hotel_ids=["00075"],
        checkin="2026-11-07",
        checkout="2026-11-08",
        slots=[single, multi],
        target_ids=["private"],
    )


@pytest.mark.asyncio
async def test_monitor_groups_requests_by_occupants_and_emits_first_hits():
    client = FakeClient()
    client.responses[("00075", 1)] = ("横浜1", vacancies()[:1], "https://single")
    client.responses[("00075", 2)] = ("横浜1", vacancies()[2:], "https://multi")
    service = MonitorService(client, AvailabilityState(), max_concurrency=2)

    events, errors = await service.run_task(watch_task())

    assert errors == []
    assert len(client.calls) == 2
    assert {event.slot_id for event in events} == {"single", "multi"}


@pytest.mark.asyncio
async def test_fulfilled_slot_is_skipped_without_stopping_other_slot():
    task = watch_task()
    task.slots[0].state = "fulfilled"
    client = FakeClient()
    client.responses[("00075", 2)] = ("横浜1", vacancies()[2:], "https://multi")
    service = MonitorService(client, AvailabilityState())

    events, errors = await service.run_task(task)

    assert errors == []
    assert len(client.calls) == 1
    assert [event.slot_id for event in events] == ["multi"]


@pytest.mark.asyncio
async def test_monitor_error_retains_previous_hit_and_retries_next_run():
    client = FakeClient()
    client.responses[("00075", 1)] = ("横浜1", vacancies()[:1], "https://single")
    client.responses[("00075", 2)] = ("横浜1", [], "https://multi")
    state = AvailabilityState()
    service = MonitorService(client, state)
    await service.run_task(watch_task())
    before = deepcopy(state.values)
    client.responses[("00075", 1)] = TimeoutError("timeout")

    events, errors = await service.run_task(watch_task())

    assert events == []
    assert len(errors) == 1
    single_key = next(key for key in before if key.endswith(":single"))
    assert state.values[single_key] == before[single_key]
