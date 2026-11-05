"""Тексты и клавиатуры бота."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from splitbot.config import NAMES, QUEUES
from splitbot.money import Transfer, fmt_vnd
from splitbot.parser import Parsed


def _who(split: list[str]) -> str:
    return "на троих" if set(split) == set(NAMES) else " + ".join(split)


def draft_text(author: str, p: Parsed) -> str:
    lines: list[str] = []
    by_payer: dict[str, list[dict]] = {}
    for it in p.items:
        by_payer.setdefault(it.get("payer") or author, []).append(it)
    for payer, its in by_payer.items():
        lines.append(f"{payer} заплатил:")
        for it in its:
            lines.append(f"  {it['title']}  {fmt_vnd(it['amount'])}  {_who(it['split'])}")
        lines.append(f"Итого {fmt_vnd(sum(it['amount'] for it in its))}")
    for pm in p.payments:
        lines.append(f"💸 Погашение: {pm['frm']} → {pm['to']}  {fmt_vnd(pm['amount'])}")
    for t in p.turns:
        lines.append(f"🔁 {QUEUES[t['queue']]}: {t['who']}")
    if p.question:
        lines.append(f"❓ {p.question}")
    return "\n".join(lines)


def draft_kb(draft_id: int, has_question: bool) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text="❌ Отмена", callback_data=f"no:{draft_id}")]
    if not has_question:
        row.insert(0, InlineKeyboardButton(text="✅ Записать", callback_data=f"ok:{draft_id}"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def settle_text(transfers: list[Transfer]) -> str:
    if not transfers:
        return "Всё ровно, никто никому не должен 🤝"
    return "\n".join(f"{t.frm} → {t.to}: {fmt_vnd(t.amount)}" for t in transfers)


def pay_kb(items: list[tuple[int, Transfer]]) -> InlineKeyboardMarkup | None:
    if not items:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ {t.frm} → {t.to} оплачено", callback_data=f"pd:{i}")]
        for i, t in items])


def pay_menu_kb(items: list[tuple[int, Transfer]]) -> InlineKeyboardMarkup:
    """Второй экран /balance: переводы по одному плюс «Назад»."""
    rows = [[InlineKeyboardButton(text=f"✅ {t.frm} → {t.to} оплачено", callback_data=f"pd:{i}")] for i, t in items]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="pm:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def balance_kb(has_transfers: bool) -> InlineKeyboardMarkup | None:
    """Первый экран /balance: одна кнопка, чтобы не промахнуться по конкретному переводу."""
    if not has_transfers:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💸 Оплачено", callback_data="pm:open")]])


def queue_text(next_by_queue: dict[str, str]) -> str:
    return "\n".join(f"{QUEUES[q]}: {n}" for q, n in next_by_queue.items())
