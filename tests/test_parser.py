import asyncio
from pathlib import Path

from splitbot import parser
from splitbot.config import Settings
from splitbot.parser import should_parse, validate

ALL = ["Некит", "Антон", "Полина"]


def raw(items=None, turns=None, kind="expenses", question=None):
    return {"kind": kind, "items": items or [], "turns": turns or [], "question": question}


def item(amount=1000, split=None, title="кофе"):
    return {"title": title, "amount": amount, "split": split if split is not None else ALL}


def test_should_parse_ignores_chatter():
    assert should_parse("го в кафе вечером") is False
    assert should_parse("кофе 120к на троих") is True
    assert should_parse("заправил байк") is True
    assert should_parse("купила воду") is True


def test_valid_items():
    p = validate(raw([item(120000, title="кофе"), item(30000, ["некит", "Полина"], "чипсы")]), "Некит")
    assert p.question is None
    assert p.items[1]["split"] == ["Некит", "Полина"]


def test_unknown_name_asks():
    assert validate(raw([item(1000, ["Некит", "Вася"])]), "Некит").question is not None


def test_bad_amounts_ask():
    assert validate(raw([item(0)]), "Некит").question is not None
    assert validate(raw([item(60_000_000)]), "Некит").question is not None


def test_pair_without_partner_asks():
    assert validate(raw([item(1000, ["Некит"])]), "Некит").question is not None


def test_turn_defaults_to_author():
    p = validate(raw(turns=[{"queue": "bike", "who": ""}]), "Полина")
    assert p.turns == [{"queue": "bike", "who": "Полина"}]


def test_unknown_queue_asks():
    assert validate(raw(turns=[{"queue": "pizza", "who": "Антон"}]), "Антон").question is not None


def test_none_kind():
    assert validate(raw(kind="none"), "Некит").none is True


def test_nikita_alias_and_dedupe():
    p = validate(raw([item(1000, ["Никита", "никита", "Антон"])]), "Некит")
    assert p.items[0]["split"] == ["Некит", "Антон"] and p.question is None


def test_parse_passes_author():
    seen = {}

    async def fake(s, prompt, **kw):
        seen["prompt"] = prompt
        seen.update(kw)
        return raw([item(50000)])

    s = Settings("", None, Path("x"), Path("x"), Path("x"), "claude", "")
    p = asyncio.run(parser.parse("кофе 50к", "Антон", run=fake, s=s))
    assert "Антон" in seen["prompt"] and p.items[0]["amount"] == 50000
    assert seen["schema"] is parser.SCHEMA
