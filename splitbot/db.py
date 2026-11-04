"""SQLite: участники, черновики, траты, очереди, переводы."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from splitbot.config import NAMES
from splitbot.money import Expense, Transfer

SCHEMA = """
CREATE TABLE IF NOT EXISTS members(tg_id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS drafts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, author TEXT NOT NULL, payload TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', card_msg_id INTEGER, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS expenses(
  id INTEGER PRIMARY KEY AUTOINCREMENT, draft_id INTEGER, payer TEXT NOT NULL, title TEXT,
  amount INTEGER NOT NULL, split TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS turns(
  id INTEGER PRIMARY KEY AUTOINCREMENT, draft_id INTEGER, queue TEXT NOT NULL, member TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS queue_base(
  queue TEXT NOT NULL, member TEXT NOT NULL, base INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(queue, member));
CREATE TABLE IF NOT EXISTS pay_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT, frm TEXT NOT NULL, to_ TEXT NOT NULL, amount INTEGER NOT NULL,
  paid_by TEXT, paid_at TEXT);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class DB:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.c = sqlite3.connect(path, check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.executescript(SCHEMA)
        self.c.commit()

    # участники
    def add_member(self, tg_id: int, name: str) -> bool:
        try:
            with self.c:
                self.c.execute("INSERT INTO members(tg_id, name) VALUES(?,?)", (tg_id, name))
            return True
        except sqlite3.IntegrityError:
            return False

    def member_name(self, tg_id: int) -> str | None:
        r = self.c.execute("SELECT name FROM members WHERE tg_id=?", (tg_id,)).fetchone()
        return r["name"] if r else None

    def members(self) -> dict[int, str]:
        return {r["tg_id"]: r["name"] for r in self.c.execute("SELECT tg_id, name FROM members")}

    # черновики
    def create_draft(self, author: str, payload: dict) -> int:
        with self.c:
            cur = self.c.execute("INSERT INTO drafts(author, payload, created) VALUES(?,?,?)",
                                 (author, json.dumps(payload, ensure_ascii=False), _now()))
        return cur.lastrowid

    def get_draft(self, id: int) -> dict | None:
        r = self.c.execute("SELECT * FROM drafts WHERE id=?", (id,)).fetchone()
        if not r:
            return None
        return {"id": r["id"], "author": r["author"], "payload": json.loads(r["payload"]),
                "status": r["status"], "card_msg_id": r["card_msg_id"]}

    def set_card(self, id: int, msg_id: int) -> None:
        with self.c:
            self.c.execute("UPDATE drafts SET card_msg_id=? WHERE id=?", (msg_id, id))

    def save_draft(self, id: int) -> bool:
        with self.c:  # одна транзакция: статус и записи вместе
            cur = self.c.execute("UPDATE drafts SET status='saved' WHERE id=? AND status='pending'", (id,))
            if cur.rowcount == 0:
                return False
            r = self.c.execute("SELECT payload FROM drafts WHERE id=?", (id,)).fetchone()
            p = json.loads(r["payload"])
            for it in p.get("items", []):
                self.c.execute("INSERT INTO expenses(draft_id, payer, title, amount, split) VALUES(?,?,?,?,?)",
                               (id, p["payer"], it["title"], it["amount"],
                                json.dumps(it["split"], ensure_ascii=False)))
            for t in p.get("turns", []):
                self.c.execute("INSERT INTO turns(draft_id, queue, member) VALUES(?,?,?)",
                               (id, t["queue"], t["who"]))
        return True

    def cancel_draft(self, id: int) -> bool:
        with self.c:
            cur = self.c.execute("UPDATE drafts SET status='cancelled' WHERE id=? AND status='pending'", (id,))
        return cur.rowcount > 0

    def last_saved_draft(self, author: str) -> int | None:
        r = self.c.execute("SELECT id FROM drafts WHERE author=? AND status='saved' ORDER BY id DESC LIMIT 1",
                           (author,)).fetchone()
        return r["id"] if r else None

    def undo_draft(self, id: int) -> bool:
        with self.c:
            cur = self.c.execute("UPDATE drafts SET status='undone' WHERE id=? AND status='saved'", (id,))
            if cur.rowcount == 0:
                return False
            self.c.execute("DELETE FROM expenses WHERE draft_id=?", (id,))
            self.c.execute("DELETE FROM turns WHERE draft_id=?", (id,))
        return True

    # деньги
    def all_expenses(self) -> list[Expense]:
        return [Expense(r["payer"], r["amount"], tuple(json.loads(r["split"])))
                for r in self.c.execute("SELECT * FROM expenses ORDER BY id")]

    def all_paid(self) -> list[Transfer]:
        return [Transfer(r["frm"], r["to_"], r["amount"])
                for r in self.c.execute("SELECT * FROM pay_items WHERE paid_by IS NOT NULL ORDER BY id")]

    # очереди
    def queue_counts(self, queue: str) -> dict[str, int]:
        out = {n: 0 for n in NAMES}
        for r in self.c.execute("SELECT member, COUNT(*) n FROM turns WHERE queue=? GROUP BY member", (queue,)):
            if r["member"] in out:
                out[r["member"]] += r["n"]
        for r in self.c.execute("SELECT member, base FROM queue_base WHERE queue=?", (queue,)):
            if r["member"] in out:
                out[r["member"]] += r["base"]
        return out

    def add_queue_base(self, queue: str, offsets: dict[str, int]) -> None:
        with self.c:
            for m, v in offsets.items():
                self.c.execute("INSERT INTO queue_base(queue, member, base) VALUES(?,?,?) "
                               "ON CONFLICT(queue, member) DO UPDATE SET base = base + excluded.base", (queue, m, v))

    # переводы
    def create_pay_item(self, t: Transfer) -> int:
        with self.c:
            cur = self.c.execute("INSERT INTO pay_items(frm, to_, amount) VALUES(?,?,?)", (t.frm, t.to, t.amount))
        return cur.lastrowid

    def mark_paid(self, item_id: int, by: str) -> Transfer | None:
        with self.c:
            r = self.c.execute("SELECT * FROM pay_items WHERE id=?", (item_id,)).fetchone()
            if not r or r["paid_by"] is not None or by not in (r["frm"], r["to_"]):
                return None
            cur = self.c.execute("UPDATE pay_items SET paid_by=?, paid_at=? WHERE id=? AND paid_by IS NULL",
                                 (by, _now(), item_id))
            if cur.rowcount == 0:
                return None
        return Transfer(r["frm"], r["to_"], r["amount"])

    # kv
    def kv_get(self, key: str) -> str | None:
        r = self.c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return r["value"] if r else None

    def kv_set(self, key: str, value: str) -> None:
        with self.c:
            self.c.execute("INSERT INTO kv(key, value) VALUES(?,?) "
                           "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
