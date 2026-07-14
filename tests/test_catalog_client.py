from pathlib import Path

import pytest

from toyoko_watch.catalog import parse_hotel_catalog, search_hotels, validate_catalog
from toyoko_watch.client import (
    ToyokoSchemaError,
    build_search_url,
    collect_room_types,
    collect_vacancies,
    extract_plan_response,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_catalog_extracts_ids_names_addresses_and_search_fields():
    records = parse_hotel_catalog((FIXTURES / "hotel_list.html").read_text(encoding="utf-8"))

    assert records == [
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
    assert [item["hotel_id"] for item in search_hotels(records, "横浜")] == [
        "00075",
        "00073",
    ]
    assert search_hotels(records, "00073")[0]["name"].endswith("前2")


def test_catalog_validation_rejects_large_drop_and_missing_defaults():
    previous = [{"hotel_id": f"{value:05d}"} for value in range(200)]
    new = [
        {
            "hotel_id": f"{value:05d}",
            "name": "hotel",
            "detail_url": f"https://www.toyoko-inn.com/search/detail/{value:05d}/",
        }
        for value in range(100)
    ]

    with pytest.raises(ValueError, match="70 percent"):
        validate_catalog(new, previous)


def test_build_search_url_contains_occupants_and_dates():
    url = build_search_url("75", "2026-11-07", "2026-11-08", occupants=2)

    assert "hotel=00075" in url
    assert "people=2" in url
    assert "start=2026-11-07" in url
    assert "end=2026-11-08" in url


def test_extract_and_collect_vacancies_from_embedded_next_data():
    plan = extract_plan_response((FIXTURES / "room_plan.html").read_text(encoding="utf-8"))
    hotel_name, vacancies = collect_vacancies(plan)

    assert hotel_name == "東横INN横浜スタジアム前1"
    assert len(vacancies) == 1
    assert vacancies[0].room == "エコノミーシングル"
    assert vacancies[0].smoking == "non_smoking"
    assert vacancies[0].general == 1
    assert vacancies[0].member_price == 6935


def test_collect_room_types_includes_zero_inventory_rooms_for_filter_setup():
    plan = extract_plan_response((FIXTURES / "room_plan.html").read_text(encoding="utf-8"))

    hotel_name, rooms = collect_room_types(plan)

    assert hotel_name == "東横INN横浜スタジアム前1"
    assert rooms == [
        {"name": "エコノミーシングル", "smoking": "non_smoking"},
        {"name": "ツイン", "smoking": "smoking"},
    ]


def test_missing_next_data_is_schema_error_not_empty_inventory():
    with pytest.raises(ToyokoSchemaError, match="__NEXT_DATA__"):
        extract_plan_response("<html><body>maintenance</body></html>")
