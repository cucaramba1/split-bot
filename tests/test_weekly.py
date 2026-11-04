import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from splitbot import weekly
from splitbot.db import DB
from splitbot.service import Reply

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def at(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=TZ)


def test_sunday_evening_due():
    assert weekly.due_week(at(2026, 11, 8, 20, 5), None) == "2026-W45"
    assert weekly.due_week(at(2026, 11, 8, 20, 5), "2026-W45") is None


def test_sunday_before_eight_is_previous_week():
    assert weekly.due_week(at(2026, 11, 8, 19, 59), "2026-W44") is None


def test_woke_up_tuesday_sends_once():
    assert weekly.due_week(at(2026, 11, 10, 9), "2026-W44") == "2026-W45"
    assert weekly.due_week(at(2026, 11, 10, 9), "2026-W45") is None


def test_first_run_does_not_spam_old_weeks():
    assert weekly.due_week(at(2026, 11, 10, 9), None) == "2026-W45"


def test_other_timezone_input_is_converted():
    utc = datetime(2026, 11, 8, 13, 30, tzinfo=ZoneInfo("UTC"))  # 20:30 в Нячанге
    assert weekly.due_week(utc, None) == "2026-W45"


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text))


class FakeSvc:
    def balance(self):
        return Reply("Антон → Некит: 40 000")


def test_tick_sends_once_and_remembers(tmp_path):
    db, bot = DB(tmp_path / "w.db"), FakeBot()
    now = at(2026, 11, 10, 9)
    assert asyncio.run(weekly.tick(FakeSvc(), bot, 5, db, now)) is True
    assert asyncio.run(weekly.tick(FakeSvc(), bot, 5, db, now)) is False
    assert len(bot.sent) == 1 and bot.sent[0][1].startswith("📊 Итог недели\n")
    assert db.kv_get("last_report") == "2026-W45"


def test_tick_failure_does_not_mark_sent(tmp_path):
    class Boom(FakeBot):
        async def send_message(self, *a, **k):
            raise RuntimeError("net")
    db = DB(tmp_path / "w.db")
    try:
        asyncio.run(weekly.tick(FakeSvc(), Boom(), 5, db, at(2026, 11, 10, 9)))
    except RuntimeError:
        pass
    assert db.kv_get("last_report") is None
