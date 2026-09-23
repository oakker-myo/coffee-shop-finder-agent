import os
from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.getenv("PROVIDER", "openai")  # "openai" local, "foundry" deployed
TIMEZONE = os.getenv("TIMEZONE", "Europe/London")
ENV = os.getenv("ENV", "dev")

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")  # None = api.openai.com
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL")

FOUNDRY_PROJECT_ENDPOINT = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
FOUNDRY_MODEL = os.getenv("FOUNDRY_MODEL")

APPLICATIONINSIGHTS_CONNECTION_STRING = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")