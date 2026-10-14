"""Browser chat UI for the coffee agent, for local development only."""

import logging
import agent
import config
from agent_framework.devui import serve


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("agent.tools").setLevel(logging.INFO if config.ENV == "dev" else logging.WARNING)
    agent.init_agent()
    # Loopback only, so no auth token is needed; DevUI refuses to start without auth on any other host.
    serve(entities=[agent.get_agent()], host="127.0.0.1", port=8080, auto_open=True, auth_enabled=False)


if __name__ == "__main__":
    main()