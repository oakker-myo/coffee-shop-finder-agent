import os
from dotenv import load_dotenv

load_dotenv()

TIMEZONE = os.getenv("TIMEZONE", "Europe/London")

ENV = os.getenv("ENV", "dev")

PROVIDER = os.getenv("PROVIDER", "openai")  # "openai" (local), "azure_openai", "foundry"

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")  # None = api.openai.com
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL")

FOUNDRY_PROJECT_ENDPOINT = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
FOUNDRY_MODEL = os.getenv("FOUNDRY_MODEL")

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_MODEL = os.getenv("AZURE_OPENAI_MODEL")

REASONING_EFFORT = os.getenv("REASONING_EFFORT")

APPLICATIONINSIGHTS_CONNECTION_STRING = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")

ORS_API_KEY = os.getenv("ORS_API_KEY")  # OpenRouteService, unset = straight-line estimates only
# Optional "lat,lng" that biases place-name searches towards an area
_focus = os.getenv("GEOCODE_FOCUS")
GEOCODE_FOCUS = tuple(float(x) for x in _focus.split(",")) if _focus else None