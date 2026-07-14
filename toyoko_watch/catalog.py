"""Toyoko Inn hotel catalog parsing, validation, and search."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

BASE_URL = "https://www.toyoko-inn.com"
DETAIL_RE = re.compile(r"^/search/detail/(?P<id>\d{5})/")
POSTAL_RE = re.compile(r"^〒\d{3}-?\d{4}\s*")
PREFECTURE_RE = re.compile(r"^(?P<prefecture>.+?[都道府県])(?P<rest>.*)$")
CITY_RE = re.compile(r"^(?P<city>.+?[市区町村])")
REGIONS = {
    "北海道": "北海道",
    "青森県": "東北",
    "岩手県": "東北",
    "宮城県": "東北",
    "秋田県": "東北",
    "山形県": "東北",
    "福島県": "東北",
    "茨城県": "関東",
    "栃木県": "関東",
    "群馬県": "関東",
    "埼玉県": "関東",
    "千葉県": "関東",
    "東京都": "関東",
    "神奈川県": "関東",
    "新潟県": "東海・甲信越・北陸",
    "富山県": "東海・甲信越・北陸",
    "石川県": "東海・甲信越・北陸",
    "福井県": "東海・甲信越・北陸",
    "山梨県": "東海・甲信越・北陸",
    "長野県": "東海・甲信越・北陸",
    "岐阜県": "東海・甲信越・北陸",
    "静岡県": "東海・甲信越・北陸",
    "愛知県": "東海・甲信越・北陸",
    "三重県": "東海・甲信越・北陸",
    "滋賀県": "近畿",
    "京都府": "近畿",
    "大阪府": "近畿",
    "兵庫県": "近畿",
    "奈良県": "近畿",
    "和歌山県": "近畿",
    "鳥取県": "中国・四国",
    "島根県": "中国・四国",
    "岡山県": "中国・四国",
    "広島県": "中国・四国",
    "山口県": "中国・四国",
    "徳島県": "中国・四国",
    "香川県": "中国・四国",
    "愛媛県": "中国・四国",
    "高知県": "中国・四国",
    "福岡県": "九州・沖縄",
    "佐賀県": "九州・沖縄",
    "長崎県": "九州・沖縄",
    "熊本県": "九州・沖縄",
    "大分県": "九州・沖縄",
    "宮崎県": "九州・沖縄",
    "鹿児島県": "九州・沖縄",
    "沖縄県": "九州・沖縄",
}


class _HotelListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[dict[str, str]] = []
        self._capture: str | None = None
        self._text: list[str] = []
        self._pending: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        href = attributes.get("href") or ""
        match = DETAIL_RE.match(href)
        if tag == "a" and match:
            self._pending = {"hotel_id": match.group("id"), "name": ""}
            self._capture = "name"
            self._text = []
        elif tag == "p" and self._pending:
            self._capture = "address"
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture == "name" and self._pending:
            self._pending["name"] = " ".join("".join(self._text).split())
            self._capture = None
            self._text = []
        elif tag == "p" and self._capture == "address" and self._pending:
            text = " ".join("".join(self._text).split())
            self._capture = None
            self._text = []
            if not text.startswith("〒"):
                return
            address = POSTAL_RE.sub("", text)
            prefecture = ""
            city = ""
            match = PREFECTURE_RE.match(address)
            if match:
                prefecture = match.group("prefecture")
                city_match = CITY_RE.match(match.group("rest"))
                city = city_match.group("city") if city_match else ""
            hotel_id = self._pending["hotel_id"]
            self.records.append(
                {
                    "hotel_id": hotel_id,
                    "name": self._pending["name"],
                    "region": REGIONS.get(prefecture, "海外" if not prefecture else ""),
                    "prefecture": prefecture,
                    "city": city,
                    "address": address,
                    "detail_url": f"{BASE_URL}/search/detail/{hotel_id}/",
                }
            )
            self._pending = None


def parse_hotel_catalog(html_text: str) -> list[dict[str, str]]:
    """Parse official hotel cards from the Toyoko hotel-list page."""
    parser = _HotelListParser()
    parser.feed(html_text)
    unique: dict[str, dict[str, str]] = {}
    for record in parser.records:
        if record["hotel_id"] not in unique:
            unique[record["hotel_id"]] = record
    return list(unique.values())


def validate_catalog(
    records: list[dict[str, Any]], previous: list[dict[str, Any]] | None = None
) -> None:
    """Reject incomplete or malformed catalog refresh results."""
    if len(records) < 100:
        raise ValueError("catalog must contain at least 100 hotels")
    if previous and len(records) < len(previous) * 0.7:
        raise ValueError("catalog fell below 70 percent of previous size")
    ids: list[str] = []
    for record in records:
        hotel_id = str(record.get("hotel_id", ""))
        name = str(record.get("name", "")).strip()
        detail_url = str(record.get("detail_url", ""))
        if not re.fullmatch(r"\d{5}", hotel_id):
            raise ValueError(f"invalid hotel id: {hotel_id}")
        if not name:
            raise ValueError(f"hotel {hotel_id} has no name")
        if detail_url != f"{BASE_URL}/search/detail/{hotel_id}/":
            raise ValueError(f"hotel {hotel_id} has invalid detail url")
        ids.append(hotel_id)
    if len(ids) != len(set(ids)):
        raise ValueError("catalog contains duplicate hotel ids")
    if not {"00073", "00075"}.issubset(ids):
        raise ValueError("catalog is missing default Yokohama hotels")


def search_hotels(
    records: list[dict[str, Any]], query: str, limit: int = 100
) -> list[dict[str, Any]]:
    """Search local hotel fields while preserving catalog order."""
    needle = "".join(str(query).casefold().split())
    if not needle:
        return records[:limit]
    result = []
    for record in records:
        haystack = "".join(
            str(record.get(key, ""))
            for key in (
                "hotel_id",
                "name",
                "region",
                "prefecture",
                "city",
                "address",
            )
        )
        if needle in "".join(haystack.casefold().split()):
            result.append(record)
            if len(result) >= limit:
                break
    return result
