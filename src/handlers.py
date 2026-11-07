"""Handlers for the /purge command and its inline keyboard."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

import config
import docker_ops
import ui

logger = logging.getLogger("HousekeepingBot")


def _is_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id in config.ADMIN_USER_IDS)


async def _edit(query, text: str) -> None:
    try:
        await query.edit_message_text(text)
    except Exception:
        if query.message:
            await query.message.reply_text(text)


async def cmd_purge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return

    await update.message.reply_text(
        "What would you like to prune?\n\n"
        "Dangling only runs docker system prune -f.\n"
        "All unused images runs docker system prune -af.",
        reply_markup=ui.purge_keyboard(),
    )


async def handle_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    if not _is_admin(update):
        return

    action, choice = ui.parse_callback(query.data)
    if action != "purge":
        return

    if choice == ui.PURGE_CANCEL:
        await _edit(query, "Purge cancelled.")
        return

    command = docker_ops.command_for(choice)
    if command is None:
        await _edit(query, "Unknown purge option.")
        return

    await _edit(query, f"Running {command}...")

    result = await docker_ops.prune(choice)
    await _edit(query, docker_ops.format_result(result))
