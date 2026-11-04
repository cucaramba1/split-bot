"""Настройки: .env (секреты и пути)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

NAMES: tuple[str, ...] = ("Некит", "Антон", "Полина")
QUEUES: dict[str, str] = {"bike": "Заправка байка", "water": "Бутыль воды"}


@dataclass
class Settings:
    bot_token: str
    chat_id: int | None
    db_path: Path
    logs_dir: Path
    data_dir: Path
    claude_bin: str
    groq_api_key: str
    tz: str = "Asia/Ho_Chi_Minh"


def load_settings(root: Path | None = None) -> Settings:
    root = root or Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
    env = lambda k, d="": os.getenv(k, d).strip()  # noqa: E731
    data_dir = root / "data"
    return Settings(
        bot_token=env("BOT_TOKEN"),
        chat_id=int(env("CHAT_ID")) if env("CHAT_ID") else None,
        db_path=data_dir / "split.db",
        logs_dir=root / "logs",
        data_dir=data_dir,
        claude_bin=env("CLAUDE_BIN", str(Path.home() / ".npm-global/bin/claude")),
        groq_api_key=env("GROQ_API_KEY"),
    )
