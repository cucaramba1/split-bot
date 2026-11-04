"""Один процесс: поллинг бота + недельный итог."""
from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher

from splitbot import claude, parser, stt, weekly
from splitbot.bot import COMMANDS, build_router
from splitbot.config import load_settings
from splitbot.db import DB
from splitbot.service import Service


async def main() -> None:
    s = load_settings()
    s.logs_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[RotatingFileHandler(s.logs_dir / "splitbot.log", maxBytes=1_000_000, backupCount=3,
                                      encoding="utf-8"),
                  logging.StreamHandler()])
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # в URL запросов Groq/Telegram нет ключей, но шум не нужен
    if not s.bot_token:
        raise SystemExit("Заполни BOT_TOKEN в .env")
    db = DB(s.db_path)
    svc = Service(s, db, lambda text, author: parser.parse(text, author, run=claude.run_claude, s=s),
                  lambda path: stt.transcribe(s, path))
    bot = Bot(s.bot_token)
    dp = Dispatcher()
    dp.include_router(build_router(s, svc))
    await bot.set_my_commands(COMMANDS)
    tasks = [dp.start_polling(bot, handle_signals=False)]
    if s.chat_id is not None:
        tasks.append(weekly.loop(svc, bot, s.chat_id, db))
    else:
        logging.getLogger("splitbot").warning("CHAT_ID не задан: бот ждёт /join в группе, итог не шлётся")
    logging.getLogger("splitbot").info("Split Bot запущен")
    try:
        await asyncio.gather(*tasks)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
