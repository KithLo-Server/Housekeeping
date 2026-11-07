"""Telegram bot entrypoint for Docker housekeeping."""

import logging

from telegram.ext import Application, CallbackQueryHandler, CommandHandler

import config
import handlers

logger = logging.getLogger("HousekeepingBot")


def _register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("purge", handlers.cmd_purge))
    application.add_handler(CommandHandler("ps", handlers.cmd_ps))
    application.add_handler(CommandHandler("image", handlers.cmd_image))
    application.add_handler(CommandHandler("volume", handlers.cmd_volume))
    application.add_handler(CommandHandler("container", handlers.cmd_container))
    application.add_handler(CommandHandler("pull", handlers.cmd_pull))
    application.add_handler(CallbackQueryHandler(handlers.handle_callback))


def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise ValueError("HOUSEKEEPING_BOT_TOKEN environment variable is missing.")
    if not config.ADMIN_USER_IDS:
        logger.warning(
            "HOUSEKEEPING_ADMIN_USER_ID is empty: every user will be ignored."
        )

    application = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .base_url(config.TELEGRAM_API_BASE_URL)
        .base_file_url(config.TELEGRAM_API_FILE_BASE_URL)
        .local_mode(True)
        .read_timeout(config.TELEGRAM_READ_TIMEOUT)
        .write_timeout(config.TELEGRAM_WRITE_TIMEOUT)
        .connect_timeout(config.TELEGRAM_CONNECT_TIMEOUT)
        .pool_timeout(config.TELEGRAM_POOL_TIMEOUT)
        .build()
    )
    _register_handlers(application)

    logger.info("Bot is starting polling...")
    application.run_polling()


if __name__ == "__main__":
    main()
