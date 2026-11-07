"""Environment configuration for the housekeeping bot."""

import logging
import os
from typing import FrozenSet

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger("HousekeepingBot")

# Telegram's HTTP client logs every request at INFO level.
for _quiet_logger in ("httpx", "httpcore", "telegram.request"):
    logging.getLogger(_quiet_logger).setLevel(logging.WARNING)

TELEGRAM_BOT_TOKEN = os.getenv("HOUSEKEEPING_BOT_TOKEN") or os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
)
TELEGRAM_API_BASE_URL = os.getenv(
    "TELEGRAM_API_BASE_URL", "https://api.telegram.org/bot"
)
TELEGRAM_API_FILE_BASE_URL = os.getenv(
    "TELEGRAM_API_FILE_BASE_URL", "https://api.telegram.org/file/bot"
)


def parse_admin_ids(value: str) -> FrozenSet[int]:
    """Parses a comma-separated list of allowed Telegram user IDs."""
    admin_ids = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            admin_ids.add(int(item))
        except ValueError:
            logger.warning("Ignoring invalid HOUSEKEEPING_ADMIN_USER_ID: %r", item)
    return frozenset(admin_ids)


ADMIN_USER_IDS = parse_admin_ids(os.getenv("HOUSEKEEPING_ADMIN_USER_ID", ""))

PRUNE_TIMEOUT_SECONDS = int(os.getenv("PRUNE_TIMEOUT_SECONDS", "600"))
PS_TIMEOUT_SECONDS = int(os.getenv("PS_TIMEOUT_SECONDS", "120"))
IMAGE_LIST_TIMEOUT_SECONDS = int(
    os.getenv("IMAGE_LIST_TIMEOUT_SECONDS", "120")
)
IMAGE_RM_TIMEOUT_SECONDS = int(
    os.getenv("IMAGE_RM_TIMEOUT_SECONDS", "120")
)
VOLUME_LIST_TIMEOUT_SECONDS = int(
    os.getenv("VOLUME_LIST_TIMEOUT_SECONDS", "120")
)
VOLUME_RM_TIMEOUT_SECONDS = int(
    os.getenv("VOLUME_RM_TIMEOUT_SECONDS", "120")
)
CONTAINER_RM_TIMEOUT_SECONDS = int(
    os.getenv("CONTAINER_RM_TIMEOUT_SECONDS", "120")
)

TELEGRAM_READ_TIMEOUT = float(os.getenv("TELEGRAM_READ_TIMEOUT", "120"))
TELEGRAM_WRITE_TIMEOUT = float(os.getenv("TELEGRAM_WRITE_TIMEOUT", "120"))
TELEGRAM_CONNECT_TIMEOUT = float(os.getenv("TELEGRAM_CONNECT_TIMEOUT", "30"))
TELEGRAM_POOL_TIMEOUT = float(os.getenv("TELEGRAM_POOL_TIMEOUT", "30"))
