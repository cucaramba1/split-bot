"""Деньги: чистый расчёт долгов, без Telegram и базы."""
from __future__ import annotations

from dataclasses import dataclass

from splitbot.config import NAMES


@dataclass(frozen=True)
class Expense:
    payer: str
    amount: int
    split: tuple[str, ...]


@dataclass(frozen=True)
class Transfer:
    frm: str
    to: str
    amount: int


def net_balances(expenses: list[Expense], paid: list[Transfer]) -> dict[str, int]:
    """Плюс = ему должны. Доля = amount // len(split), остаток остаётся на плательщике."""
    net = {n: 0 for n in NAMES}
    for e in expenses:
        share = e.amount // len(e.split)
        for m in e.split:
            if m != e.payer:
                net[m] -= share
                net[e.payer] += share
    for t in paid:
        net[t.frm] += t.amount
        net[t.to] -= t.amount
    return net


def settle(net: dict[str, int]) -> list[Transfer]:
    """Жадно: самый большой должник платит самому большому кредитору."""
    order = {n: i for i, n in enumerate(NAMES)}
    debt = {n: -v for n, v in net.items() if v < 0}
    cred = {n: v for n, v in net.items() if v > 0}
    out: list[Transfer] = []
    while debt and cred:
        d = min(debt, key=lambda n: (-debt[n], order[n]))
        c = min(cred, key=lambda n: (-cred[n], order[n]))
        a = min(debt[d], cred[c])
        out.append(Transfer(d, c, a))
        debt[d] -= a
        cred[c] -= a
        if debt[d] == 0:
            del debt[d]
        if cred[c] == 0:
            del cred[c]
    out.sort(key=lambda t: order[t.frm])  # стабильная: внутри плательщика порядок выдачи
    return out


def fmt_vnd(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")
