"""MCP server exposing the user's cafe data."""

import json
from pathlib import Path

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


if __name__ == "__main__":
    mcp.run()  # stdio transport by default