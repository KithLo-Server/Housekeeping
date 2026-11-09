"""Handlers for the /purge and /ps commands."""

import html
import logging
from typing import List

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


_MAX_TABLE_CHARS = 3500


def _table_chunks(table: str, limit: int = _MAX_TABLE_CHARS) -> List[str]:
    lines = table.splitlines()
    if len(lines) <= 2:
        return ["\n".join(lines)]

    header = lines[:2]
    chunks: List[str] = []
    current = list(header)
    for line in lines[2:]:
        size = sum(len(item) + 1 for item in current) + len(line) + 1
        if size > limit and len(current) > len(header):
            chunks.append("\n".join(current))
            current = list(header)
        current.append(line)
    chunks.append("\n".join(current))
    return chunks


async def _send_table(message, table: str) -> None:
    for index, chunk in enumerate(_table_chunks(table)):
        text = f"<pre>{html.escape(chunk)}</pre>"
        if index == 0:
            try:
                await message.edit_text(text, parse_mode="HTML")
                continue
            except Exception:
                pass
        await message.reply_text(text, parse_mode="HTML")


async def cmd_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return

    args = list(context.args or [])
    subcommand = args[0].lower() if args else ""

    if subcommand == "ls" and len(args) == 1:
        status = await update.message.reply_text("Fetching images...")
        result = await docker_ops.list_images()
        if result.error:
            await status.edit_text(f"Could not list images.\n\n{result.error}")
            return
        await _send_table(status, docker_ops.format_image_table(result.images))
        return

    if subcommand == "rm" and len(args) >= 2:
        identifiers = args[1:]
        invalid = [
            identifier
            for identifier in identifiers
            if not identifier or identifier.startswith("-")
        ]
        if invalid:
            await update.message.reply_text(
                "Invalid image identifier: " + ", ".join(invalid)
            )
            return

        status = await update.message.reply_text(
            f"Removing {len(identifiers)} image(s)..."
        )
        result = await docker_ops.remove_images(identifiers)
        await status.edit_text(
            docker_ops.format_remove_result(identifiers, result)
        )
        return

    await update.message.reply_text(
        "Usage:\n/image ls\n/image rm <IDENTIFIER> [IDENTIFIER ...]"
    )


async def cmd_volume(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not _is_admin(update):
        return

    args = list(context.args or [])
    subcommand = args[0].lower() if args else ""

    if subcommand == "ls" and len(args) == 1:
        status = await update.message.reply_text("Fetching volumes...")
        result = await docker_ops.list_volumes()
        if result.error:
            await status.edit_text(f"Could not list volumes.\n\n{result.error}")
            return
        await _send_table(status, docker_ops.format_volume_table(result.volumes))
        return

    if subcommand == "rm" and len(args) >= 2:
        names = args[1:]
        invalid = [
            name for name in names if not name or name.startswith("-")
        ]
        if invalid:
            await update.message.reply_text(
                "Invalid volume name: " + ", ".join(invalid)
            )
            return

        status = await update.message.reply_text(
            f"Removing {len(names)} volume(s)..."
        )
        result = await docker_ops.remove_volumes(names)
        await status.edit_text(
            docker_ops.format_volume_remove_result(names, result)
        )
        return

    await update.message.reply_text(
        "Usage:\n/volume ls\n/volume rm <NAME> [NAME ...]"
    )


async def _container_action(
    update: Update,
    identifiers: List[str],
    gerund: str,
    action,
    formatter,
) -> None:
    invalid = [
        identifier
        for identifier in identifiers
        if not identifier or identifier.startswith("-")
    ]
    if invalid:
        await update.message.reply_text(
            "Invalid container identifier: " + ", ".join(invalid)
        )
        return

    status = await update.message.reply_text(
        f"{gerund} {len(identifiers)} container(s)..."
    )
    result = await action(identifiers)
    await status.edit_text(formatter(identifiers, result))


async def cmd_container(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not _is_admin(update):
        return

    args = list(context.args or [])
    subcommand = args[0].lower() if args else ""

    if subcommand == "ls" and len(args) == 1:
        status = await update.message.reply_text("Fetching containers...")
        result = await docker_ops.list_all_containers()
        if result.error:
            await status.edit_text(
                f"Could not list containers.\n\n{result.error}"
            )
            return
        await _send_table(
            status,
            docker_ops.format_container_table(
                result.containers, empty_message="No containers."
            ),
        )
        return

    actions = {
        "rm": (
            "Removing",
            docker_ops.remove_containers,
            docker_ops.format_container_remove_result,
        ),
        "stop": (
            "Stopping",
            docker_ops.stop_containers,
            docker_ops.format_container_stop_result,
        ),
        "start": (
            "Starting",
            docker_ops.start_containers,
            docker_ops.format_container_start_result,
        ),
        "restart": (
            "Restarting",
            docker_ops.restart_containers,
            docker_ops.format_container_restart_result,
        ),
    }
    entry = actions.get(subcommand)
    if entry and len(args) >= 2:
        gerund, action, formatter = entry
        await _container_action(
            update, args[1:], gerund, action, formatter
        )
        return

    await update.message.reply_text(
        "Usage:\n/container ls\n"
        "/container rm <ID> [ID ...]\n"
        "/container stop <ID> [ID ...]\n"
        "/container start <ID> [ID ...]\n"
        "/container restart <ID> [ID ...]"
    )


async def cmd_ps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return

    status = await update.message.reply_text("Fetching containers...")
    result = await docker_ops.list_containers()
    if result.error:
        await status.edit_text(
            f"Could not list containers.\n\n{result.error}"
        )
        return

    await _send_table(status, docker_ops.format_container_table(result.containers))


async def cmd_pull(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return

    args = list(context.args or [])
    if len(args) != 1 or not args[0] or args[0].startswith("-"):
        await update.message.reply_text("Usage: /pull <IMAGE>")
        return

    identifier = args[0]
    status = await update.message.reply_text(f"Pulling {identifier}...")
    result = await docker_ops.pull_image(identifier)
    await status.edit_text(
        docker_ops.format_pull_result(identifier, result)
    )


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
