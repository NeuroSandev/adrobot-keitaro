"""Расчёт долей офферов в потоке. Доли — целые проценты, сумма всегда 100."""

from typing import Literal

TOTAL = 100
Mode = Literal["even", "proportional"]


def split_even(count: int, total: int = TOTAL) -> list[int]:
    """100 на 3 -> [34, 33, 33]: остаток раздаётся первым по одному проценту."""
    if count <= 0:
        return []
    base, rest = divmod(total, count)
    return [base + 1 if i < rest else base for i in range(count)]


def scale_to(weights: list[int], total: int = TOTAL) -> list[int]:
    """Пропорционально масштабирует веса до total методом наибольшего остатка."""
    if not weights:
        return []
    weight_sum = sum(weights)
    if weight_sum <= 0:
        return split_even(len(weights), total)
    exact = [w * total / weight_sum for w in weights]
    result = [int(x) for x in exact]
    missing = total - sum(result)
    by_remainder = sorted(range(len(weights)), key=lambda i: exact[i] - result[i], reverse=True)
    for i in by_remainder[:missing]:
        result[i] += 1
    return result


def after_add(current: list[int], mode: Mode = "even") -> list[int]:
    """Доли после добавления оффера; новый оффер — последний элемент."""
    count = len(current) + 1
    if mode == "even" or not current:
        return split_even(count)
    new_share = TOTAL // count
    return scale_to(current, TOTAL - new_share) + [new_share]


def after_remove(remaining: list[int], mode: Mode = "even") -> list[int]:
    """Доли оставшихся офферов после удаления одного."""
    if mode == "even":
        return split_even(len(remaining))
    return scale_to(remaining)
