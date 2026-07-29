"""! @file joint_service.py
@brief 联合优化的非 GUI service 入口。
"""

from __future__ import annotations

from .optimization.joint import (
    CancellationCheck,
    JointDomain,
    JointOptimizationConfig,
    JointOptimizationResult,
    JointProgressCallback,
    build_joint_domain,
    optimize_can_cpu_balanced,
)
from .parsers.project_loader import LoadedProject
from .timeline.state import SearchState


def run_joint_optimization(
    loaded: LoadedProject,
    network_id: str,
    *,
    seed: int = 0,
    joint_config: JointOptimizationConfig | None = None,
    cancellation_check: CancellationCheck | None = None,
    progress_callback: JointProgressCallback | None = None,
) -> JointOptimizationResult:
    """! @brief 按已加载网络的正式 weight mode 运行 CAN/CPU 联合优化。"""
    return optimize_can_cpu_balanced(
        network_id,
        loaded.network.messages,
        loaded.config.optimization,
        loaded.config.objective,
        average_load_limit=loaded.config.model.average_load_limit,
        weight_mode=loaded.network.weight_mode,
        seed=seed,
        joint_config=joint_config,
        cancellation_check=cancellation_check,
        progress_callback=progress_callback,
    )


def materialize_joint_state(
    loaded: LoadedProject,
    offsets_by_name: dict[str, int],
) -> tuple[JointDomain, SearchState]:
    """Build the formal full-domain state for one selected Joint assignment."""
    domain = build_joint_domain(loaded.network.messages, loaded.config.optimization)
    decision_names = {message.name for message in domain.decision_messages}
    if set(offsets_by_name) != {message.name for message in domain.all_messages}:
        raise ValueError("joint assignment must contain every eligible message")
    if any(
        offsets_by_name[message.name] != 0 for message in domain.fixed_messages
    ):
        raise ValueError("joint fixed long-period messages must keep Offset=0")
    state = domain.new_state()
    state.apply_assignments(
        {
            name: offset
            for name, offset in offsets_by_name.items()
            if name in decision_names
        }
    )
    return domain, state
