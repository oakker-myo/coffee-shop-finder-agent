"""MCP server exposing the user's cafe data."""

import json
import config
import difflib
import math
import httpx
import re
from html.parser import HTMLParser
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Literal

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


FETCH_TIMEOUT_S = 10
FETCH_MAX_BYTES = 1_000_000
FETCH_MAX_REDIRECTS = 3
FETCH_TYPES = ("text/html", "text/plain")
FETCH_HEADERS = {"User-Agent": "coffee-shop-finder-agent/0.1 (personal project)"}
FETCH_HINT = "Tell the user the page couldn't be read, and answer from get_shop data instead."

def _same_site(a: httpx.URL, b: httpx.URL) -> bool:
    # example.com -> www.example.com is a normal redirect; another domain isn't.
    return a.host.removeprefix("www.") == b.host.removeprefix("www.")


async def _fetch(url: str) -> dict:
    """GET a page on the cafe's own site. Returns {"url", "html"} or {"error", "hint"}."""
    start = current = httpx.URL(url)
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_S, headers=FETCH_HEADERS) as client:
            for _ in range(FETCH_MAX_REDIRECTS + 1):
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        target = current.join(response.headers["location"])
                        if target.scheme not in ("http", "https") or not _same_site(start, target):
                            return {"error": f"The page redirects to another site ({target.host}).", "hint": FETCH_HINT}
                        current = target
                        continue
                    if not response.is_success:
                        return {"error": f"The site returned HTTP {response.status_code}.", "hint": FETCH_HINT}
                    ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    if ctype not in FETCH_TYPES:
                        return {"error": f"The page isn't readable text ({ctype or 'unknown type'}).", "hint": FETCH_HINT}
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body += chunk
                        if len(body) >= FETCH_MAX_BYTES:
                            break
                    html = bytes(body[:FETCH_MAX_BYTES]).decode(response.charset_encoding or "utf-8", errors="replace")
                    return {"url": str(current), "html": html}
            return {"error": "The page redirects too many times.", "hint": FETCH_HINT}
    except (httpx.HTTPError, httpx.InvalidURL, LookupError) as e:
        return {"error": f"Could not reach the page ({type(e).__name__}).", "hint": FETCH_HINT}


FETCH_MAX_CHARS = 4000
FETCH_MIN_CHARS = 200
TEXT_START = "<<<UNTRUSTED WEBSITE TEXT START>>>"
TEXT_END = "<<<UNTRUSTED WEBSITE TEXT END>>>"

SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header", "footer", "nav", "table", "ul", "ol", "dt", "dd"}

class _TextExtractor(HTMLParser):
    """Visible text only, with block tags turned into line breaks."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_tag: str | None = None
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if self._skip_tag:
            # Count only the skipped tag, so an unclosed <p> inside it can't swallow the rest of the page.
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        attrs = dict(attrs)
        style = (attrs.get("style") or "").replace(" ", "").lower()
        # Hidden text is invisible to people but a common place to plant instructions.
        hidden = "hidden" in attrs or attrs.get("aria-hidden") == "true" or "display:none" in style
        if (tag in SKIP_TAGS or hidden) and tag not in VOID_TAGS:
            self._skip_tag, self._skip_depth = tag, 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self._skip_tag:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if self._skip_depth == 0:
                    self._skip_tag = None
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip_tag:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


@mcp.tool()
async def fetch_shop_page(shop_id: str, page: Literal["website", "menu"] = "website") -> dict:
    """
        Read a cafe's own website or menu page, live. Use this for things get_shop doesn't have: food, specials, events, news, or whether the menu has changed.
        Use get_shop for hours, prices and the user's notes.
    """
    shop = next((s for s in _load() if s["id"] == shop_id), None)
    if shop is None:
        return {"error": f"No shop with id '{shop_id}'.", "hint": "Call list_shops for valid ids."}
    url = shop.get("menu_url" if page == "menu" else "website")
    if not url:
        hint = "Try page='website' instead." if page == "menu" else FETCH_HINT
        return {"error": f"No {page} page recorded for {shop['name']}.", "hint": hint}

    result = await _fetch(url)
    if "error" in result:
        return result
    # Strip anything marker-like so the page can't close the untrusted block early.
    text = re.sub(r"<{3,}|>{3,}", "", _html_to_text(result["html"]))
    out = {"shop": shop["name"], "url": result["url"]}
    if len(text) > FETCH_MAX_CHARS:
        text = text[:FETCH_MAX_CHARS].rsplit("\n", 1)[0]
        out["truncated"] = True
    if len(text) < FETCH_MIN_CHARS:
        out["note"] = ("Very little text on this page; it is probably built with JavaScript or shows the menu as images. "
                       "Answer from get_shop data instead.")
    out["content"] = f"{TEXT_START}\n{text}\n{TEXT_END}"
    return out


if __name__ == "__main__":
    mcp.run()  # stdio transport by default