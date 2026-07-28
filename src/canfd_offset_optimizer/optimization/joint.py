"""! @file joint.py
@brief 非 GUI 的 CAN/CPU ε-constraint 联合优化与 Pareto 解集。

@details
旧 Peak/Balanced/Variance 路径保持不变。本模块把长周期报文固定为 Offset=0，
并作为不可变负载基线保留在正式 CAN evaluator 和 exact MainFunction solver 中。
外层 Offset 搜索仍是可复现的 GCLS 启发式搜索；仅固定 assignment 下的
MainFunction partition 是全局精确的。
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import combinations
from time import perf_counter

from ..config import ObjectiveConfig, OptimizationConfig
from ..exceptions import OptimizationError
from ..models import (
    CanMessage,
    ObjectiveMode,
    ObjectiveValue,
    OffsetAssignment,
    OptimizationResult,
    RestartAttemptKind,
    RestartMode,
    TimeWindow,
    WeightMode,
    hash_offset_assignments,
    lcm,
)
from ..timeline.slot_map import SlotMap, precompute_slot_map
from ..timeline.state import SearchState
from .gcls import calculate_peak_budget_us, run_gcls
from .greedy import greedy_construct, greedy_order
from .local_search import (
    conflict_candidates,
    conflict_pair_search,
    lowest_delta_relocation_offsets,
    relocate_single_messages,
    variance_hot_slots,
)
from .main_function import (
    MainFunctionMessage,
    MainFunctionSolveResult,
    RhoInput,
    main_function_cache_info,
    normalize_rho,
    solve_main_function_partition,
)
from .objective import ObjectivePolicy, score_state, slot_load_threshold_us
from .joint_analysis import JointRecommendation, select_joint_recommendation
from .triple_search import conflict_triple_search


@dataclass(frozen=True, slots=True)
class JointOptimizationConfig:
    """! @brief 联合搜索新增且不影响旧模式的配置。"""

    rho: Fraction = Fraction(1, 1)
    epsilon_points: int = 21
    max_refinement_passes: int = 3
    endpoint_only: bool = False

    def __post_init__(self) -> None:
        if self.rho <= 0:
            raise ValueError("joint rho must be positive")
        if (
            isinstance(self.epsilon_points, bool)
            or not isinstance(self.epsilon_points, int)
            or self.epsilon_points < 2
        ):
            raise ValueError("epsilon_points must be an integer >= 2")
        if (
            isinstance(self.max_refinement_passes, bool)
            or not isinstance(self.max_refinement_passes, int)
            or self.max_refinement_passes < 1
        ):
            raise ValueError("max_refinement_passes must be an integer >= 1")
        if not isinstance(self.endpoint_only, bool):
            raise ValueError("endpoint_only must be boolean")

    @classmethod
    def from_values(
        cls,
        rho: RhoInput = Fraction(1, 1),
        epsilon_points: int = 21,
        max_refinement_passes: int = 3,
        endpoint_only: bool = False,
    ) -> JointOptimizationConfig:
        """! @brief 稳定解析公开 API 的十进制 rho。"""
        return cls(
            normalize_rho(rho),
            epsilon_points,
            max_refinement_passes,
            endpoint_only,
        )


@dataclass(frozen=True, slots=True)
class JointDomain:
    """! @brief decision/fixed 分离后的完整联合搜索域。"""

    decision_messages: tuple[CanMessage, ...]
    fixed_messages: tuple[CanMessage, ...]
    all_messages: tuple[CanMessage, ...]
    fixed_offsets: tuple[tuple[str, int], ...]
    slot_map: SlotMap
    max_offset_us: int
    hyperperiod_us: int

    @property
    def fixed_offset_map(self) -> dict[str, int]:
        """! @brief 返回 fixed Offset 映射副本。"""
        return dict(self.fixed_offsets)

    def new_state(self) -> SearchState:
        """! @brief 创建已含不可变 fixed CAN baseline 的 decision 状态。"""
        return SearchState(
            self.decision_messages,
            self.slot_map,
            self.fixed_messages,
            self.fixed_offset_map,
        )


@dataclass(frozen=True, slots=True)
class JointMetrics:
    """! @brief 同一 full assignment 的正式 CAN 指标与 exact CPU 结果。"""

    can_objective: ObjectiveValue
    main_function_result: MainFunctionSolveResult

    @property
    def peak(self) -> int:
        return self.can_objective.steady_peak

    @property
    def qss(self) -> int:
        return self.can_objective.sum_square_load

    @property
    def cpu_proxy(self) -> Fraction:
        return self.main_function_result.cpu_proxy


@dataclass(frozen=True, slots=True)
class JointSearchAttempt:
    """! @brief 一次可复现 joint restart 的完整 full-assignment 审计。"""

    attempt_index: int
    attempt_kind: RestartAttemptKind
    seed: int
    assignments: tuple[OffsetAssignment, ...]
    assignment_hash: str
    peak: int
    qss: int
    cpu_proxy: Fraction
    can_objective: ObjectiveValue
    feasible: bool
    evaluation_count: int
    accepted_moves: int
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class JointSearchMetadata:
    """! @brief anchor 或 ε stage 的目标、约束、seed 与 restart 审计。"""

    stage: str
    base_seed: int
    objective: str
    hard_constraints: tuple[str, ...]
    actual_attempts: int
    stop_reason: str
    elapsed_seconds: float
    attempts: tuple[JointSearchAttempt, ...] = ()


@dataclass(frozen=True, slots=True)
class JointSolution:
    """! @brief 一个完整、不可变且可追溯的联合候选解。"""

    assignments: tuple[OffsetAssignment, ...]
    assignment_hash: str
    peak: int
    qss: int
    cpu_proxy: Fraction
    can_objective: ObjectiveValue
    main_function_result: MainFunctionSolveResult
    source: str
    epsilon_budget: Fraction | None
    search_metadata: JointSearchMetadata
    refinement_pass: int = -1
    origin_attempt: int | None = None

    def __post_init__(self) -> None:
        if self.assignment_hash != hash_offset_assignments(self.assignments):
            raise ValueError("joint assignment hash mismatch")
        if self.cpu_proxy != self.main_function_result.cpu_proxy:
            raise ValueError("joint CPU Proxy does not match MainFunction result")
        if (
            self.peak != self.can_objective.steady_peak
            or self.qss != self.can_objective.sum_square_load
        ):
            raise ValueError("joint CAN metrics do not match formal objective")
        if self.peak < 0 or self.qss < 0:
            raise ValueError("joint CAN metrics must be non-negative")

    @property
    def main_function_count(self) -> int:
        return len(self.main_function_result.groups)


@dataclass(frozen=True, slots=True)
class JointEpsilonRun:
    """! @brief 一个 exact Fraction CPU budget 及其搜索结果。"""

    index: int
    budget: Fraction
    solution: JointSolution
    status: str = "feasible"

    def __post_init__(self) -> None:
        if self.solution.cpu_proxy > self.budget:
            raise ValueError("epsilon solution exceeds its exact CPU budget")


@dataclass(frozen=True, slots=True)
class JointPerformanceStats:
    """! @brief exact solver 在联合搜索中的调用与缓存性能。"""

    joint_evaluations: int
    solver_calls: int
    cache_hits: int
    cache_misses: int
    unique_d_histograms: int
    solver_seconds: float
    total_seconds: float
    refinement_seconds: float = 0.0
    epsilon_seconds: float = 0.0

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total else 0.0


@dataclass(frozen=True, slots=True)
class JointOptimizationResult:
    """! @brief anchors、ε runs 和全部 observed non-dominated solutions。"""

    network_id: str
    config: JointOptimizationConfig
    decision_message_count: int
    fixed_message_count: int
    peak_reference: JointSolution
    peak_budget: int
    can_anchor: JointSolution
    cpu_anchor: JointSolution
    epsilon_runs: tuple[JointEpsilonRun, ...]
    pareto_solutions: tuple[JointSolution, ...]
    performance: JointPerformanceStats
    status: str
    refined_peak_reference: JointSolution | None = None
    refined_peak_budget: int | None = None
    refined_can_endpoint: JointSolution | None = None
    refined_cpu_endpoint: JointSolution | None = None
    archive_solutions: tuple[JointSolution, ...] = ()
    stage_solutions: tuple[JointSolution, ...] = ()
    refinement: JointRefinementSummary | None = None
    recommendation: JointRecommendation | None = None


@dataclass(frozen=True, slots=True)
class JointRefinementPass:
    """! @brief 一个 refinement pass 结束后的稳定 observed-state 快照。"""

    pass_index: int
    peak_reference_hash: str
    peak_objective: ObjectiveValue
    peak_budget: int
    can_endpoint_hash: str
    can_qss: int
    can_cpu_proxy: Fraction
    cpu_endpoint_hash: str
    cpu_qss: int
    cpu_cpu_proxy: Fraction
    epsilon_budgets: tuple[Fraction, ...]
    epsilon_solution_hashes: tuple[str, ...]
    pareto_hashes: tuple[str, ...]
    pareto_objectives: tuple[tuple[int, Fraction], ...]
    archive_size: int
    peak_feasible_archive_size: int
    signature: str
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class JointRefinementSummary:
    """! @brief bounded iterative refinement 的终止与逐 pass 审计。"""

    passes_run: int
    max_passes: int
    converged: bool
    termination_reason: str
    passes: tuple[JointRefinementPass, ...]


def build_joint_domain(
    messages: tuple[CanMessage, ...],
    config: OptimizationConfig,
) -> JointDomain:
    """! @brief 按 ``T > max_offset`` 固定 0，并构造 full CAN 时隙表。

    @details
    fixed message 使用 ``allowed_offsets_us=(0,)``，0 是联合模式业务值而非普通
    candidate grid。旧消息对象和旧优化路径均不被修改。
    """
    if not messages:
        raise OptimizationError("joint optimization requires eligible periodic messages")
    ordered = tuple(
        sorted(
            messages,
            key=lambda item: (item.definition_index, item.can_id, item.name),
        )
    )
    decision: list[CanMessage] = []
    fixed: list[CanMessage] = []
    for message in ordered:
        if message.cycle_time_us > config.offset_max_us:
            fixed.append(
                replace(
                    message,
                    allowed_offsets_us=(0,),
                    original_offset_us=0,
                )
            )
        else:
            decision.append(message)
    all_messages = tuple(
        sorted(
            (*decision, *fixed),
            key=lambda item: (item.definition_index, item.can_id, item.name),
        )
    )
    calculated_hyperperiod = lcm(tuple(message.cycle_time_us for message in all_messages))
    hyperperiod = calculated_hyperperiod if config.hyperperiod_us is None else config.hyperperiod_us
    if (
        hyperperiod < calculated_hyperperiod
        or hyperperiod % calculated_hyperperiod
        or hyperperiod > config.hyperperiod_cap_us
    ):
        raise OptimizationError("joint hyperperiod is invalid or exceeds configured cap")
    startup = TimeWindow(0, config.offset_max_us, config.slot_width_us)
    steady = TimeWindow(
        config.offset_max_us,
        config.offset_max_us + hyperperiod,
        config.slot_width_us,
    )
    slot_map = precompute_slot_map(all_messages, startup, steady)
    fixed_offsets = tuple((message.name, 0) for message in fixed)
    return JointDomain(
        tuple(decision),
        tuple(fixed),
        all_messages,
        fixed_offsets,
        slot_map,
        config.offset_max_us,
        hyperperiod,
    )


class JointEvaluator:
    """! @brief 复用正式 CAN score 与 exact MainFunction solver 的评价器。"""

    def __init__(
        self,
        domain: JointDomain,
        rho: Fraction,
        load_threshold_us: int | None,
    ) -> None:
        self.domain = domain
        self.rho = rho
        self.can_policy = ObjectivePolicy(ObjectiveMode.PEAK, load_threshold_us)
        self.evaluation_count = 0
        self.solver_calls = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.solver_seconds = 0.0
        self._histograms: set[tuple[tuple[int, int], ...]] = set()

    @property
    def unique_histogram_count(self) -> int:
        return len(self._histograms)

    def full_assignments(
        self,
        state: SearchState,
    ) -> tuple[OffsetAssignment, ...]:
        """! @brief 合并 decision search vector 与 fixed Offset=0。"""
        offsets = dict(state.current_offsets)
        offsets.update(self.domain.fixed_offset_map)
        if offsets.keys() != {message.name for message in self.domain.all_messages}:
            raise OptimizationError("joint evaluator requires a complete full assignment")
        return tuple(
            OffsetAssignment(
                message.name,
                message.can_id,
                offsets[message.name],
                message.definition_index,
            )
            for message in self.domain.all_messages
        )

    def evaluate_state(self, state: SearchState) -> JointMetrics:
        """! @brief 对一个完整状态计算正式 Peak/Qss 和 exact CPU Proxy。"""
        state.validate_invariants(require_complete=True)
        assignments = self.full_assignments(state)
        offset_by_name = {
            assignment.message_name: assignment.offset_us for assignment in assignments
        }
        mf_messages = tuple(
            MainFunctionMessage(
                message_key=(f"{message.definition_index}:{message.can_id}:{message.name}"),
                period_us=message.cycle_time_us,
                offset_us=offset_by_name[message.name],
            )
            for message in self.domain.all_messages
        )
        histogram_counter = Counter(message.d_us for message in mf_messages)
        self._histograms.add(tuple(sorted(histogram_counter.items())))
        before = main_function_cache_info()
        started = perf_counter()
        mf_result = solve_main_function_partition(mf_messages, self.rho)
        self.solver_seconds += perf_counter() - started
        after = main_function_cache_info()
        self.cache_hits += after.hits - before.hits
        self.cache_misses += after.misses - before.misses
        self.solver_calls += 1
        self.evaluation_count += 1
        return JointMetrics(score_state(state, self.can_policy), mf_result)

    def evaluate_assignments(
        self,
        decision_offsets: Mapping[str, int],
    ) -> tuple[SearchState, JointMetrics]:
        state = self.domain.new_state()
        state.apply_assignments(decision_offsets)
        return state, self.evaluate_state(state)


@dataclass(frozen=True, slots=True)
class _JointPolicy:
    """内部 comparator：CPU anchor 或 CPU-budget 下的 Qss。"""

    objective: str
    peak_budget: int
    violation_guardrail: tuple[int, int]
    epsilon_budget: Fraction | None = None

    def feasible(self, metrics: JointMetrics) -> bool:
        objective = metrics.can_objective
        return (
            objective.steady_peak <= self.peak_budget
            and (objective.violation_count, objective.violation_excess) <= self.violation_guardrail
            and (self.epsilon_budget is None or metrics.cpu_proxy <= self.epsilon_budget)
        )

    def key(
        self,
        metrics: JointMetrics,
        assignment_signature: tuple[tuple[int, int, str, int], ...],
    ) -> tuple[object, ...]:
        if self.objective == "cpu_proxy_then_qss":
            return (
                metrics.cpu_proxy,
                metrics.qss,
                metrics.peak,
                assignment_signature,
            )
        return (
            metrics.qss,
            metrics.cpu_proxy,
            metrics.peak,
            assignment_signature,
        )


def _assignment_signature(
    assignments: tuple[OffsetAssignment, ...],
) -> tuple[tuple[int, int, str, int], ...]:
    return tuple(
        (
            item.definition_index,
            item.can_id,
            item.message_name,
            item.offset_us,
        )
        for item in assignments
    )


def _state_key(
    evaluator: JointEvaluator,
    policy: _JointPolicy,
    state: SearchState,
    metrics: JointMetrics,
) -> tuple[object, ...]:
    return policy.key(
        metrics,
        _assignment_signature(evaluator.full_assignments(state)),
    )


def _restart_order(
    messages: tuple[CanMessage, ...],
    seed: int,
) -> tuple[CanMessage, ...]:
    base = greedy_order(messages)
    groups: dict[tuple[int, int], list[CanMessage]] = defaultdict(list)
    sequence: list[tuple[int, int]] = []
    for message in base:
        key = (message.cycle_time_us, message.frame_time_us)
        if key not in groups:
            sequence.append(key)
        groups[key].append(message)
    generator = random.Random(seed)
    ordered: list[CanMessage] = []
    for key in sequence:
        group = groups[key]
        generator.shuffle(group)
        ordered.extend(group)
    return tuple(ordered)


def _joint_single_search(
    state: SearchState,
    evaluator: JointEvaluator,
    policy: _JointPolicy,
    order: tuple[CanMessage, ...],
) -> tuple[int, int]:
    evaluations = 0
    accepted = 0
    improved = True
    while improved:
        improved = False
        for message in order:
            baseline_metrics = evaluator.evaluate_state(state)
            baseline_key = _state_key(evaluator, policy, state, baseline_metrics)
            old_offset = state.remove(message)
            best_offset = old_offset
            best_key = baseline_key
            for offset in message.allowed_offsets_us:
                state.apply(message, offset)
                metrics = evaluator.evaluate_state(state)
                evaluations += 1
                if policy.feasible(metrics):
                    key = _state_key(evaluator, policy, state, metrics)
                    if key < best_key:
                        best_key = key
                        best_offset = offset
                state.rollback(message, offset)
            state.apply(message, best_offset)
            if best_offset != old_offset:
                accepted += 1
                improved = True
    return evaluations, accepted


def _neighbor_offsets(
    message: CanMessage,
    current: int,
    steps: tuple[int, ...],
    step_us: int,
) -> tuple[int, ...]:
    legal = set(message.allowed_offsets_us)
    candidates = {current}
    for step in steps:
        candidates.add(current - step * step_us)
        candidates.add(current + step * step_us)
    return tuple(sorted(candidates & legal))


def _joint_pair_search(
    state: SearchState,
    evaluator: JointEvaluator,
    policy: _JointPolicy,
    config: OptimizationConfig,
) -> tuple[int, int]:
    evaluations = 0
    accepted = 0
    while True:
        baseline_metrics = evaluator.evaluate_state(state)
        baseline_key = _state_key(evaluator, policy, state, baseline_metrics)
        slots = variance_hot_slots(state)
        candidates = conflict_candidates(
            state,
            slots,
            config.conflict_candidate_cap,
            ObjectivePolicy(
                ObjectiveMode.BALANCED,
                evaluator.can_policy.load_threshold_us,
                policy.peak_budget,
            ),
        )
        best: (
            tuple[
                tuple[object, ...],
                CanMessage,
                CanMessage,
                int,
                int,
            ]
            | None
        ) = None
        for first, second in combinations(candidates, 2):
            first_old = state.current_offsets[first.name]
            second_old = state.current_offsets[second.name]
            first_offsets = set(
                _neighbor_offsets(
                    first,
                    first_old,
                    config.pair_neighbor_steps,
                    config.offset_step_us,
                )
            )
            second_offsets = set(
                _neighbor_offsets(
                    second,
                    second_old,
                    config.pair_neighbor_steps,
                    config.offset_step_us,
                )
            )
            first_offsets.update(
                lowest_delta_relocation_offsets(
                    state,
                    first,
                    config.variance_offset_cap,
                    first_old,
                )
            )
            second_offsets.update(
                lowest_delta_relocation_offsets(
                    state,
                    second,
                    config.variance_offset_cap,
                    second_old,
                )
            )
            state.remove(first)
            state.remove(second)
            try:
                for first_new in sorted(first_offsets):
                    for second_new in sorted(second_offsets):
                        if first_new == first_old or second_new == second_old:
                            continue
                        state.apply(first, first_new)
                        state.apply(second, second_new)
                        metrics = evaluator.evaluate_state(state)
                        evaluations += 1
                        if policy.feasible(metrics):
                            key = _state_key(evaluator, policy, state, metrics)
                            candidate = (
                                key,
                                first,
                                second,
                                first_new,
                                second_new,
                            )
                            if key < baseline_key and (best is None or key < best[0]):
                                best = candidate
                        state.remove(second)
                        state.remove(first)
            finally:
                if first.name not in state.current_offsets:
                    state.apply(first, first_old)
                if second.name not in state.current_offsets:
                    state.apply(second, second_old)
        if best is None:
            break
        _, first, second, first_new, second_new = best
        state.remove(first)
        state.remove(second)
        state.apply(first, first_new)
        state.apply(second, second_new)
        accepted += 1
        single_evaluations, single_accepted = _joint_single_search(
            state,
            evaluator,
            policy,
            greedy_order(state.messages),
        )
        evaluations += single_evaluations
        accepted += single_accepted
    return evaluations, accepted


def _full_offsets_from_solution(
    solution: JointSolution,
    domain: JointDomain,
) -> dict[str, int]:
    all_offsets = {
        assignment.message_name: assignment.offset_us for assignment in solution.assignments
    }
    return {message.name: all_offsets[message.name] for message in domain.decision_messages}


def _make_attempt(
    evaluator: JointEvaluator,
    state: SearchState,
    metrics: JointMetrics,
    policy: _JointPolicy,
    attempt_index: int,
    seed: int,
    evaluations: int,
    accepted_moves: int,
    elapsed_seconds: float,
) -> JointSearchAttempt:
    assignments = evaluator.full_assignments(state)
    return JointSearchAttempt(
        attempt_index,
        (RestartAttemptKind.DETERMINISTIC if attempt_index == 0 else RestartAttemptKind.RANDOM),
        seed,
        assignments,
        hash_offset_assignments(assignments),
        metrics.peak,
        metrics.qss,
        metrics.cpu_proxy,
        metrics.can_objective,
        policy.feasible(metrics),
        evaluations,
        accepted_moves,
        elapsed_seconds,
    )


def _solution_from_state(
    evaluator: JointEvaluator,
    state: SearchState,
    metrics: JointMetrics,
    source: str,
    epsilon_budget: Fraction | None,
    metadata: JointSearchMetadata,
    refinement_pass: int = -1,
    origin_attempt: int | None = None,
) -> JointSolution:
    assignments = evaluator.full_assignments(state)
    return JointSolution(
        assignments,
        hash_offset_assignments(assignments),
        metrics.peak,
        metrics.qss,
        metrics.cpu_proxy,
        metrics.can_objective,
        metrics.main_function_result,
        source,
        epsilon_budget,
        metadata,
        refinement_pass,
        origin_attempt,
    )


def _run_joint_search(
    domain: JointDomain,
    evaluator: JointEvaluator,
    config: OptimizationConfig,
    policy: _JointPolicy,
    *,
    base_seed: int,
    stage: str,
    incumbents: tuple[JointSolution, ...],
    refinement_pass: int = -1,
) -> JointSolution:
    """Run one shared custom-comparator GCLS path for CPU anchor and ε stages."""
    started = perf_counter()
    best_state: SearchState | None = None
    best_metrics: JointMetrics | None = None
    best_key: tuple[object, ...] | None = None
    attempts: list[JointSearchAttempt] = []

    for incumbent in incumbents:
        state = domain.new_state()
        state.apply_assignments(_full_offsets_from_solution(incumbent, domain))
        metrics = evaluator.evaluate_state(state)
        if not policy.feasible(metrics):
            continue
        evaluations, accepted = _joint_single_search(
            state,
            evaluator,
            policy,
            greedy_order(domain.decision_messages),
        )
        metrics = evaluator.evaluate_state(state)
        key = _state_key(evaluator, policy, state, metrics)
        if best_key is None or key < best_key:
            best_state, best_metrics, best_key = state.clone(), metrics, key

    restart_policy = config.restart_policy
    stop_reason = "fixed_limit"
    last_improvement_attempt = 0
    balanced_policy = ObjectivePolicy(
        ObjectiveMode.BALANCED,
        evaluator.can_policy.load_threshold_us,
        policy.peak_budget,
    )
    for attempt_index in range(restart_policy.attempt_limit):
        attempt_started = perf_counter()
        joint_evaluations_before = evaluator.evaluation_count
        seed = base_seed + attempt_index
        order = (
            greedy_order(domain.decision_messages)
            if attempt_index == 0
            else _restart_order(domain.decision_messages, seed)
        )
        state, _ = greedy_construct(
            domain.decision_messages,
            domain.slot_map,
            balanced_policy,
            order,
            fixed_messages=domain.fixed_messages,
            fixed_offsets=domain.fixed_offset_map,
        )
        can_stats = relocate_single_messages(state, balanced_policy, order)
        can_stats += conflict_pair_search(
            state,
            balanced_policy,
            config.hot_slot_count,
            config.conflict_candidate_cap,
            config.pair_neighbor_steps,
            config.offset_step_us,
            config.variance_offset_cap,
        )
        if config.conflict_triple_enabled:
            triple_stats, _ = conflict_triple_search(
                state,
                balanced_policy,
                policy.violation_guardrail,
                candidate_cap=config.triple_candidate_cap,
                hot_slot_count=config.triple_hot_slot_count,
                max_rounds=config.triple_max_rounds,
                pair_hot_slot_count=config.hot_slot_count,
                pair_candidate_cap=config.conflict_candidate_cap,
                pair_neighbor_steps=config.pair_neighbor_steps,
                offset_step_us=config.offset_step_us,
                variance_offset_cap=config.variance_offset_cap,
            )
            can_stats += triple_stats
        metrics = evaluator.evaluate_state(state)
        accepted_moves = can_stats.accepted_moves
        if policy.feasible(metrics):
            _, joint_accepted = _joint_single_search(
                state,
                evaluator,
                policy,
                order,
            )
            _, pair_accepted = _joint_pair_search(
                state,
                evaluator,
                policy,
                config,
            )
            accepted_moves += joint_accepted + pair_accepted
            metrics = evaluator.evaluate_state(state)
        attempt = _make_attempt(
            evaluator,
            state,
            metrics,
            policy,
            attempt_index,
            seed,
            evaluator.evaluation_count - joint_evaluations_before,
            accepted_moves,
            perf_counter() - attempt_started,
        )
        attempts.append(attempt)
        strict_improvement = False
        if attempt.feasible:
            key = _state_key(evaluator, policy, state, metrics)
            strict_improvement = best_key is None or key < best_key
            if strict_improvement:
                best_state, best_metrics, best_key = state.clone(), metrics, key
                last_improvement_attempt = attempt_index + 1
        actual_attempts = attempt_index + 1
        if (
            restart_policy.mode is RestartMode.ADAPTIVE
            and actual_attempts >= restart_policy.min_attempts
            and actual_attempts % restart_policy.check_interval == 0
            and actual_attempts - last_improvement_attempt >= restart_policy.patience_attempts
        ):
            stop_reason = "patience_exhausted"
            break
    if best_state is None or best_metrics is None:
        raise OptimizationError(f"{stage} found no feasible joint assignment")
    metadata = JointSearchMetadata(
        stage,
        base_seed,
        policy.objective,
        (
            f"Peak <= {policy.peak_budget}",
            (
                "violation pair <= "
                f"({policy.violation_guardrail[0]}, {policy.violation_guardrail[1]})"
            ),
            (
                f"exact CPU Proxy <= {policy.epsilon_budget}"
                if policy.epsilon_budget is not None
                else "no CPU budget"
            ),
        ),
        len(attempts),
        stop_reason,
        perf_counter() - started,
        tuple(attempts),
    )
    return _solution_from_state(
        evaluator,
        best_state,
        best_metrics,
        stage,
        policy.epsilon_budget,
        metadata,
        refinement_pass,
    )


def generate_epsilon_budgets(
    p_min: Fraction,
    p_max: Fraction,
    count: int,
) -> tuple[Fraction, ...]:
    """! @brief 生成含两个端点的 exact、单调非降 CPU budget。"""
    if count < 2:
        raise ValueError("epsilon point count must be >= 2")
    if p_min > p_max:
        raise ValueError("P_min must not exceed P_max")
    return tuple(p_min + Fraction(index, count - 1) * (p_max - p_min) for index in range(count))


def _representative_key(solution: JointSolution) -> tuple[object, ...]:
    return (
        solution.peak,
        solution.main_function_count,
        _assignment_signature(solution.assignments),
        solution.source,
    )


def deduplicate_joint_solutions(
    solutions: tuple[JointSolution, ...],
) -> tuple[JointSolution, ...]:
    """! @brief 先按 full assignment，再按 exact ``(Qss, CPU)`` 去重。"""
    by_assignment: dict[str, JointSolution] = {}
    for solution in solutions:
        previous = by_assignment.get(solution.assignment_hash)
        if previous is None or _representative_key(solution) < _representative_key(previous):
            by_assignment[solution.assignment_hash] = solution
    by_objective: dict[tuple[int, Fraction], JointSolution] = {}
    for solution in by_assignment.values():
        key = (solution.qss, solution.cpu_proxy)
        previous = by_objective.get(key)
        if previous is None or _representative_key(solution) < _representative_key(previous):
            by_objective[key] = solution
    return tuple(by_objective.values())


def filter_pareto_solutions(
    solutions: tuple[JointSolution, ...],
) -> tuple[JointSolution, ...]:
    """! @brief 在 Qss/CPU 两维过滤支配点；Peak 仅作为 hard guardrail。"""
    unique = deduplicate_joint_solutions(solutions)
    non_dominated = tuple(
        candidate
        for candidate in unique
        if not any(
            other is not candidate
            and other.qss <= candidate.qss
            and other.cpu_proxy <= candidate.cpu_proxy
            and (other.qss < candidate.qss or other.cpu_proxy < candidate.cpu_proxy)
            for other in unique
        )
    )
    return tuple(
        sorted(
            non_dominated,
            key=lambda item: (
                item.qss,
                item.cpu_proxy,
                item.peak,
                _assignment_signature(item.assignments),
            ),
        )
    )


def _archive_representative_key(solution: JointSolution) -> tuple[object, ...]:
    return (
        solution.refinement_pass,
        solution.source,
        -1 if solution.origin_attempt is None else solution.origin_attempt,
        _assignment_signature(solution.assignments),
    )


def _archive_add(
    archive: dict[str, JointSolution],
    solution: JointSolution,
) -> None:
    previous = archive.get(solution.assignment_hash)
    if previous is None or _archive_representative_key(solution) < _archive_representative_key(
        previous
    ):
        archive[solution.assignment_hash] = solution


def _solution_from_attempt(
    attempt: JointSearchAttempt,
    parent: JointSolution,
    evaluator: JointEvaluator,
    domain: JointDomain,
) -> JointSolution:
    decision_names = {message.name for message in domain.decision_messages}
    decision_offsets = {
        assignment.message_name: assignment.offset_us
        for assignment in attempt.assignments
        if assignment.message_name in decision_names
    }
    state, metrics = evaluator.evaluate_assignments(decision_offsets)
    metadata = JointSearchMetadata(
        stage=f"{parent.source}/attempt_{attempt.attempt_index:02d}",
        base_seed=attempt.seed,
        objective=parent.search_metadata.objective,
        hard_constraints=parent.search_metadata.hard_constraints,
        actual_attempts=1,
        stop_reason="archive_attempt",
        elapsed_seconds=attempt.elapsed_seconds,
        attempts=(),
    )
    return _solution_from_state(
        evaluator,
        state,
        metrics,
        metadata.stage,
        parent.epsilon_budget,
        metadata,
        parent.refinement_pass,
        attempt.attempt_index,
    )


def _archive_stage(
    archive: dict[str, JointSolution],
    solution: JointSolution,
    evaluator: JointEvaluator,
    domain: JointDomain,
) -> None:
    _archive_add(archive, solution)
    for attempt in solution.search_metadata.attempts:
        _archive_add(
            archive,
            _solution_from_attempt(attempt, solution, evaluator, domain),
        )


def _official_peak_key(solution: JointSolution) -> tuple[object, ...]:
    return (
        solution.can_objective.as_tuple(),
        _assignment_signature(solution.assignments),
    )


def _peak_feasible(
    solution: JointSolution,
    peak_reference: JointSolution,
    peak_budget: int,
) -> bool:
    reference = peak_reference.can_objective
    objective = solution.can_objective
    return objective.steady_peak <= peak_budget and (
        objective.violation_count,
        objective.violation_excess,
    ) <= (reference.violation_count, reference.violation_excess)


def _peak_feasible_archive(
    archive: Mapping[str, JointSolution],
    peak_reference: JointSolution,
    peak_budget: int,
) -> tuple[JointSolution, ...]:
    return tuple(
        sorted(
            (
                solution
                for solution in archive.values()
                if _peak_feasible(solution, peak_reference, peak_budget)
            ),
            key=lambda item: (
                item.qss,
                item.cpu_proxy,
                item.peak,
                _assignment_signature(item.assignments),
            ),
        )
    )


def _observed_can_endpoint(
    solutions: tuple[JointSolution, ...],
) -> JointSolution:
    if not solutions:
        raise OptimizationError("joint archive contains no Peak-feasible CAN endpoint")
    return min(
        solutions,
        key=lambda item: (
            item.qss,
            item.cpu_proxy,
            item.can_objective.as_tuple(),
            _assignment_signature(item.assignments),
        ),
    )


def _observed_cpu_endpoint(
    solutions: tuple[JointSolution, ...],
) -> JointSolution:
    if not solutions:
        raise OptimizationError("joint archive contains no Peak-feasible CPU endpoint")
    return min(
        solutions,
        key=lambda item: (
            item.cpu_proxy,
            item.qss,
            item.can_objective.as_tuple(),
            _assignment_signature(item.assignments),
        ),
    )


def _warm_start_archive(
    solutions: tuple[JointSolution, ...],
    *,
    epsilon_budget: Fraction | None = None,
    required: tuple[JointSolution, ...] = (),
    cap: int = 4,
) -> tuple[JointSolution, ...]:
    eligible = tuple(
        solution
        for solution in solutions
        if epsilon_budget is None or solution.cpu_proxy <= epsilon_budget
    )
    ordered = tuple(
        sorted(
            (*required, *eligible),
            key=lambda item: (
                item.qss,
                item.cpu_proxy,
                item.peak,
                _assignment_signature(item.assignments),
            ),
        )
    )
    unique: list[JointSolution] = []
    seen: set[str] = set()
    required_hashes = {item.assignment_hash for item in required}
    for solution in ordered:
        if solution.assignment_hash in seen:
            continue
        if len(unique) >= cap and solution.assignment_hash not in required_hashes:
            continue
        seen.add(solution.assignment_hash)
        unique.append(solution)
    return tuple(unique)


def _refinement_signature(
    peak_reference: JointSolution,
    peak_budget: int,
    can_endpoint: JointSolution,
    cpu_endpoint: JointSolution,
    pareto: tuple[JointSolution, ...],
) -> str:
    payload = {
        "peak": {
            "objective": peak_reference.can_objective.as_tuple(),
            "hash": peak_reference.assignment_hash,
        },
        "peak_budget": peak_budget,
        "can": {
            "qss": can_endpoint.qss,
            "cpu": (
                can_endpoint.cpu_proxy.numerator,
                can_endpoint.cpu_proxy.denominator,
            ),
            "hash": can_endpoint.assignment_hash,
        },
        "cpu": {
            "qss": cpu_endpoint.qss,
            "cpu": (
                cpu_endpoint.cpu_proxy.numerator,
                cpu_endpoint.cpu_proxy.denominator,
            ),
            "hash": cpu_endpoint.assignment_hash,
        },
        "pareto": [
            (
                item.qss,
                item.cpu_proxy.numerator,
                item.cpu_proxy.denominator,
                item.assignment_hash,
            )
            for item in pareto
        ],
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _gcls_metadata(
    stage: str,
    base_seed: int,
    result: OptimizationResult,
    evaluator: JointEvaluator,
    domain: JointDomain,
) -> JointSearchMetadata:
    attempts: list[JointSearchAttempt] = []
    for record in result.restart_records:
        offsets = {
            assignment.message_name: assignment.offset_us for assignment in record.assignments
        }
        state, metrics = evaluator.evaluate_assignments(offsets)
        assignments = evaluator.full_assignments(state)
        attempts.append(
            JointSearchAttempt(
                record.attempt_index,
                record.attempt_kind,
                record.seed,
                assignments,
                hash_offset_assignments(assignments),
                metrics.peak,
                metrics.qss,
                metrics.cpu_proxy,
                metrics.can_objective,
                True,
                record.evaluation_count,
                record.accepted_moves,
                record.elapsed_seconds,
            )
        )
    return JointSearchMetadata(
        stage,
        base_seed,
        result.objective.mode.value,
        ("joint-domain formal CAN objective",),
        result.restart_execution.actual_attempts,
        result.restart_execution.stop_reason,
        result.elapsed_seconds,
        tuple(attempts),
    )


def _solution_from_gcls(
    source: str,
    base_seed: int,
    result: OptimizationResult,
    evaluator: JointEvaluator,
    domain: JointDomain,
    refinement_pass: int = -1,
) -> JointSolution:
    state, metrics = evaluator.evaluate_assignments(result.offset_by_name())
    if metrics.can_objective.metrics_tuple() != result.objective.metrics_tuple():
        raise RuntimeError("joint GCLS loads differ from formal full CAN evaluation")
    metadata = _gcls_metadata(source, base_seed, result, evaluator, domain)
    return _solution_from_state(
        evaluator,
        state,
        metrics,
        source,
        None,
        metadata,
        refinement_pass,
    )


def _single_assignment_solution(
    domain: JointDomain,
    evaluator: JointEvaluator,
    source: str,
    seed: int,
) -> JointSolution:
    state = domain.new_state()
    metrics = evaluator.evaluate_state(state)
    metadata = JointSearchMetadata(
        source,
        seed,
        "single_fixed_assignment",
        ("all messages fixed at Offset=0",),
        0,
        "no_decision_messages",
        0.0,
    )
    return _solution_from_state(evaluator, state, metrics, source, None, metadata)


def optimize_can_cpu_balanced(
    network_id: str,
    messages: tuple[CanMessage, ...],
    optimization_config: OptimizationConfig,
    objective_config: ObjectiveConfig,
    *,
    average_load_limit: float = 0.75,
    weight_mode: WeightMode = WeightMode.FRAME_TIME_US,
    seed: int = 0,
    joint_config: JointOptimizationConfig | None = None,
) -> JointOptimizationResult:
    """! @brief 运行 bounded iterative refinement 并解释最终 observed Pareto。

    @details
    ``peak_reference/can_anchor/cpu_anchor`` 保留 initial heuristic 语义；refined
    字段保存 cumulative archive 上的最终 observed endpoints。Knee 仅在搜索和
    convergence 完成后做 post-processing，不反馈给搜索。
    """
    started = perf_counter()
    selected_joint_config = joint_config or JointOptimizationConfig()
    domain = build_joint_domain(messages, optimization_config)
    load_threshold = (
        slot_load_threshold_us(
            optimization_config.slot_width_us,
            average_load_limit,
        )
        if weight_mode is WeightMode.FRAME_TIME_US
        else None
    )
    evaluator = JointEvaluator(
        domain,
        selected_joint_config.rho,
        load_threshold,
    )
    if not domain.decision_messages:
        only = _single_assignment_solution(domain, evaluator, "single_assignment", seed)
        recommendation = select_joint_recommendation((only,))
        refinement = JointRefinementSummary(
            0,
            selected_joint_config.max_refinement_passes,
            True,
            "no_decision_messages",
            (),
        )
        performance = JointPerformanceStats(
            evaluator.evaluation_count,
            evaluator.solver_calls,
            evaluator.cache_hits,
            evaluator.cache_misses,
            evaluator.unique_histogram_count,
            evaluator.solver_seconds,
            perf_counter() - started,
        )
        return JointOptimizationResult(
            network_id,
            selected_joint_config,
            0,
            len(domain.fixed_messages),
            only,
            calculate_peak_budget_us(only.peak, objective_config),
            only,
            only,
            (),
            (only,),
            performance,
            "no_decision_messages",
            only,
            calculate_peak_budget_us(only.peak, objective_config),
            only,
            only,
            (only,),
            (only,),
            refinement,
            recommendation,
        )

    archive: dict[str, JointSolution] = {}
    peak_objective = replace(objective_config, mode=ObjectiveMode.PEAK)
    peak_result = run_gcls(
        domain.decision_messages,
        domain.slot_map,
        optimization_config,
        average_load_limit,
        seed,
        weight_mode,
        peak_objective,
        fixed_messages=domain.fixed_messages,
        fixed_offsets=domain.fixed_offset_map,
    )
    peak_reference = _solution_from_gcls(
        "initial_peak_reference",
        seed,
        peak_result,
        evaluator,
        domain,
    )
    initial_peak_budget = calculate_peak_budget_us(
        peak_reference.peak,
        objective_config,
    )
    balanced_objective = replace(objective_config, mode=ObjectiveMode.BALANCED)
    can_result = run_gcls(
        domain.decision_messages,
        domain.slot_map,
        optimization_config,
        average_load_limit,
        seed,
        weight_mode,
        balanced_objective,
        peak_result,
        fixed_messages=domain.fixed_messages,
        fixed_offsets=domain.fixed_offset_map,
    )
    can_anchor = _solution_from_gcls(
        "initial_can_anchor",
        seed,
        can_result,
        evaluator,
        domain,
    )
    _archive_stage(archive, peak_reference, evaluator, domain)
    _archive_stage(archive, can_anchor, evaluator, domain)
    violation_guardrail = (
        peak_result.objective.violation_count,
        peak_result.objective.violation_excess,
    )
    cpu_policy = _JointPolicy(
        "cpu_proxy_then_qss",
        initial_peak_budget,
        violation_guardrail,
    )
    cpu_anchor = _run_joint_search(
        domain,
        evaluator,
        optimization_config,
        cpu_policy,
        base_seed=seed + 10_000,
        stage="initial_cpu_anchor",
        incumbents=(can_anchor,),
    )
    if cpu_anchor.cpu_proxy > can_anchor.cpu_proxy:
        raise RuntimeError("CPU anchor lost the known feasible CAN anchor")
    _archive_stage(archive, cpu_anchor, evaluator, domain)
    stage_solutions: list[JointSolution] = [
        peak_reference,
        can_anchor,
        cpu_anchor,
    ]

    refined_peak = min(archive.values(), key=_official_peak_key)
    refined_budget = calculate_peak_budget_us(refined_peak.peak, objective_config)
    feasible_archive = _peak_feasible_archive(
        archive,
        refined_peak,
        refined_budget,
    )
    refined_can = _observed_can_endpoint(feasible_archive)
    refined_cpu = _observed_cpu_endpoint(feasible_archive)
    if refined_cpu.cpu_proxy > refined_can.cpu_proxy:
        raise RuntimeError("observed CPU endpoint exceeds observed CAN endpoint CPU Proxy")

    pass_records: list[JointRefinementPass] = []
    final_epsilon_runs: tuple[JointEpsilonRun, ...] = ()
    previous_signature: str | None = None
    converged = False
    termination_reason = "refinement_limit_reached"
    epsilon_seconds = 0.0
    refinement_started = perf_counter()

    for pass_index in range(selected_joint_config.max_refinement_passes):
        pass_started = perf_counter()
        pass_seed_base = seed + 1_000_000 + pass_index * 100_000

        peak_pass_result = run_gcls(
            domain.decision_messages,
            domain.slot_map,
            optimization_config,
            average_load_limit,
            pass_seed_base,
            weight_mode,
            peak_objective,
            fixed_messages=domain.fixed_messages,
            fixed_offsets=domain.fixed_offset_map,
        )
        peak_pass = _solution_from_gcls(
            f"refinement_{pass_index:02d}_peak",
            pass_seed_base,
            peak_pass_result,
            evaluator,
            domain,
            pass_index,
        )
        _archive_stage(archive, peak_pass, evaluator, domain)
        stage_solutions.append(peak_pass)

        refined_peak = min(archive.values(), key=_official_peak_key)
        refined_budget = calculate_peak_budget_us(
            refined_peak.peak,
            objective_config,
        )
        feasible_archive = _peak_feasible_archive(
            archive,
            refined_peak,
            refined_budget,
        )
        refined_can = _observed_can_endpoint(feasible_archive)
        violation_guardrail = (
            refined_peak.can_objective.violation_count,
            refined_peak.can_objective.violation_excess,
        )

        can_policy = _JointPolicy(
            "qss_then_cpu_proxy",
            refined_budget,
            violation_guardrail,
        )
        can_refinement = _run_joint_search(
            domain,
            evaluator,
            optimization_config,
            can_policy,
            base_seed=pass_seed_base + 20_000,
            stage=f"refinement_{pass_index:02d}_can",
            incumbents=_warm_start_archive(
                feasible_archive,
                required=(refined_can,),
            ),
            refinement_pass=pass_index,
        )
        _archive_stage(archive, can_refinement, evaluator, domain)
        stage_solutions.append(can_refinement)

        refined_peak = min(archive.values(), key=_official_peak_key)
        refined_budget = calculate_peak_budget_us(
            refined_peak.peak,
            objective_config,
        )
        feasible_archive = _peak_feasible_archive(
            archive,
            refined_peak,
            refined_budget,
        )
        refined_can = _observed_can_endpoint(feasible_archive)
        refined_cpu = _observed_cpu_endpoint(feasible_archive)
        violation_guardrail = (
            refined_peak.can_objective.violation_count,
            refined_peak.can_objective.violation_excess,
        )
        cpu_policy = _JointPolicy(
            "cpu_proxy_then_qss",
            refined_budget,
            violation_guardrail,
        )
        cpu_refinement = _run_joint_search(
            domain,
            evaluator,
            optimization_config,
            cpu_policy,
            base_seed=pass_seed_base + 30_000,
            stage=f"refinement_{pass_index:02d}_cpu",
            incumbents=_warm_start_archive(
                feasible_archive,
                required=(refined_cpu, refined_can),
            ),
            refinement_pass=pass_index,
        )
        _archive_stage(archive, cpu_refinement, evaluator, domain)
        stage_solutions.append(cpu_refinement)

        refined_peak = min(archive.values(), key=_official_peak_key)
        refined_budget = calculate_peak_budget_us(
            refined_peak.peak,
            objective_config,
        )
        feasible_archive = _peak_feasible_archive(
            archive,
            refined_peak,
            refined_budget,
        )
        refined_can = _observed_can_endpoint(feasible_archive)
        refined_cpu = _observed_cpu_endpoint(feasible_archive)
        if refined_cpu.cpu_proxy > refined_can.cpu_proxy:
            raise RuntimeError("refined P_min exceeds refined P_max")

        pass_epsilon_runs: list[JointEpsilonRun] = []
        budgets: tuple[Fraction, ...] = ()
        if (
            not selected_joint_config.endpoint_only
            and refined_cpu.cpu_proxy < refined_can.cpu_proxy
        ):
            budgets = generate_epsilon_budgets(
                refined_cpu.cpu_proxy,
                refined_can.cpu_proxy,
                selected_joint_config.epsilon_points,
            )
            previous = refined_cpu
            epsilon_started = perf_counter()
            for index, budget in enumerate(budgets):
                epsilon_required = tuple(
                    solution
                    for solution in (previous, refined_cpu, refined_can)
                    if solution.cpu_proxy <= budget
                )
                epsilon_policy = _JointPolicy(
                    "qss_then_cpu_proxy",
                    refined_budget,
                    (
                        refined_peak.can_objective.violation_count,
                        refined_peak.can_objective.violation_excess,
                    ),
                    budget,
                )
                solution = _run_joint_search(
                    domain,
                    evaluator,
                    optimization_config,
                    epsilon_policy,
                    base_seed=pass_seed_base + 40_000 + index * 1_000,
                    stage=f"refinement_{pass_index:02d}_epsilon_{index:02d}",
                    incumbents=_warm_start_archive(
                        feasible_archive,
                        epsilon_budget=budget,
                        required=epsilon_required,
                        cap=6,
                    ),
                    refinement_pass=pass_index,
                )
                run = JointEpsilonRun(index, budget, solution)
                pass_epsilon_runs.append(run)
                _archive_stage(archive, solution, evaluator, domain)
                stage_solutions.append(solution)
                previous = solution
            epsilon_seconds += perf_counter() - epsilon_started

        # 任意 stage 都可能发现更好的正式 Peak candidate；以收紧后的 guardrail
        # 重新筛 archive，绝不为保留旧 Pareto 点沿用过时 budget。
        refined_peak = min(archive.values(), key=_official_peak_key)
        refined_budget = calculate_peak_budget_us(
            refined_peak.peak,
            objective_config,
        )
        feasible_archive = _peak_feasible_archive(
            archive,
            refined_peak,
            refined_budget,
        )
        refined_can = _observed_can_endpoint(feasible_archive)
        refined_cpu = _observed_cpu_endpoint(feasible_archive)
        pareto = filter_pareto_solutions(feasible_archive)
        final_epsilon_runs = tuple(
            run
            for run in pass_epsilon_runs
            if _peak_feasible(run.solution, refined_peak, refined_budget)
        )
        signature = _refinement_signature(
            refined_peak,
            refined_budget,
            refined_can,
            refined_cpu,
            pareto,
        )
        pass_records.append(
            JointRefinementPass(
                pass_index,
                refined_peak.assignment_hash,
                refined_peak.can_objective,
                refined_budget,
                refined_can.assignment_hash,
                refined_can.qss,
                refined_can.cpu_proxy,
                refined_cpu.assignment_hash,
                refined_cpu.qss,
                refined_cpu.cpu_proxy,
                budgets,
                tuple(run.solution.assignment_hash for run in pass_epsilon_runs),
                tuple(solution.assignment_hash for solution in pareto),
                tuple((solution.qss, solution.cpu_proxy) for solution in pareto),
                len(archive),
                len(feasible_archive),
                signature,
                perf_counter() - pass_started,
            )
        )
        if previous_signature is not None and signature == previous_signature:
            converged = True
            termination_reason = "refinement_converged"
            break
        previous_signature = signature

    refinement_seconds = perf_counter() - refinement_started
    if not pass_records:
        raise RuntimeError("joint refinement produced no pass")
    pareto = filter_pareto_solutions(feasible_archive)
    recommendation = select_joint_recommendation(pareto)
    refinement = JointRefinementSummary(
        len(pass_records),
        selected_joint_config.max_refinement_passes,
        converged,
        termination_reason,
        tuple(pass_records),
    )
    archive_solutions = tuple(
        sorted(
            archive.values(),
            key=lambda item: (
                item.refinement_pass,
                item.source,
                -1 if item.origin_attempt is None else item.origin_attempt,
                _assignment_signature(item.assignments),
            ),
        )
    )
    status = "no_observed_cpu_tradeoff" if refined_cpu.cpu_proxy == refined_can.cpu_proxy else "ok"
    performance = JointPerformanceStats(
        evaluator.evaluation_count,
        evaluator.solver_calls,
        evaluator.cache_hits,
        evaluator.cache_misses,
        evaluator.unique_histogram_count,
        evaluator.solver_seconds,
        perf_counter() - started,
        refinement_seconds,
        epsilon_seconds,
    )
    return JointOptimizationResult(
        network_id,
        selected_joint_config,
        len(domain.decision_messages),
        len(domain.fixed_messages),
        peak_reference,
        initial_peak_budget,
        can_anchor,
        cpu_anchor,
        final_epsilon_runs,
        pareto,
        performance,
        status,
        refined_peak,
        refined_budget,
        refined_can,
        refined_cpu,
        archive_solutions,
        tuple(stage_solutions),
        refinement,
        recommendation,
    )
