"""Local tools for the user's geo questions: their location."""

import re
import httpx
from typing import Annotated
from urllib.parse import quote

from agent_framework import FunctionInvocationContext, tool

import config

POSTCODES_API = "https://api.postcodes.io/postcodes/"
ORS_GEOCODE_URL = "https://api.openrouteservice.org/geocode/search"
UK_POSTCODE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.IGNORECASE)
GEOCODE_RADIUS_KM = 20  # only match places within this distance of GEOCODE_FOCUS
STOPWORDS = {"the", "a", "an", "of", "in", "at", "near"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS}


@tool
async def locate(
    place: Annotated[str, "A UK postcode or place name, exactly as the user wrote it. Never add a town or city they did not say."],
    ctx: FunctionInvocationContext,
) -> dict:
    """
        Find the latitude and longitude of a UK postcode or place name.
        Pass lat and lng to nearest_shops to rank the cafes by walking time.
        For a place name, tell the user which place was matched (label).
    """
    result = await _lookup(place)
    if "error" in result and ctx.tools is not None:
        # Small models keep trying other places after a miss. 
        # Removing the tool for the rest of this turn leaves asking the user as the only option.
        ctx.remove_tools("locate")
    return result


async def _lookup(place: str) -> dict:
    place = place.strip()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if UK_POSTCODE.match(place):
                return await _postcode(client, place)
            return await _place_name(client, place)
    except httpx.HTTPError:
        return {"error": "The location service could not be reached. Try again shortly."}


async def _postcode(client: httpx.AsyncClient, postcode: str) -> dict:
    response = await client.get(POSTCODES_API + quote(postcode, safe=""))
    if response.status_code == 404:
        return {"error": f"'{postcode}' is not a valid UK postcode. Ask the user to check it."}
    if response.status_code != 200:
        return {"error": f"The postcode service returned an error ({response.status_code})."}
    result = response.json()["result"]
    return {"label": result["postcode"], "lat": result["latitude"], "lng": result["longitude"], "area": result.get("admin_district")}


async def _place_name(client: httpx.AsyncClient, place: str) -> dict:
    if not config.ORS_API_KEY:
        return {"error": "Place names cannot be looked up right now. Ask the user for a postcode instead."}
    params = {"text": place, "size": 5, "boundary.country": "GB"}
    if config.GEOCODE_FOCUS:
        lat, lng = config.GEOCODE_FOCUS
        params |= {
            "focus.point.lat": lat, "focus.point.lon": lng,
            "boundary.circle.lat": lat, "boundary.circle.lon": lng,
            "boundary.circle.radius": GEOCODE_RADIUS_KM,
        }
    response = await client.get(ORS_GEOCODE_URL, params=params, headers={"Authorization": config.ORS_API_KEY})
    if response.status_code != 200:
        return {"error": f"The place search returned an error ({response.status_code})."}
    features = response.json().get("features") or []
    if not features:
        return {"error": f"No UK place found for '{place}'. Ask the user for a postcode or a more specific name."}
    wanted = _words(place)
    for feature in features:
        label = feature["properties"].get("label", "")
        if wanted <= _words(label):  # every word the user typed appears in the match
            lng, lat = feature["geometry"]["coordinates"]  # GeoJSON order: [lng, lat]
            return {"label": label, "lat": lat, "lng": lng}

    return {
        "error": f"No place called '{place}' found near your area.",
        "hint": "Ask the user for a postcode or a different place name. Do not choose a place yourself.",
    }