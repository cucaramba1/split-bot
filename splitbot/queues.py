"""Очереди: кто следующий, чистая логика по счётчикам."""
from __future__ import annotations

from splitbot.config import NAMES


def next_turn(counts: dict[str, int]) -> str:
    """Минимальный счётчик, при равенстве первый по NAMES."""
    return min(NAMES, key=lambda n: (counts.get(n, 0), NAMES.index(n)))


def offsets_for_next(counts: dict[str, int], name: str) -> dict[str, int]:
    """Поправки к счётчикам: name → M, остальные двое → M+1 (M = max(counts)).

    Эффективные счётчики равны целям, дальше ход идёт по next_turn: сначала name, потом
    остальные в порядке NAMES (ничья решается по NAMES). Формула плана M, M+1, M+2
    после хода name снова ставила его первым, тест плана это не проходит.
    """
    m = max(counts.get(n, 0) for n in NAMES)
    return {n: (m if n == name else m + 1) - counts.get(n, 0) for n in NAMES}
