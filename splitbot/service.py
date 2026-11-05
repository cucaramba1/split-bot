"""Логика бота без aiogram: проверяется тестами, bot.py только тонкий слой."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from splitbot import cards
from splitbot.config import NAMES, QUEUES
from splitbot.db import DB
from splitbot.money import fmt_vnd, net_balances, settle
from splitbot.parser import Parsed, should_parse
from splitbot.queues import cycle_from, next_turn

NOT_YOURS = "Это не твоя трата"
DONE_VERB = {"Полина": "выполнила"}  # остальные участники мужского рода


@dataclass
class Reply:
    text: str
    kb: InlineKeyboardMarkup | None = None


class Service:
    def __init__(self, s, db: DB, parse_fn, transcribe_fn):
        self.s, self.db, self.parse_fn, self.transcribe_fn = s, db, parse_fn, transcribe_fn
        self._parse_lock = asyncio.Lock()  # один claude -p за раз: лимит памяти сторожа 600 МБ

    # регистрация
    def join(self, tg_id: int, name: str) -> Reply | None:
        members = self.db.members()
        if len(members) >= len(NAMES) or name not in NAMES:
            return None
        if tg_id in members:
            return Reply(f"Ты уже {members[tg_id]}")
        if name in members.values():
            return Reply("Это имя уже занято")
        self.db.add_member(tg_id, name)
        return Reply(f"{name} в деле ({len(members) + 1}/{len(NAMES)})")

    # трата
    async def handle_text(self, tg_id: int, text: str) -> tuple[Reply, int] | None:
        author = self.db.member_name(tg_id)
        if author is None or not should_parse(text):
            return None
        async with self._parse_lock:
            p: Parsed = await self.parse_fn(text, author)
        if p.none:
            return None
        did = self.db.create_draft(author, {"payer": author, "items": p.items, "turns": p.turns,
                                            "payments": p.payments, "question": p.question})
        return Reply(cards.draft_text(author, p), cards.draft_kb(did, bool(p.question))), did

    def _own_draft(self, tg_id: int, draft_id: int) -> tuple[dict | None, str | None]:
        d = self.db.get_draft(draft_id)
        if d is None:
            return None, "Не нашёл эту трату"
        if self.db.member_name(tg_id) != d["author"]:
            return None, NOT_YOURS
        return d, None

    def confirm(self, tg_id: int, draft_id: int) -> str:
        d, err = self._own_draft(tg_id, draft_id)
        if err:
            return err
        if d["status"] in ("saved", "undone"):
            return "Уже записано"
        if d["status"] == "cancelled":
            return "Уже отменено"
        if d["payload"].get("question"):
            return "Сначала надиктуй заново"
        if not self.db.save_draft(draft_id):
            return "Уже записано"
        lines = ["✅ Записано"]
        for q in dict.fromkeys(t["queue"] for t in d["payload"].get("turns", [])):
            lines.append(f"Следующая {QUEUES[q].lower()}: {self._next(q)}")
        return "\n".join(lines)

    def cancel(self, tg_id: int, draft_id: int) -> str:
        _, err = self._own_draft(tg_id, draft_id)
        if err:
            return err
        return "❌ Отменено" if self.db.cancel_draft(draft_id) else "Уже обработано"

    # деньги
    def balance(self) -> Reply:
        transfers = settle(net_balances(self.db.all_expenses(), self.db.all_paid()))
        items = self.db.sync_pay_items(transfers)
        return Reply(cards.settle_text(transfers), cards.pay_kb(items))

    def paid(self, tg_id: int, item_id: int) -> str:
        name = self.db.member_name(tg_id)
        t = self.db.mark_paid(item_id, name) if name else None
        if t is None:
            return "Уже отмечено или это не твой перевод"
        return f"✅ {t.frm} → {t.to}: {fmt_vnd(t.amount)} оплачено"

    def unpaid(self, tg_id: int, item_id: int) -> str:
        name = self.db.member_name(tg_id)
        if not name or not self.db.unmark_paid(item_id, name):
            return "Уже снято или это не твой перевод"
        return "↩️ Отметка снята, долг снова виден в /balance"

    # очереди
    def _next(self, queue: str) -> str:
        return next_turn(self.db.queue_counts(queue), self.db.queue_last(queue))

    def queue_status(self) -> Reply:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=title, callback_data=f"qv:{q}") for q, title in QUEUES.items()]])
        return Reply(cards.queue_text({q: self._next(q) for q in QUEUES}), kb)

    def queue_view(self, queue: str) -> Reply | None:
        if queue not in QUEUES:
            return None
        who = self._next(queue)
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"✅ {who} {DONE_VERB.get(who, 'выполнил')}", callback_data=f"qd:{queue}:{who}")]])
        return Reply(f"{QUEUES[queue]}: {who}", kb)

    def queue_done(self, tg_id: int, queue: str, who: str) -> str:
        """Кнопка «выполнил»: ход засчитывается через обычный черновик, поэтому /undo его откатит."""
        name = self.db.member_name(tg_id)
        if queue not in QUEUES or name is None:
            return "Не понял"
        current = self._next(queue)
        if current != who:
            return f"Уже выполнено. Сейчас ход: {current}"
        if name != who:
            return f"Это ход {who}, не твой"
        did = self.db.create_draft(name, {"payer": name, "items": [], "turns": [{"queue": queue, "who": name}],
                                          "payments": [], "question": None})
        self.db.save_draft(did)
        return f"✅ {name}: {QUEUES[queue].lower()} выполнена. Следующий: {self._next(queue)}"

    def queue_set(self, queue: str, name: str) -> Reply:
        self.db.seed_queue(queue, cycle_from(name))
        return Reply(f"{QUEUES[queue]}: следующий {self._next(queue)}")

    # отмена записанного
    def undo_ask(self, tg_id: int) -> Reply | None:
        name = self.db.member_name(tg_id)
        if name is None:
            return None
        did = self.db.last_saved_draft(name)
        if did is None:
            return Reply("Нечего отменять")
        p = self.db.get_draft(did)["payload"]
        body = cards.draft_text(name, Parsed(items=p.get("items", []), turns=p.get("turns", []),
                                         payments=p.get("payments", [])))
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="↩️ Удалить", callback_data=f"ud:{did}")]])
        return Reply(f"Удалить последнюю запись?\n{body}", kb)

    def undo(self, tg_id: int, draft_id: int) -> str:
        _, err = self._own_draft(tg_id, draft_id)
        if err:
            return err
        return "↩️ Удалено" if self.db.undo_draft(draft_id) else "Уже удалено"
