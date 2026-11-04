"""Очереди: кто следующий, чистая логика по счётчикам и давности хода."""
from __future__ import annotations

from splitbot.config import NAMES


def next_turn(counts: dict[str, int], last: dict[str, int] | None = None) -> str:
    """Минимальный счётчик; при равенстве тот, чей последний ход был раньше всех
    (last: имя → номер хода, больше = свежее; нет хода = раньше всех); дальше порядок NAMES."""
    last = last or {}
    return min(NAMES, key=lambda n: (counts.get(n, 0), last.get(n, -1), NAMES.index(n)))


def equalize_offsets(counts: dict[str, int]) -> dict[str, int]:
    """Поправки, после которых у всех счётчик равен максимальному. Дальше порядок задаёт история ходов."""
    m = max(counts.get(n, 0) for n in NAMES)
    return {n: m - counts.get(n, 0) for n in NAMES}
