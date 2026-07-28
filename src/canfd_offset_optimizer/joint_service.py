"""! @file joint_service.py
@brief 联合优化的非 GUI service 入口。
"""

from __future__ import annotations

from .optimization.joint import (
    JointOptimizationConfig,
    JointOptimizationResult,
    optimize_can_cpu_balanced,
)
from .parsers.project_loader import LoadedProject


def run_joint_optimization(
    loaded: LoadedProject,
    network_id: str,
    *,
    seed: int = 0,
    joint_config: JointOptimizationConfig | None = None,
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
    )
