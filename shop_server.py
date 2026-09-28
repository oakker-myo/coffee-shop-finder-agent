"""MCP server exposing the user's cafe data."""

import json
import config
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
    known = ", ".join(s["id"] for s in shops)
    raise ValueError(f"No shop with id '{shop_id}'. Known ids: {known}")


DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

@mcp.tool()
def open_shops(day: str | None = None, time: str | None = None) -> dict:
    """
        Check which cafes are open on a given day and time. Leave both empty for right now.
        day: mon, tue, wed, thu, fri, sat or sun. time: 24-hour HH:MM, e.g. 14:30.
    """
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    day = (day or DAYS[now.weekday()]).lower()[:3]
    if day not in DAYS:
        raise ValueError(f"day must be one of: {', '.join(DAYS)}")
    try:
        # Normalises "9:05" to "09:05"
        time = datetime.strptime(time, "%H:%M").strftime("%H:%M") if time else now.strftime("%H:%M")
    except ValueError:
        raise ValueError("time must be 24-hour HH:MM, e.g. 14:30") from None

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
            closed.append({**entry, "status": status})

    return {"checked": f"{day} {time}", "open": open_, "closed": closed, "hours_unknown": unknown}


DRINKS = ["latte", "iced_latte", "iced_spanish_latte"]

@mcp.tool()
def compare_prices(drink: str) -> dict:
    """
        Rank the cafes by price for one drink, cheapest first.
        drink: latte, iced_latte or iced_spanish_latte.
        Cafes with no recorded price for the drink are listed separately.
    """
    # Normalise drinks to the keys above.
    drink = drink.strip().lower().replace(" ", "_").replace("-", "_").removesuffix("s")
    if drink not in DRINKS:
        raise ValueError(f"drink must be one of: {', '.join(DRINKS)}")

    priced, missing = [], []
    for shop in _load():
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