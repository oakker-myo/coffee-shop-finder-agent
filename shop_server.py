"""MCP server exposing the user's cafe data."""

import json
import config
import difflib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

DATA_FILE = Path(__file__).parent / "data" / "shops.json"

mcp = FastMCP("coffee-shops")


def _load() -> list[dict]:
    # Read on every call so edits to shops.json apply without a restart.
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


@mcp.tool()
def list_shops() -> list[dict]:
    """
        List every cafe the user tracks, with id, name, postcode, the user's rank (1 = favourite), Google rating and review count. 
        Call get_shop for full details.
    """
    return [
        {k: shop.get(k) for k in ("id", "name", "postcode", "my_rank", "rating", "review_count")}
        for shop in _load()
    ]


@mcp.tool()
def get_shop(shop_id: str) -> dict:
    """
        Get full details for one cafe by id: location, opening hours, drink prices, rating, website and the user's own notes.
    """
    shops = _load()
    for shop in shops:
        if shop["id"] == shop_id:
            return shop
    return {
                "error": f"No shop with id '{shop_id}'.",
                "known_shops": [{"id": s["id"], "name": s["name"]} for s in shops],
            }



DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

def _next_open(hours: dict, day: str, time: str) -> str:
    """First opening after `day time`, looking up to a week ahead."""
    start = DAYS.index(day)
    for offset in range(8):  # 0 = later the same day, 7 = same day next week
        d = DAYS[(start + offset) % 7]
        for opens, _ in hours.get(d) or []:
            if offset > 0 or opens > time:
                return f"next {d} {opens}" if offset == 7 else f"{d} {opens}"
    return "No opening hours recorded this week"


@mcp.tool()
def open_shops(day: str | None = None, time: str | None = None) -> dict:
    """
        Check which cafes are open on a given day and time. Leave both empty for right now.
        day: mon, tue, wed, thu, fri, sat or sun. time: 24-hour HH:MM, e.g. 14:30.
        Closed cafes include next_open, the next day and time they open.
        Use this for "when does X open next", rather than working it out from get_shop.
    """
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    day = (day or DAYS[now.weekday()]).lower()[:3]
    if day not in DAYS:
        return {"error": f"Unknown day '{day}'.", "valid_days": DAYS}
    try:
        # Normalises "9:05" to "09:05"
        time = datetime.strptime(time, "%H:%M").strftime("%H:%M") if time else now.strftime("%H:%M")
    except ValueError:
        return {"error": f"Invalid time '{time}'. Use 24-hour HH:MM, e.g. 14:30."}

    open_, closed, unknown = [], [], []
    for shop in _load():
        ranges = shop.get("hours", {}).get(day)
        entry = {"id": shop["id"], "name": shop["name"]}
        if ranges is None:
            unknown.append(entry)
            continue
        match = next((end for start, end in ranges if start <= time < end), None)
        if match:
            open_.append({**entry, "closes": match})
        else:
            later = [start for start, _ in ranges if start > time]
            if later:
                status = f"opens at {later[0]}"
            elif ranges:
                status = "closed for the rest of the day"
            else:
                status = "closed all day"
            closed.append({**entry, "status": status, "next_open": _next_open(shop.get("hours", {}), day, time)})

    return {"checked": f"{day} {time}", "open": open_, "closed": closed, "hours_unknown": unknown}


@mcp.tool()
def compare_prices(drink: str | None = None) -> dict:
    """
        Rank drink prices across the cafes, cheapest first.
        With a drink (e.g. latte, iced latte): every cafe's price for it, plus cafes with no recorded price.
        Without a drink: every priced drink at every cafe. Use this for "cheapest drink" or "what drinks are there".
    """
    shops = _load()

    # Models sometimes send "" to mean "no drink".
    if drink is None or not drink.strip():
        items = [
            {"id": s["id"], "name": s["name"], "drink": d, "price": p}
            for s in shops
            for d, p in s.get("prices", {}).items()
        ]
        items.sort(key=lambda i: i["price"])
        return {"cheapest_first": items}

    # "Iced Latte", "iced-latte" and "lattes" all normalise to the JSON keys.
    drink = drink.strip().lower().replace(" ", "_").replace("-", "_").removesuffix("s")
    known = sorted({d for s in shops for d in s.get("prices", {})})
    if drink not in known:
        # Typos like "iced spanis latte" still match; unrelated drinks don't.
        close = difflib.get_close_matches(drink, known, n=1, cutoff=0.8)
        if not close:
            return {"error": f"No prices recorded for '{drink}'.", "drinks_with_prices": known}
        drink = close[0]


    priced, missing = [], []
    for shop in shops:
        entry = {"id": shop["id"], "name": shop["name"]}
        price = shop.get("prices", {}).get(drink)
        if price is None:
            missing.append(entry)
        else:
            priced.append({**entry, "price": price})

    priced.sort(key=lambda s: s["price"])
    return {"drink": drink, "cheapest_first": priced, "no_price_recorded": missing}


if __name__ == "__main__":
    mcp.run()  # stdio transport by default