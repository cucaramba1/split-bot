import asyncio

import pytest

from splitbot.config import Settings
from splitbot.db import DB
from splitbot.money import Transfer
from splitbot.parser import Parsed
from splitbot.service import Service

ALL = ["Некит", "Антон", "Полина"]
N, A, P = 1, 2, 3
STRANGER = 999


class Fake:
    def __init__(self, parsed: Parsed):
        self.parsed, self.calls = parsed, 0

    async def __call__(self, text, author):
        self.calls += 1
        return self.parsed


def make(tmp_path, parsed=None):
    s = Settings(bot_token="t", chat_id=1, db_path=tmp_path / "t.db", logs_dir=tmp_path, data_dir=tmp_path,
                 claude_bin="claude", groq_api_key="k")
    db = DB(s.db_path)
    for i, n in ((N, "Некит"), (A, "Антон"), (P, "Полина")):
        db.add_member(i, n)
    fake = Fake(parsed or Parsed(items=[{"title": "кофе", "amount": 120_000, "split": ALL}]))
    return Service(s, db, fake, None), db, fake


def run(c):
    return asyncio.run(c)


def draft(svc, tg=N, text="кофе 120к"):
    reply, did = run(svc.handle_text(tg, text))
    return reply, did


def test_stranger_ignored(tmp_path):
    svc, db, fake = make(tmp_path)
    assert run(svc.handle_text(STRANGER, "кофе 50к")) is None
    assert fake.calls == 0


def test_chatter_skips_claude(tmp_path):
    svc, db, fake = make(tmp_path)
    assert run(svc.handle_text(N, "го в кафе")) is None
    assert fake.calls == 0


def test_none_parse_is_silent(tmp_path):
    svc, db, fake = make(tmp_path, Parsed(none=True))
    assert run(svc.handle_text(N, "купил 5 раз сказал")) is None
    assert fake.calls == 1


def test_confirm_twice_saves_once(tmp_path):
    svc, db, _ = make(tmp_path)
    _, did = draft(svc)
    assert svc.confirm(N, did).startswith("✅ Записано")
    assert svc.confirm(N, did) == "Уже записано"
    assert len(db.all_expenses()) == 1


def test_other_member_cannot_confirm(tmp_path):
    svc, db, _ = make(tmp_path)
    _, did = draft(svc)
    assert svc.confirm(A, did) == "Это не твоя трата"
    assert svc.confirm(STRANGER, did) == "Это не твоя трата"
    assert db.all_expenses() == []


def test_draft_with_question_not_saved(tmp_path):
    svc, db, _ = make(tmp_path, Parsed(items=[{"title": "x", "amount": 5, "split": ["Некит"]}], question="На кого?"))
    _, did = draft(svc)
    assert svc.confirm(N, did) == "Сначала надиктуй заново"
    assert db.all_expenses() == []
    assert db.get_draft(did)["status"] == "pending"


def test_cancelled_cannot_be_confirmed(tmp_path):
    svc, db, _ = make(tmp_path)
    _, did = draft(svc)
    assert svc.cancel(A, did) == "Это не твоя трата"
    assert "Отменено" in svc.cancel(N, did)
    assert svc.confirm(N, did) != "✅ Записано"
    assert db.all_expenses() == []


def test_turn_reports_next(tmp_path):
    svc, db, _ = make(tmp_path, Parsed(turns=[{"queue": "water", "who": "Некит"}]))
    _, did = draft(svc, text="купил воду")
    assert "Следующая бутыль воды: Антон" in svc.confirm(N, did)


def test_balance_and_paid(tmp_path):
    svc, db, _ = make(tmp_path)
    _, did = draft(svc)
    svc.confirm(N, did)
    r = svc.balance()
    assert "Антон → Некит: 40 000" in r.text
    items = {b.text: b.callback_data for row in r.kb.inline_keyboard for b in row}
    anton = next(v for k, v in items.items() if "Антон → Некит" in k)
    item = int(anton.split(":")[1])
    assert "не твой" in svc.paid(P, item)
    assert svc.paid(A, item).startswith("✅")
    assert "Антон → Некит" not in svc.balance().text


