"""Стартовые долги (05.11.2026). Идемпотентно: повторный запуск ничего не дублирует.
Запуск: .venv/bin/python scripts/seed_debts.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from splitbot.config import load_settings
from splitbot.db import DB
from splitbot.money import fmt_vnd, net_balances, settle

DEBTS = [("Некит", "Полина", 10_900_000), ("Некит", "Антон", 75_000)]

db = DB(load_settings().db_path)
for frm, to, amount in DEBTS:
    print(f"{frm} → {to} {fmt_vnd(amount)}:", "записан" if db.add_opening_debt(frm, to, amount) else "уже есть")
for t in settle(net_balances(db.all_expenses(), db.all_paid())):
    print("итог:", t.frm, "→", t.to, fmt_vnd(t.amount))
