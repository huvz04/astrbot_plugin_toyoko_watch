"""Regenerate the bundled hotel catalog from the official Toyoko list."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiohttp

from toyoko_watch.catalog import parse_hotel_catalog, validate_catalog

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://www.toyoko-inn.com/hotel_list/"


async def main() -> None:
    """Download, validate, and write the seed catalog."""
    timeout = aiohttp.ClientTimeout(total=30)
    async with (
        aiohttp.ClientSession(
            timeout=timeout, headers={"User-Agent": "Mozilla/5.0 ToyokoWatch/0.1"}
        ) as session,
        session.get(SOURCE_URL) as response,
    ):
        response.raise_for_status()
        content = await response.text()
    records = parse_hotel_catalog(content)
    validate_catalog(records)
    target = ROOT / "data" / "hotels.seed.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(records)} hotels to {target}")


if __name__ == "__main__":
    asyncio.run(main())
