import asyncio

import httpx
import pytest

from splitbot import cards, stt
from splitbot.config import QUEUES, Settings
from splitbot.money import Transfer
from splitbot.parser import Parsed

ALL = ["Некит", "Антон", "Полина"]


def _parsed(question=None):
    return Parsed(
        items=[{"title": "кофе", "amount": 120_000, "split": ALL},
               {"title": "чипсы", "amount": 30_000, "split": ["Некит", "Полина"]}],
        turns=[{"queue": "bike", "who": "Антон"}], question=question)


def _settings(tmp_path, key="gsk_SECRET"):
    return Settings(bot_token="t", chat_id=1, db_path=tmp_path / "x.db", logs_dir=tmp_path,
                    data_dir=tmp_path, claude_bin="claude", groq_api_key=key)


def test_draft_text_matches_spec():
    t = cards.draft_text("Некит", _parsed())
    for part in ("Некит заплатил:", "кофе", "120 000", "на троих", "Некит + Полина", "Итого 150 000",
                 "🔁 Заправка байка: Антон"):
        assert part in t


def test_draft_with_question_has_only_cancel():
    kb = cards.draft_kb(5, True)
    buttons = [b for row in kb.inline_keyboard for b in row]
    assert len(buttons) == 1 and buttons[0].callback_data == "no:5"
    ok = [b.callback_data for row in cards.draft_kb(5, False).inline_keyboard for b in row]
    assert ok == ["ok:5", "no:5"]


def test_question_shown_in_text():
    assert "❓ На кого делим?" in cards.draft_text("Некит", _parsed("На кого делим?"))


def test_settle_empty():
    assert "Всё ровно" in cards.settle_text([])


def test_settle_and_pay_kb():
    ts = [Transfer("Антон", "Некит", 40_000)]
    assert cards.settle_text(ts) == "Антон → Некит: 40 000"
    kb = cards.pay_kb([(7, ts[0])])
    b = kb.inline_keyboard[0][0]
    assert b.callback_data == "pd:7" and "Антон → Некит" in b.text
    assert cards.pay_kb([]) is None


def test_queue_text():
    assert cards.queue_text({"bike": "Полина", "water": "Антон"}) == \
        f"{QUEUES['bike']}: Полина\n{QUEUES['water']}: Антон"


def test_no_em_dash():
    texts = [cards.draft_text("Некит", _parsed("?")), cards.settle_text([]),
             cards.settle_text([Transfer("Антон", "Некит", 1)]),
             cards.queue_text({"bike": "Полина", "water": "Антон"})]
    assert all("—" not in t for t in texts)


def test_stt_sends_ru_and_returns_text(tmp_path):
    audio = tmp_path / "v.ogg"
    audio.write_bytes(b"OggS")
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers["authorization"]
        seen["body"] = req.content
        return httpx.Response(200, text="кофе 120к\n")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await stt.transcribe(_settings(tmp_path), audio, c)

    assert asyncio.run(go()) == "кофе 120к"
    assert seen["auth"] == "Bearer gsk_SECRET"
    assert b"whisper-large-v3-turbo" in seen["body"] and b"ru" in seen["body"]
    assert b'name="language"' in seen["body"]


def test_stt_error_raises_without_key(tmp_path):
    audio = tmp_path / "v.ogg"
    audio.write_bytes(b"OggS")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429, text="slow"))) as c:
            return await stt.transcribe(_settings(tmp_path), audio, c)

    with pytest.raises(RuntimeError) as e:
        asyncio.run(go())
    assert "429" in str(e.value) and "gsk_SECRET" not in str(e.value)


def test_stt_empty_key_raises(tmp_path):
    audio = tmp_path / "v.ogg"
    audio.write_bytes(b"OggS")
    with pytest.raises(RuntimeError):
        asyncio.run(stt.transcribe(_settings(tmp_path, key=""), audio))


def test_draft_text_shows_payment():
    t = cards.draft_text("Некит", Parsed(payments=[{"frm": "Некит", "to": "Антон", "amount": 50_000}]))
    assert "Некит → Антон" in t and "50" in t


def test_draft_text_groups_by_payer():
    p = Parsed(items=[{"title": "ужин", "amount": 150_000, "split": ALL, "payer": "Антон"},
                      {"title": "кофе", "amount": 30_000, "split": ALL, "payer": "Некит"}])
    t = cards.draft_text("Некит", p)
    assert "Антон заплатил:" in t and "Некит заплатил:" in t and "ужин" in t


def test_pay_menu_kb_adds_back_button():
    kb = cards.pay_menu_kb([(7, Transfer("Антон", "Некит", 40_000))])
    assert [r[0].callback_data for r in kb.inline_keyboard] == ["pd:7", "pm:back"]
