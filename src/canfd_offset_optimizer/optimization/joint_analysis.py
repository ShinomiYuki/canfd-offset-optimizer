"""! @file joint_analysis.py
@brief Joint observed Pareto front 的精确 knee 后处理与距离诊断。

@details
本模块只读取最终 Pareto 解，不参与 GCLS objective、约束、restart 或候选筛选。
归一化、knee score 与所有 tie-break 使用 ``Fraction``；Hausdorff 仅在最终展示
欧氏距离时转为 float。
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import sqrt
from typing import Protocol


class JointParetoPoint(Protocol):
    """Knee/距离诊断所需的最小结构接口。"""

    @property
    def qss(self) -> int: ...

    @property
    def cpu_proxy(self) -> Fraction: ...

    @property
    def peak(self) -> int: ...

    @property
    def assignment_hash(self) -> str: ...

    @property
    def main_function_count(self) -> int: ...


@dataclass(frozen=True, slots=True)
class NormalizedJointPoint:
    """一个 observed Pareto 点的 exact normalized 坐标。"""

    assignment_hash: str
    qss: int
    cpu_proxy: Fraction
    normalized_q: Fraction
    normalized_cpu: Fraction


@dataclass(frozen=True, slots=True)
class JointRecommendation:
    """最终 refined observed Pareto 的解释性推荐结果。"""

    method: str
    solution_hash: str | None
    pareto_index: int | None
    qss: int | None
    cpu_proxy: Fraction | None
    peak: int | None
    main_function_count: int | None
    normalized_q: Fraction | None
    normalized_cpu: Fraction | None
    knee_score: Fraction | None
    knee_distance_display: float | None
    ideal_distance_display: float | None
    note: str

    @property
    def has_recommendation(self) -> bool:
        return self.solution_hash is not None


def _normalize_objectives(
    objectives: tuple[tuple[str, int, Fraction], ...],
) -> tuple[NormalizedJointPoint, ...]:
    if not objectives:
        return ()
    q_min = min(item[1] for item in objectives)
    q_max = max(item[1] for item in objectives)
    p_min = min(item[2] for item in objectives)
    p_max = max(item[2] for item in objectives)
    q_span = q_max - q_min
    p_span = p_max - p_min
    return tuple(
        NormalizedJointPoint(
            assignment_hash,
            qss,
            cpu_proxy,
            Fraction(qss - q_min, q_span) if q_span else Fraction(),
            (cpu_proxy - p_min) / p_span if p_span else Fraction(),
        )
        for assignment_hash, qss, cpu_proxy in objectives
    )


def normalize_joint_front(
    front: tuple[JointParetoPoint, ...],
) -> tuple[NormalizedJointPoint, ...]:
    """按 deterministic Q/P/hash 顺序归一化一个 observed front。"""
    ordered = tuple(
        sorted(
            front,
            key=lambda item: (item.qss, item.cpu_proxy, item.assignment_hash),
        )
    )
    return _normalize_objectives(
        tuple((item.assignment_hash, item.qss, item.cpu_proxy) for item in ordered)
    )


def select_joint_recommendation(
    front: tuple[JointParetoPoint, ...],
) -> JointRecommendation:
    """在最终 refined observed Pareto 上执行 exact chord-distance knee。

    几何只使用 Qss 与 CPU Proxy。Peak 已由 guardrail 处理，MainFunction 数也不
    进入几何；它们仅随被选 solution 一起输出。
    """
    ordered = tuple(
        sorted(
            front,
            key=lambda item: (item.qss, item.cpu_proxy, item.assignment_hash),
        )
    )
    normalized = normalize_joint_front(ordered)
    if not ordered:
        return JointRecommendation(
            "invalid_empty_front",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "empty observed Pareto front; no automatic recommendation",
        )
    if len(ordered) == 1:
        point = ordered[0]
        normalized_point = normalized[0]
        return JointRecommendation(
            "unique_solution",
            point.assignment_hash,
            0,
            point.qss,
            point.cpu_proxy,
            point.peak,
            point.main_function_count,
            normalized_point.normalized_q,
            normalized_point.normalized_cpu,
            None,
            None,
            0.0,
            "the only observed non-dominated solution is returned; this is not a knee",
        )
    if len(ordered) == 2:
        return JointRecommendation(
            "no_interior_knee",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "two endpoint solutions have no interior compromise point",
        )

    candidates: list[
        tuple[
            int,
            JointParetoPoint,
            NormalizedJointPoint,
            Fraction,
            Fraction,
        ]
    ] = []
    for index in range(1, len(ordered) - 1):
        point = ordered[index]
        normalized_point = normalized[index]
        x_value = normalized_point.normalized_q
        y_value = normalized_point.normalized_cpu
        knee_score = Fraction(1) - x_value - y_value
        ideal_squared = x_value * x_value + y_value * y_value
        candidates.append((index, point, normalized_point, knee_score, ideal_squared))
    positive = tuple(item for item in candidates if item[3] > 0)
    if positive:
        selected = min(
            positive,
            key=lambda item: (
                -item[3],
                item[4],
                item[1].qss,
                item[1].cpu_proxy,
                item[1].assignment_hash,
            ),
        )
        method = "geometric_knee"
        note = "maximum exact positive chord-distance score on the refined observed front"
    else:
        selected = min(
            candidates,
            key=lambda item: (
                item[4],
                max(
                    item[2].normalized_q,
                    item[2].normalized_cpu,
                ),
                item[1].qss,
                item[1].cpu_proxy,
                item[1].assignment_hash,
            ),
        )
        method = "ideal_point_fallback"
        note = (
            "no positive geometric knee exists; selected the closest interior "
            "ideal-point compromise"
        )
    index, point, normalized_point, knee_score, ideal_squared = selected
    return JointRecommendation(
        method,
        point.assignment_hash,
        index,
        point.qss,
        point.cpu_proxy,
        point.peak,
        point.main_function_count,
        normalized_point.normalized_q,
        normalized_point.normalized_cpu,
        knee_score,
        float(knee_score) / sqrt(2.0),
        sqrt(float(ideal_squared)),
        note,
    )


def normalized_symmetric_hausdorff_distance(
    first: tuple[tuple[int, Fraction], ...],
    second: tuple[tuple[int, Fraction], ...],
) -> float:
    """返回两个 observed objective fronts 的 common-normalized Hausdorff 距离。

    空 front 没有可定义距离，因此明确抛错。某维 span 为零时该维坐标统一为 0。
    最近点与最大值比较使用 exact squared distance，最后仅对结果开平方展示。
    """
    if not first or not second:
        raise ValueError("Hausdorff distance requires two non-empty fronts")
    combined = tuple(
        (f"first:{index}", qss, cpu) for index, (qss, cpu) in enumerate(first)
    ) + tuple((f"second:{index}", qss, cpu) for index, (qss, cpu) in enumerate(second))
    normalized = _normalize_objectives(combined)
    first_points = tuple(
        (item.normalized_q, item.normalized_cpu) for item in normalized[: len(first)]
    )
    second_points = tuple(
        (item.normalized_q, item.normalized_cpu) for item in normalized[len(first) :]
    )

    def directed(
        source: tuple[tuple[Fraction, Fraction], ...],
        target: tuple[tuple[Fraction, Fraction], ...],
    ) -> Fraction:
        return max(
            min(
                (source_q - target_q) ** 2 + (source_p - target_p) ** 2
                for target_q, target_p in target
            )
            for source_q, source_p in source
        )

    squared = max(
        directed(first_points, second_points),
        directed(second_points, first_points),
    )
    return sqrt(float(squared))
