"""Inline keyboards and callback payloads for the housekeeping bot."""

from typing import Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

CALLBACK_PREFIX = "hk"

PURGE_DANGLING = "dangling"
PURGE_ALL = "all"
PURGE_CANCEL = "cancel"


def _callback(action: str, value: str) -> str:
    return f"{CALLBACK_PREFIX}:{action}:{value}"


def parse_callback(data: str) -> Tuple[str, str]:
    """Returns (action, value) for a callback payload."""
    parts = (data or "").split(":")
    if len(parts) < 3 or parts[0] != CALLBACK_PREFIX:
        return "", ""
    return parts[1], parts[2]


def purge_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Dangling only (system prune -f)",
                    callback_data=_callback("purge", PURGE_DANGLING),
                ),
            ],
            [
                InlineKeyboardButton(
                    "All unused images (system prune -af)",
                    callback_data=_callback("purge", PURGE_ALL),
                ),
            ],
            [
                InlineKeyboardButton(
                    "Cancel",
                    callback_data=_callback("purge", PURGE_CANCEL),
                ),
            ],
        ]
    )
