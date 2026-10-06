"""MCP server exposing the user's cafe data."""

import json
import config
import difflib
import math
import httpx
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


WALK_SPEED_M_PER_MIN = 80  # about 4.8 km/h
DETOUR_FACTOR = 1.3        # streets are rarely straight lines

def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Straight-line distance in metres between two points on the Earth."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


ORS_MATRIX_URL = "https://api.openrouteservice.org/v2/matrix/foot-walking"

async def _ors_routes(lat: float, lng: float, shops: list[dict]) -> list[tuple[float, float]] | None:
    """Walking (metres, seconds) to each shop via OpenRouteService, or None if unavailable."""
    if not config.ORS_API_KEY:
        return None
    locations = [[lng, lat]] + [[s["lng"], s["lat"]] for s in shops]  # ORS wants [lng, lat]
    body = {
        "locations": locations,
        "sources": [0],
        "destinations": list(range(1, len(locations))),
        "metrics": ["distance", "duration"],
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(ORS_MATRIX_URL, json=body, headers={"Authorization": config.ORS_API_KEY})
        response.raise_for_status()
        data = response.json()
        routes = list(zip(data["distances"][0], data["durations"][0]))
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return None
    # A cafe ORS can't route to comes back as null; fall back for all so the method stays consistent.
    return None if any(m is None or s is None for m, s in routes) else routes


@mcp.tool()
async def nearest_shops(lat: float, lng: float) -> dict:
    """
        Rank the cafes by walking time from a location, nearest first.
        Get lat and lng from the locate tool; never guess them.
    """
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return {"error": f"Invalid coordinates ({lat}, {lng})."}

    shops = _load()
    located = [s for s in shops if s.get("lat") is not None and s.get("lng") is not None]
    routes = await _ors_routes(lat, lng, located)

    ranked = []
    for i, shop in enumerate(located):
        if routes:
            metres, minutes, prefix = routes[i][0], max(1, round(routes[i][1] / 60)), ""
        else:
            metres = _haversine_m(lat, lng, shop["lat"], shop["lng"]) * DETOUR_FACTOR
            minutes, prefix = max(1, round(metres / WALK_SPEED_M_PER_MIN)), "about "
        distance = f"{round(metres, -1):.0f} m" if metres < 1000 else f"{metres / 1000:.1f} km"
        entry = {"id": shop["id"], "name": shop["name"], "walk": f"{prefix}{distance}, {minutes} min walk", "walk_min": minutes}
        if shop.get("address"):
            entry["address"] = shop["address"]
        ranked.append((routes[i][1] if routes else metres, entry))

    ranked = [entry for _, entry in sorted(ranked, key=lambda pair: pair[0])]
    result = {
        "method": "walking route (OpenRouteService)" if routes else "estimate: straight-line distance x1.3 at walking pace",
        "nearest_first": ranked,
    }
    unknown = [{"id": s["id"], "name": s["name"]} for s in shops if s not in located]
    if unknown:
        result["cafes_without_coordinates"] = unknown
    if ranked and ranked[0]["walk_min"] > 60:
        result["note"] = "The nearest cafe is over an hour's walk away. Check with the user that the location is right."
    return result


if __name__ == "__main__":
    mcp.run()  # stdio transport by default