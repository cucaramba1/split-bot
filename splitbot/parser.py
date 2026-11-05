"""Разбор речи в траты: claude -p только разбирает, проверку делает validate."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from splitbot import claude
from splitbot.config import NAMES, QUEUES, Settings

MAX_AMOUNT = 50_000_000

_TRIGGER = re.compile(
    r"\d|\bк\b|\b(?:тыс|тыщ|лям|миллион|сот|двест|трист|пятьс|донг|заправ|бензин|байк|вод|купил|потратил|заплатил|отда|вернул|верн[её]т|перевёл|перевел|погас)",
    re.I)


def should_parse(text: str) -> bool:
    return bool(_TRIGGER.search(text or ""))


SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["expenses", "none"]},
        "items": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "amount": {"type": "integer"},
                           "split": {"type": "array", "items": {"type": "string"}}},
            "required": ["title", "amount", "split"]}},
        "turns": {"type": "array", "items": {
            "type": "object",
            "properties": {"queue": {"type": "string", "enum": list(QUEUES)}, "who": {"type": "string"}},
            "required": ["queue", "who"]}},
        "payments": {"type": "array", "items": {
            "type": "object",
            "properties": {"frm": {"type": "string"}, "to": {"type": "string"}, "amount": {"type": "integer"}},
            "required": ["frm", "to", "amount"]}},
        "question": {"type": ["string", "null"]},
    },
    "required": ["kind", "items", "turns", "payments", "question"],
}

SYSTEM = """Ты разбираешь сообщение из общего чата трёх друзей в общие траты. Участники: Некит (Никита), Антон, Полина.
Автор сообщения указан в запросе. «Я», «мне», «меня» означают автора.
Верни JSON строго по схеме.

Правила:
- items: траты, которые заплатил автор. У каждой title (коротко), amount (целое число в донгах) и split (имена тех, на кого делим).
- «на троих», «на всех» или без уточнения: split = все трое (Некит, Антон, Полина).
- «на двоих с X» или «мне и X»: split = автор и X. «X и Y»: split = X и Y.
- Суммы в донгах целым числом: «120к» = 120000, «1.2 ляма» = 1200000, «сто двадцать тысяч» = 120000.
- turns: очереди. «заправил байк» = queue bike, «купил воду» или «поменял бутыль» = queue water, who = кто это сделал (по умолчанию автор). Если сумма не названа явно как общая трата, это turns, а не items.
- payments: погашение долга между людьми, это НЕ трата. «Отдал Антону 50к», «вернул Полине 100к» = frm автор, to Антон/Полина. «Антон отдал мне 30к», «Полина вернула мне» = frm Антон/Полина, to автор. amount целое в донгах.
- Не придумывай сумму. Если суммы нет, а она нужна, оставь items пустым и задай короткий вопрос в question.
- Болтовня без трат и очередей: kind = none, items и turns пустые, question = null.
- Если kind = expenses, а всё понятно, question = null."""


@dataclass
class Parsed:
    items: list[dict] = field(default_factory=list)
    turns: list[dict] = field(default_factory=list)
    payments: list[dict] = field(default_factory=list)
    question: str | None = None
    none: bool = False


_ALIASES = {n.lower(): n for n in NAMES} | {"никита": "Некит"}


def _name(x: str, author: str, *, empty_is_author: bool = False) -> str | None:
    x = (x or "").strip()
    if not x:
        return author if empty_is_author else None
    return _ALIASES.get(x.lower())


def validate(raw: dict, author: str) -> Parsed:
    question = raw.get("question") or None
    items: list[dict] = []
    turns: list[dict] = []
    for it in raw.get("items") or []:
        split: list[str] = []
        bad = False
        for n in it.get("split") or []:
            m = _name(n, author)
            if m is None:
                bad = True
                question = question or f"Не знаю, кто это: {n}. На кого делим?"
            elif m not in split:
                split.append(m)
        amount = it.get("amount")
        title = str(it.get("title") or "").strip()
        if not isinstance(amount, int) or amount <= 0 or amount > MAX_AMOUNT:
            question = question or f"Не понял сумму для «{title}». Сколько?"
        elif not bad and len(split) < 2:
            question = question or f"«{title}»: на кого делим?"
        items.append({"title": title, "amount": amount if isinstance(amount, int) else 0, "split": split})
    for t in raw.get("turns") or []:
        who = _name(t.get("who", ""), author, empty_is_author=True)
        q = t.get("queue")
        if q not in QUEUES:
            question = question or "Не понял, про какую очередь речь."
        elif who is None:
            question = question or f"Не знаю, кто это: {t.get('who')}."
        else:
            turns.append({"queue": q, "who": who})
    payments: list[dict] = []
    for pm in raw.get("payments") or []:
        frm, to, amount = _name(pm.get("frm", ""), author), _name(pm.get("to", ""), author), pm.get("amount")
        if frm is None or to is None:
            question = question or f"Не знаю, кто тут: {pm.get('frm')} → {pm.get('to')}."
        elif frm == to or author not in (frm, to):
            question = question or "Погашение должно быть между тобой и кем-то. Кто кому отдал?"
        elif not isinstance(amount, int) or amount <= 0 or amount > MAX_AMOUNT:
            question = question or "Не понял сумму погашения. Сколько?"
        else:
            payments.append({"frm": frm, "to": to, "amount": amount})
    none = raw.get("kind") == "none" and not items and not turns and not payments
    return Parsed(items=items, turns=turns, payments=payments, question=question, none=none)


async def parse(text: str, author: str, *, run=claude.run_claude, s: Settings) -> Parsed:
    prompt = f"Автор сообщения: {author}\nСообщение: {text}"
    raw = await run(s, prompt, system=SYSTEM, schema=SCHEMA, timeout=90)
    return validate(raw, author)
