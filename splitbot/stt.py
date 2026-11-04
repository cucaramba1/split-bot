"""Расшифровка голосовых через Groq API (не локальный Whisper)."""
from __future__ import annotations

import logging
from pathlib import Path

import httpx

from splitbot.config import Settings

log = logging.getLogger("splitbot.stt")

URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "whisper-large-v3-turbo"
HINT = ("Покупки и траты в донгах: кофе, молоко, продукты, на троих, на двоих, Антон, Полина, Некит, "
        "заправил байк, купил воду.")


async def transcribe(s: Settings, audio: Path, client: httpx.AsyncClient | None = None) -> str:
    if not s.groq_api_key:
        raise RuntimeError("GROQ_API_KEY не задан")
    own = client is None
    client = client or httpx.AsyncClient()
    try:
        r = await client.post(
            URL, headers={"Authorization": f"Bearer {s.groq_api_key}"},
            data={"model": MODEL, "language": "ru", "response_format": "text", "prompt": HINT},
            files={"file": (Path(audio).name, Path(audio).read_bytes(), "audio/ogg")}, timeout=60)
    except httpx.HTTPError as e:
        log.warning("groq: %s", type(e).__name__)
        raise RuntimeError(f"groq: {type(e).__name__}") from None
    finally:
        if own:
            await client.aclose()
    if r.status_code != 200:
        log.warning("groq: HTTP %s %s", r.status_code, r.text[:200])
        raise RuntimeError(f"groq: HTTP {r.status_code}")
    return r.text.strip()
