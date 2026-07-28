"""! @file joint.py
@brief 非 GUI 的 CAN/CPU ε-constraint 联合优化与 Pareto 解集。

@details
旧 Peak/Balanced/Variance 路径保持不变。本模块把长周期报文固定为 Offset=0，
并作为不可变负载基线保留在正式 CAN evaluator 和 exact MainFunction solver 中。
外层 Offset 搜索仍是可复现的 GCLS 启发式搜索；仅固定 assignment 下的
MainFunction partition 是全局精确的。
"""

from __future__ import annotations

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
from .triple_search import conflict_triple_search


@dataclass(frozen=True, slots=True)
class JointOptimizationConfig:
    """! @brief 联合搜索新增且不影响旧模式的配置。"""

    rho: Fraction = Fraction(1, 1)
    epsilon_points: int = 21

    def __post_init__(self) -> None:
        if self.rho <= 0:
            raise ValueError("joint rho must be positive")
        if (
            isinstance(self.epsilon_points, bool)
            or not isinstance(self.epsilon_points, int)
            or self.epsilon_points < 2
        ):
            raise ValueError("epsilon_points must be an integer >= 2")

    @classmethod
    def from_values(
        cls,
        rho: RhoInput = Fraction(1, 1),
        epsilon_points: int = 21,
    ) -> JointOptimizationConfig:
        """! @brief 稳定解析公开 API 的十进制 rho。"""
        return cls(normalize_rho(rho), epsilon_points)


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
    """! @brief 运行 joint Peak/CAN/CPU anchors、ε 扫描并返回全部 Pareto 点。

    @note 不选择推荐点；observed Pareto 仅来自配置搜索发现的候选。
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
        )

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
        "peak_reference",
        seed,
        peak_result,
        evaluator,
        domain,
    )
    peak_budget = calculate_peak_budget_us(
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
        "can_anchor",
        seed,
        can_result,
        evaluator,
        domain,
    )
    violation_guardrail = (
        peak_result.objective.violation_count,
        peak_result.objective.violation_excess,
    )
    cpu_policy = _JointPolicy(
        "cpu_proxy_then_qss",
        peak_budget,
        violation_guardrail,
    )
    cpu_anchor = _run_joint_search(
        domain,
        evaluator,
        optimization_config,
        cpu_policy,
        base_seed=seed + 10_000,
        stage="cpu_anchor",
        incumbents=(can_anchor,),
    )
    if cpu_anchor.cpu_proxy > can_anchor.cpu_proxy:
        raise RuntimeError("CPU anchor lost the known feasible CAN anchor")

    epsilon_runs: list[JointEpsilonRun] = []
    candidates: list[JointSolution] = [can_anchor, cpu_anchor]
    status = "ok"
    if cpu_anchor.cpu_proxy == can_anchor.cpu_proxy:
        status = "no_observed_cpu_tradeoff"
    else:
        budgets = generate_epsilon_budgets(
            cpu_anchor.cpu_proxy,
            can_anchor.cpu_proxy,
            selected_joint_config.epsilon_points,
        )
        previous = cpu_anchor
        for index, budget in enumerate(budgets):
            epsilon_policy = _JointPolicy(
                "qss_then_cpu_proxy",
                peak_budget,
                violation_guardrail,
                budget,
            )
            feasible_incumbents = tuple(
                solution
                for solution in (previous, cpu_anchor, can_anchor)
                if solution.cpu_proxy <= budget
            )
            solution = _run_joint_search(
                domain,
                evaluator,
                optimization_config,
                epsilon_policy,
                base_seed=seed + 100_000 + index * 1_000,
                stage=f"epsilon_{index:02d}",
                incumbents=feasible_incumbents,
            )
            run = JointEpsilonRun(index, budget, solution)
            epsilon_runs.append(run)
            candidates.append(solution)
            previous = solution
        if epsilon_runs[-1].solution.qss > can_anchor.qss:
            raise RuntimeError("last epsilon run lost the feasible CAN anchor")

    pareto = filter_pareto_solutions(tuple(candidates))
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
        len(domain.decision_messages),
        len(domain.fixed_messages),
        peak_reference,
        peak_budget,
        can_anchor,
        cpu_anchor,
        tuple(epsilon_runs),
        pareto,
        performance,
        status,
    )