def test_repeated_balance_does_not_pile_up_items(tmp_path):
    svc, db, _ = make(tmp_path)
    _, did = draft(svc)
    svc.confirm(N, did)
    svc.balance(); svc.balance(); svc.balance()
    assert db.c.execute("SELECT COUNT(*) FROM pay_items").fetchone()[0] == 2


def test_balance_drops_stale_items_when_debt_changes(tmp_path):
    svc, db, fake = make(tmp_path)
    _, did = draft(svc)
    svc.confirm(N, did)
    svc.balance()
    fake.parsed = Parsed(items=[{"title": "ещё", "amount": 60_000, "split": ALL}])
    _, d2 = draft(svc, tg=A)
    svc.confirm(A, d2)
    r = svc.balance()
    assert db.c.execute("SELECT COUNT(*) FROM pay_items WHERE paid_by IS NULL").fetchone()[0] == len(
        [l for l in r.text.splitlines() if "→" in l])


def test_undo_only_own(tmp_path):
    svc, db, _ = make(tmp_path)
    _, did = draft(svc)
    svc.confirm(N, did)
    assert svc.undo(A, did) == "Это не твоя трата"
    assert svc.undo(N, did).startswith("↩️")
    assert db.all_expenses() == []
    assert svc.undo(N, did) == "Уже удалено"


def test_undo_ask(tmp_path):
    svc, db, _ = make(tmp_path)
    assert run_none(svc.undo_ask(STRANGER))
    assert "Нечего" in svc.undo_ask(N).text
    _, did = draft(svc)
    svc.confirm(N, did)
    r = svc.undo_ask(N)
    assert r.kb.inline_keyboard[0][0].callback_data == f"ud:{did}"


def run_none(x):
    return x is None


def test_join_rules(tmp_path):
    s = Settings(bot_token="t", chat_id=1, db_path=tmp_path / "j.db", logs_dir=tmp_path, data_dir=tmp_path,
                 claude_bin="c", groq_api_key="k")
    db = DB(s.db_path)
    svc = Service(s, db, Fake(Parsed()), None)
    assert "1/3" in svc.join(10, "Некит").text
    assert "занято" in svc.join(11, "Некит").text
    assert "уже" in svc.join(10, "Антон").text
    assert svc.join(11, "Вася") is None
    svc.join(11, "Антон"); svc.join(12, "Полина")
    assert svc.join(13, "Некит") is None


def test_queue_status_and_set(tmp_path):
    svc, db, _ = make(tmp_path)
    svc.queue_set("bike", "Полина")
    svc.queue_set("water", "Антон")
    t = svc.queue_status().text
    assert "Заправка байка: Полина" in t and "Бутыль воды: Антон" in t
    # цикл Антон -> Полина -> Некит: после Полины ход Некита, потом Антона
    _, did = draft_turn(svc, "bike", "Полина")
    svc.confirm(P, did)
    assert "Заправка байка: Некит" in svc.queue_status().text


def draft_turn(svc, queue, who):
    svc.parse_fn.parsed = Parsed(turns=[{"queue": queue, "who": who}])
    tg = {"Некит": N, "Антон": A, "Полина": P}[who]
    return run(svc.handle_text(tg, "заправил байк"))


def test_unpay_returns_debt(tmp_path):
    svc, db, _ = make(tmp_path)
    _, did = draft(svc)
    svc.confirm(N, did)
    r = svc.balance()
    item = next(int(b.callback_data[3:]) for row in r.kb.inline_keyboard for b in row if "Антон → Некит" in b.text)
    assert svc.paid(P, item).startswith("Уже")            # Полина не из пары
    assert svc.paid(N, item).startswith("✅")
    assert "Антон → Некит" not in svc.balance().text
    assert svc.unpaid(P, item).startswith("Уже")
    assert svc.unpaid(A, item).startswith("↩️")
    assert "Антон → Некит: 40 000" in svc.balance().text


def test_parse_calls_are_serialized(tmp_path):
    active = {"now": 0, "max": 0}

    async def slow(text, author):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.02)
        active["now"] -= 1
        return Parsed(none=True)

    svc, db, _ = make(tmp_path)
    svc.parse_fn = slow

    async def go():
        await asyncio.gather(*(svc.handle_text(N, f"кофе {i}0к") for i in range(4)))
    asyncio.run(go())
    assert active["max"] == 1
