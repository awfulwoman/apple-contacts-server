from __future__ import annotations
import logging
import uvicorn
from apple_contacts_server import http, store
from apple_contacts_server.config import Config

logger = logging.getLogger("apple_contacts_server")


def create_app(config: Config):
    if not config.bearer_tokens:
        # `_authorized` returns False with no tokens configured, so every
        # request gets a 401 — the server is unusable, not open.
        logger.warning(
            "No CONTACTS_SERVER_BEARER_TOKENS configured — every request will be "
            "rejected with 401. Set CONTACTS_SERVER_BEARER_TOKENS to allow access."
        )
    store.init(config)
    http.init(config)
    return http.create_app()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = Config()
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
