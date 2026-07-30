"""! @file test_main_function.py
@brief MainFunction exact solver 的数学、确定性、缓存与穷举对照测试。
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterator
from dataclasses import FrozenInstanceError
from fractions import Fraction
from math import gcd

import pytest

from canfd_offset_optimizer.optimization.main_function import (
    MainFunctionMessage,
    calculate_group_timebase_us,
    calculate_message_d_us,
    clear_main_function_cache,
    main_function_cache_info,
    solve_main_function_partition,
    solve_main_function_proxy_exact,
)


def _message(key: str, d_us: int) -> MainFunctionMessage:
    """构造 ``offset=0`` 且 ``D=period`` 的简洁测试输入。"""
    return MainFunctionMessage(key, d_us, 0)


def _set_partitions(indices: tuple[int, ...]) -> Iterator[tuple[tuple[int, ...], ...]]:
    """枚举 message-level 无序集合 partition，仅作为小规模独立 oracle。"""
    if not indices:
        yield ()
        return
    first = indices[0]
    for partition in _set_partitions(indices[1:]):
        yield ((first,),) + partition
        for group_index in range(len(partition)):
            extended = list(partition)
            extended[group_index] = (first,) + extended[group_index]
            yield tuple(extended)


def _brute_force_cost(
    messages: tuple[MainFunctionMessage, ...],
    rho: Fraction,
) -> Fraction:
    """按原始报文枚举 Bell partition，完全不使用 D 类型压缩。"""
    best: Fraction | None = None
    for partition in _set_partitions(tuple(range(len(messages)))):
        cost = Fraction()
        for group in partition:
            timebase_us = 0
            for index in group:
                timebase_us = gcd(timebase_us, messages[index].d_us)
            cost += (
                (rho + len(group))
                * 1_000_000
                / timebase_us
            )
        if best is None or cost < best:
            best = cost
    assert best is not None
    return best


@pytest.mark.parametrize(
    ("period_us", "offset_us", "expected_d_us"),
    (
        (100_000, 15_000, 5_000),
        (100_000, 20_000, 20_000),
        (200_000, 0, 200_000),
        (500_000, 0, 500_000),
    ),
)
def test_message_d_uses_exact_integer_gcd(
    period_us: int,
    offset_us: int,
    expected_d_us: int,
) -> None:
    assert calculate_message_d_us(period_us, offset_us) == expected_d_us
    assert MainFunctionMessage("M", period_us, offset_us).d_us == expected_d_us


def test_group_timebase_is_the_gcd_of_all_message_d_values() -> None:
    first = (_message("D20", 20_000), _message("D100", 100_000))
    second = first + (_message("D50", 50_000),)
    assert calculate_group_timebase_us(first) == 20_000
    assert calculate_group_timebase_us(second) == 10_000


def test_result_satisfies_timing_partition_and_cost_invariants() -> None:
    messages = (
        MainFunctionMessage("A", 100_000, 15_000),
        MainFunctionMessage("B", 100_000, 20_000),
        MainFunctionMessage("C", 200_000, 0),
        MainFunctionMessage("D", 500_000, 0),
    )
    original = tuple(messages)
    result = solve_main_function_partition(messages, rho="1.5")

    output_keys: list[str] = []
    for group in result.groups:
        output_keys.extend(message.message_key for message in group.messages)
        expected_timebase = 0
        for message in group.messages:
            expected_timebase = gcd(expected_timebase, message.d_us)
            assert message.period_us % group.timebase_us == 0
            assert message.offset_us % group.timebase_us == 0
        assert group.timebase_us == expected_timebase
        assert group.group_proxy_cost == (
            (result.rho + group.message_count)
            * 1_000_000
            / group.timebase_us
        )

    assert sorted(output_keys) == sorted(message.message_key for message in messages)
    assert len(output_keys) == len(set(output_keys))
    assert result.cpu_proxy == sum(
        (group.group_proxy_cost for group in result.groups), start=Fraction()
    )
    assert messages == original


def test_rho_penalizes_extra_main_functions_and_exact_tie_prefers_fewer_groups() -> None:
    widely_separated = (_message("D10", 10_000), _message("D100", 100_000))
    low_fixed_cost = solve_main_function_partition(widely_separated, rho=1)
    high_fixed_cost = solve_main_function_partition(widely_separated, rho=10)
    assert len(low_fixed_cost.groups) == 2
    assert len(high_fixed_cost.groups) == 1

    # D=10/20 且 rho=1 时，合并与拆分的 Proxy 都是 300/s。
    # 正式 tie-break 必须选择更少的一个 MainFunction。
    exact_tie = solve_main_function_partition(
        (_message("D10", 10_000), _message("D20", 20_000)),
        rho=1,
    )
    assert exact_tie.cpu_proxy == 300
    assert len(exact_tie.groups) == 1


def test_compressed_subset_dp_matches_message_level_brute_force_oracle() -> None:
    """固定样本覆盖 n<=7 与重复 D，证明类型压缩不损失最优成本。"""
    generator = random.Random(20260728)
    d_pool = (5_000, 10_000, 20_000, 25_000, 50_000, 100_000)
    rhos = (Fraction(1, 2), Fraction(1), Fraction(3))
    checked = 0

    constructed = (
        (5_000,),
        (5_000, 5_000),
        (5_000, 10_000, 10_000),
        (20_000, 20_000, 50_000, 100_000),
        (5_000, 5_000, 10_000, 20_000, 20_000, 50_000, 100_000),
    )
    samples = list(constructed)
    for size in range(1, 8):
        samples.extend(
            tuple(generator.choice(d_pool) for _ in range(size))
            for _ in range(6)
        )

    for sample_index, d_values in enumerate(samples):
        messages = tuple(
            _message(f"M{sample_index}_{index}", d_us)
            for index, d_us in enumerate(d_values)
        )
        for rho in rhos:
            exact = solve_main_function_partition(messages, rho=rho)
            assert exact.cpu_proxy == _brute_force_cost(messages, rho)
            owner_by_d: dict[int, int] = {}
            for group_index, group in enumerate(exact.groups):
                for message in group.messages:
                    previous_owner = owner_by_d.setdefault(message.d_us, group_index)
                    assert previous_owner == group_index
            checked += 1
    assert checked == len(samples) * len(rhos)


def test_proxy_only_exact_path_matches_full_materialized_solver() -> None:
    generator = random.Random(20260730)
    d_pool = (1, 1_250, 1_500, 5_000, 10_000, 20_000, 50_000)
    rhos: tuple[Fraction | str | float, ...] = (
        Fraction(1, 4),
        Fraction(1),
        "1.5",
        2.25,
    )
    samples = (
        (5_000,),
        (5_000, 5_000),
        (1, 1_250, 1_500),
        (5_000, 10_000, 20_000, 50_000),
        *(
            tuple(generator.choice(d_pool) for _ in range(size))
            for size in range(1, 8)
            for _ in range(10)
        ),
    )
    for sample_index, d_values in enumerate(samples):
        messages = tuple(
            _message(f"P{sample_index}_{index}", d_us)
            for index, d_us in enumerate(d_values)
        )
        histogram = tuple(sorted(Counter(d_values).items()))
        for rho in rhos:
            proxy = solve_main_function_proxy_exact(histogram, rho)
            materialized = solve_main_function_partition(messages, rho)
            assert proxy == materialized.cpu_proxy


@pytest.mark.parametrize(
    ("histogram", "exception"),
    (
        ((), ValueError),
        (((0, 1),), ValueError),
        (((5_000, 0),), ValueError),
        (((5_000, 1), (5_000, 2)), ValueError),
        (((10_000, 1), (5_000, 1)), ValueError),
        (((5_000.0, 1),), TypeError),
        (((5_000, True),), TypeError),
    ),
)
def test_proxy_only_histogram_validation(
    histogram: tuple[tuple[object, object], ...],
    exception: type[Exception],
) -> None:
    with pytest.raises(exception):
        solve_main_function_proxy_exact(histogram)  # type: ignore[arg-type]


def test_input_order_does_not_change_canonical_partition_or_group_order() -> None:
    messages = (
        _message("D", 50_000),
        _message("B", 10_000),
        _message("A", 10_000),
        _message("C", 20_000),
        _message("E", 100_000),
    )
    shuffled = list(messages)
    random.Random(19).shuffle(shuffled)

    def signature(
        items: tuple[MainFunctionMessage, ...],
    ) -> tuple[Fraction, tuple[tuple[tuple[int, ...], int, tuple[str, ...]], ...]]:
        result = solve_main_function_partition(items, rho="0.1")
        return (
            result.cpu_proxy,
            tuple(
                (
                    group.d_types_us,
                    group.timebase_us,
                    tuple(message.message_key for message in group.messages),
                )
                for group in result.groups
            ),
        )

    expected = signature(messages)
    assert signature(tuple(reversed(messages))) == expected
    assert signature(tuple(shuffled)) == expected
    for _ in range(100):
        assert signature(messages) == expected


def test_exact_arithmetic_keeps_decimal_rho_and_result_stable() -> None:
    messages = (
        _message("A", 999_983),
        _message("B", 999_979),
        _message("C", 1_000_003),
        _message("D", 2_000_006),
    )
    result = solve_main_function_partition(messages, rho=0.1)
    assert result.rho == Fraction(1, 10)
    assert isinstance(result.cpu_proxy, Fraction)
    assert result == solve_main_function_partition(tuple(reversed(messages)), rho="0.1")


def test_histogram_cache_ignores_identity_and_input_order_but_maps_messages_back() -> None:
    clear_main_function_cache()
    first = (
        _message("A1", 10_000),
        _message("A2", 10_000),
        _message("A3", 100_000),
    )
    second = (
        _message("B3", 100_000),
        _message("B2", 10_000),
        _message("B1", 10_000),
    )

    first_result = solve_main_function_partition(first, rho=1)
    after_first = main_function_cache_info()
    second_result = solve_main_function_partition(second, rho=1)
    after_second = main_function_cache_info()

    assert (after_first.hits, after_first.misses) == (0, 1)
    assert (after_second.hits, after_second.misses) == (1, 1)
    assert first_result.cpu_proxy == second_result.cpu_proxy
    assert {
        message.message_key
        for group in second_result.groups
        for message in group.messages
    } == {"B1", "B2", "B3"}
    with pytest.raises(FrozenInstanceError):
        first_result.cpu_proxy = Fraction()  # type: ignore[misc]


def test_cache_is_bounded() -> None:
    clear_main_function_cache()
    maxsize = main_function_cache_info().maxsize
    for index in range(maxsize + 5):
        solve_main_function_partition((_message(f"M{index}", 1_000 + index),))
    info = main_function_cache_info()
    assert info.currsize == maxsize
    assert info.misses == maxsize + 5
    clear_main_function_cache()


@pytest.mark.parametrize(
    ("period_us", "offset_us", "exception"),
    (
        (0, 0, ValueError),
        (-1, 0, ValueError),
        (100, -1, ValueError),
        (100.0, 0, TypeError),
        (100, 0.0, TypeError),
        (True, 0, TypeError),
    ),
)
def test_invalid_message_time_is_rejected(
    period_us: object,
    offset_us: object,
    exception: type[Exception],
) -> None:
    with pytest.raises(exception):
        MainFunctionMessage("bad", period_us, offset_us)  # type: ignore[arg-type]


@pytest.mark.parametrize("rho", (0, -1, "0", "nan", True))
def test_invalid_rho_is_rejected(rho: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        solve_main_function_partition((_message("A", 10_000),), rho=rho)  # type: ignore[arg-type]


def test_empty_duplicate_and_non_message_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        solve_main_function_partition(())
    with pytest.raises(ValueError, match="unique"):
        solve_main_function_partition(
            (_message("same", 10_000), _message("same", 20_000))
        )
    with pytest.raises(TypeError, match="MainFunctionMessage"):
        solve_main_function_partition((object(),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must not be empty"):
        calculate_group_timebase_us(())
