"""最终论文实验输入锁与 Original baseline 精确评价。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from .exceptions import ConfigurationError, MissingFieldError
from .models import (
    ComparisonStageResult,
    ObjectiveMode,
    OffsetAssignment,
    TimeWindow,
    WeightMode,
)
from .optimization.objective import (
    ObjectivePolicy,
    calculate_objective,
    slot_load_threshold_us,
)
from .parsers.project_loader import LoadedProject, load_project


@dataclass(frozen=True, slots=True)
class FinalExperimentInput:
    """一个网段在统一 final manifest 中的输入定义。"""

    network_id: str
    dbc_path: Path
    selected_sender: str | None
    protocol: str
    routing_excel_path: Path
    routing_target_network: str
    arxml_dir: Path
    config_path: Path
    channel: str

    def __post_init__(self) -> None:
        if not self.network_id.strip():
            raise ConfigurationError("final experiment network_id must not be empty")
        if self.selected_sender is None or not self.selected_sender.strip():
            raise ConfigurationError(
                f"final experiment {self.network_id} requires explicit selected_sender"
            )
        if self.protocol not in {"CAN", "CAN_FD"}:
            raise ConfigurationError(
                f"final experiment {self.network_id} has unsupported protocol "
                f"{self.protocol!r}"
            )
        if not self.routing_target_network.strip():
            raise ConfigurationError(
                f"final experiment {self.network_id} requires routing target network"
            )
        if not self.channel.strip():
            raise ConfigurationError(
                f"final experiment {self.network_id} requires ARXML channel"
            )


def load_final_experiment_project(spec: FinalExperimentInput) -> LoadedProject:
    """按 final input lock 加载一个网段；缺 sender/routing/StartDelay/timing 即失败。"""

    if spec.protocol != "CAN_FD":
        raise ConfigurationError(
            "current final experiment pipeline only implements the locked CAN_FD "
            f"main-experiment protocol, got {spec.protocol!r} for {spec.network_id}"
        )
    loaded = load_project(
        spec.dbc_path,
        spec.arxml_dir,
        spec.config_path,
        weight_mode_override=WeightMode.FRAME_TIME_US,
        channel_override=spec.channel,
        selected_sender=spec.selected_sender,
        routing_excel_path=spec.routing_excel_path,
        routing_target_network=spec.routing_target_network,
        require_original_offsets=True,
    )
    if loaded.network.weight_mode is not WeightMode.FRAME_TIME_US:
        raise ConfigurationError("final experiment must use frame_time_us")
    if loaded.dbc_parse_result is None:
        raise RuntimeError("final experiment load lost DBC audit metadata")
    if loaded.dbc_parse_result.selected_sender != spec.selected_sender:
        raise RuntimeError("final experiment selected_sender audit mismatch")
    if loaded.routing_table is None or loaded.routing_target_network is None:
        raise RuntimeError("final experiment load lost routing audit metadata")
    if loaded.eligible_start_delay_unknown_count:
        raise MissingFieldError(
            f"{spec.network_id}: final experiment has "
            f"{loaded.eligible_start_delay_unknown_count} unknown GenMsgStartDelayTime values"
        )
    return loaded


def _release_slots(offset_us: int, cycle_time_us: int, window: TimeWindow) -> tuple[int, ...]:
    if offset_us < 0:
        raise ValueError("Original Offset must be non-negative")
    if offset_us >= window.end_us:
        return ()
    if offset_us >= window.start_us:
        first = offset_us
    else:
        delta = window.start_us - offset_us
        first = offset_us + ((delta + cycle_time_us - 1) // cycle_time_us) * cycle_time_us
    return tuple(
        (release - window.start_us) // window.slot_width_us
        for release in range(first, window.end_us, cycle_time_us)
    )


def evaluate_original_baseline(loaded: LoadedProject) -> ComparisonStageResult:
    """使用 StartDelay-only 原值评价 Original，不把越界原值偷偷替换为最小候选。

    Original 只是 baseline evaluation，可以位于优化候选集合之外；优化搜索空间仍
    严格使用每条报文的 ``allowed_offsets_us``。
    """

    started = perf_counter()
    messages = tuple(
        sorted(
            loaded.network.messages,
            key=lambda item: (item.definition_index, item.can_id, item.name),
        )
    )
    steady_loads = [0] * loaded.network.steady_window.slot_count
    startup_loads = [0] * loaded.network.startup_window.slot_count
    steady_counts = [0] * loaded.network.steady_window.slot_count
    startup_counts = [0] * loaded.network.startup_window.slot_count
    assignments: list[OffsetAssignment] = []
    for message in messages:
        if message.original_offset_us is None:
            raise MissingFieldError(
                f"message {message.name} has unknown GenMsgStartDelayTime"
            )
        offset = message.original_offset_us
        steady_slots = _release_slots(
            offset,
            message.cycle_time_us,
            loaded.network.steady_window,
        )
        startup_slots = _release_slots(
            offset,
            message.cycle_time_us,
            loaded.network.startup_window,
        )
        for index in steady_slots:
            steady_loads[index] += message.frame_time_us
            steady_counts[index] += 1
        for index in startup_slots:
            startup_loads[index] += message.frame_time_us
            startup_counts[index] += 1
        assignments.append(
            OffsetAssignment(
                message.name,
                message.can_id,
                offset,
                message.definition_index,
            )
        )
    threshold = slot_load_threshold_us(
        loaded.config.optimization.slot_width_us,
        loaded.config.model.average_load_limit,
    )
    objective = calculate_objective(
        steady_loads,
        startup_loads,
        steady_counts,
        ObjectivePolicy(ObjectiveMode.PEAK, threshold),
    )
    return ComparisonStageResult(
        name="original",
        kind="baseline",
        assignments=tuple(assignments),
        objective=objective,
        steady_slot_loads=tuple(steady_loads),
        startup_slot_loads=tuple(startup_loads),
        steady_slot_counts=tuple(steady_counts),
        startup_slot_counts=tuple(startup_counts),
        evaluation_count=0,
        accepted_moves=0,
        elapsed_seconds=perf_counter() - started,
    )
