"""Недельный итог: воскресенье 20:00 по Нячангу, не чаще раза за ISO-неделю."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

log = logging.getLogger("splitbot.weekly")
TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def due_week(now: datetime, last_sent: str | None) -> str | None:
    """Ключ недели последнего прошедшего воскресенья 20:00, если по нему итог ещё не слали."""
    now = now.astimezone(TZ)
    sunday = (now - timedelta(days=(now.weekday() + 1) % 7)).replace(hour=20, minute=0, second=0, microsecond=0)
    if sunday > now:
        sunday -= timedelta(days=7)
    y, w, _ = sunday.isocalendar()
    key = f"{y}-W{w:02d}"
    return None if key == last_sent else key


async def tick(svc, bot, chat_id: int, db, now: datetime | None = None) -> bool:
    key = due_week(now or datetime.now(TZ), db.kv_get("last_report"))
    if key is None:
        return False
    rep = svc.balance()
    await bot.send_message(chat_id, "📊 Итог недели\n" + rep.text, reply_markup=rep.kb)
    db.kv_set("last_report", key)  # только после успешной отправки
    return True


async def loop(svc, bot, chat_id: int, db) -> None:
    while True:
        try:
            await tick(svc, bot, chat_id, db)
        except Exception:
            log.exception("недельный итог не ушёл, повторю через минуту")
        await asyncio.sleep(60)
