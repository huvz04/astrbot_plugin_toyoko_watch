"""Asynchronous Toyoko Inn availability-page client."""

from __future__ import annotations

import asyncio
import html
import json
import re
from urllib.parse import urlencode

import aiohttp

from .models import Vacancy

SEARCH_URL = "https://www.toyoko-inn.com/search/result/room_plan/"
NEXT_DATA_RE = re.compile(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.DOTALL)


class ToyokoSchemaError(RuntimeError):
    """The official page no longer contains the expected inventory schema."""


def build_search_url(hotel_id: str, checkin: str, checkout: str, occupants: int = 1) -> str:
    """Build an official availability-search URL."""
    query = urlencode(
        {
            "hotel": str(hotel_id).zfill(5),
            "people": int(occupants),
            "room": 1,
            "smoking": "all",
            "start": checkin,
            "end": checkout,
        }
    )
    return f"{SEARCH_URL}?{query}"


def extract_plan_response(html_text: str) -> dict:
    """Extract `planResponse` from the embedded Next.js data."""
    match = NEXT_DATA_RE.search(html_text)
    if not match:
        raise ToyokoSchemaError("page does not contain __NEXT_DATA__")
    try:
        data = json.loads(html.unescape(match.group(1)))
        response = data["props"]["pageProps"]["planResponse"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ToyokoSchemaError("__NEXT_DATA__ does not contain planResponse") from exc
    if not isinstance(response, dict):
        raise ToyokoSchemaError("planResponse is not an object")
    return response


def collect_vacancies(plan_response: dict) -> tuple[str, list[Vacancy]]:
    """Flatten positive room-plan inventory from a plan response."""
    vacancies: list[Vacancy] = []
    room_types = plan_response.get("roomTypeList") or []
    if not isinstance(room_types, list):
        raise ToyokoSchemaError("roomTypeList is not a list")
    for room in room_types:
        room_name = str(room.get("roomTypeName") or room.get("roomTypeId") or "")
        smoking = "smoking" if (room.get("specs") or {}).get("isSmoking") else "non_smoking"
        for plan in room.get("plans") or []:
            vacant = plan.get("vacant") or {}
            general = int(vacant.get("generalVacantRoom") or 0)
            member = int(vacant.get("membershipVacantRoom") or 0)
            if general <= 0 and member <= 0:
                continue
            price = plan.get("price") or {}
            vacancies.append(
                Vacancy(
                    room=room_name,
                    smoking=smoking,
                    plan=str(plan.get("planName") or ""),
                    general=general,
                    member=member,
                    general_price=price.get("generalPrice"),
                    member_price=price.get("membershipPrice"),
                )
            )
    return str(plan_response.get("hotelTitle") or ""), vacancies


class ToyokoClient:
    """Fetch official availability pages with bounded retries."""

    def __init__(self, timeout: int = 30, attempts: int = 2):
        self.timeout = timeout
        self.attempts = attempts

    async def fetch_availability(
        self,
        hotel_id: str,
        checkin: str,
        checkout: str,
        occupants: int,
        session: aiohttp.ClientSession | None = None,
    ) -> tuple[str, list[Vacancy], str]:
        """Return hotel name, positive vacancies, and official booking URL."""
        url = build_search_url(hotel_id, checkin, checkout, occupants)
        owns_session = session is None
        if session is None:
            session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/126 Safari/537.36"
                    )
                },
            )
        try:
            last_error: Exception | None = None
            for attempt in range(self.attempts):
                try:
                    async with session.get(url) as response:
                        response.raise_for_status()
                        page = await response.text()
                    plan = extract_plan_response(page)
                    hotel_name, vacancies = collect_vacancies(plan)
                    return hotel_name, vacancies, url
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    last_error = exc
                    if attempt + 1 < self.attempts:
                        await asyncio.sleep(2)
            assert last_error is not None
            raise last_error
        finally:
            if owns_session:
                await session.close()
