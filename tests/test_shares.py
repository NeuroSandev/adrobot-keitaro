import pytest

from app.services import shares


@pytest.mark.parametrize("count,expected", [
    (1, [100]), (2, [50, 50]), (3, [34, 33, 33]), (6, [17, 17, 17, 17, 16, 16]), (0, []),
])
def test_split_even(count, expected):
    assert shares.split_even(count) == expected


def test_scale_to_keeps_sum_and_proportions():
    assert shares.scale_to([60, 30]) == [67, 33]
    assert shares.scale_to([1, 1, 1]) == [34, 33, 33]
    assert shares.scale_to([0, 0]) == [50, 50]


def test_after_add():
    assert shares.after_add([100]) == [50, 50]
    assert shares.after_add([50, 50]) == [34, 33, 33]
    # пропорционально: новый получает 1/n, остальные делят остаток как раньше
    assert shares.after_add([70, 30], "proportional") == [47, 20, 33]


def test_after_remove():
    assert shares.after_remove([34, 33]) == [50, 50]
    assert shares.after_remove([60, 20], "proportional") == [75, 25]


@pytest.mark.parametrize("current", [[100], [50, 50], [34, 33, 33], [1, 99], [10, 20, 30, 40]])
def test_sum_is_always_100(current):
    for mode in ("even", "proportional"):
        assert sum(shares.after_add(current, mode)) == 100
        if len(current) > 1:
            assert sum(shares.after_remove(current[1:], mode)) == 100
