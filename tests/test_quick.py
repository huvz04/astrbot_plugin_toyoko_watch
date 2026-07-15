from datetime import date

import pytest

from toyoko_watch.quick import build_quick_task, parse_quick_stay, quick_task_id


def test_quick_dates_use_nearest_future_occurrence():
    assert parse_quick_stay("1106", "1108", date(2026, 7, 15)) == (
        "2026-11-06",
        "2026-11-08",
    )


def test_quick_dates_roll_past_checkin_to_next_year():
    assert parse_quick_stay("0106", "0108", date(2026, 7, 15)) == (
        "2027-01-06",
        "2027-01-08",
    )


def test_quick_dates_support_cross_year_checkout():
    assert parse_quick_stay("1231", "0102", date(2026, 7, 15)) == (
        "2026-12-31",
        "2027-01-02",
    )


@pytest.mark.parametrize(
    ("start", "end"),
    [("1131", "1201"), ("1106", "1106"), ("1106", "1207"), ("116", "1108")],
)
def test_quick_dates_reject_invalid_or_out_of_range_stays(start, end):
    with pytest.raises(ValueError):
        parse_quick_stay(start, end, date(2026, 7, 15))


def test_quick_task_contains_single_and_multi_defaults():
    data = build_quick_task(
        "00075",
        "東横INN横浜スタジアム前1",
        "2026-11-06",
        "2026-11-08",
        "private-123",
    )

    assert data["id"] == quick_task_id("00075", "2026-11-06", "2026-11-08")
    assert data["hotel_ids"] == ["00075"]
    assert data["target_ids"] == ["private-123"]
    assert data["enabled"] is True
    assert [(slot["id"], slot["occupants"]) for slot in data["slots"]] == [
        ("single", 1),
        ("multi", 2),
    ]
    assert data["slots"][0]["subtypes"] == [
        "economy_single",
        "standard_single",
        "large_single",
    ]
    assert data["slots"][1]["subtypes"] == [
        "economy_double",
        "double",
        "twin",
        "triple",
    ]
