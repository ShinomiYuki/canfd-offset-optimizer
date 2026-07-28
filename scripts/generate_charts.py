"""! Generate charts for final nine-network baseline regression.

Generates:
1. Original vs Peak steady slot load for DK (representative: big improvement)
2. Peak vs Balanced vs Variance for DK (Qss/peak trade-off)
3. Peak vs Balanced vs Variance for IC (biggest variance Qss improvement)
"""
# ruff: noqa: E402

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT / "src"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib import rcParams

# Use CJK-compatible fallback
rcParams["font.family"] = "sans-serif"
rcParams["font.sans-serif"] = ["SimHei", "Noto Sans CJK SC", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False

RESULTS_DIR = _PROJECT / "output" / "diagnostics" / "final_nine_network_baseline" / "results"
PLOTS_DIR = _PROJECT / "output" / "diagnostics" / "final_nine_network_baseline" / "plots"
PLOTS_DIR.mkdir(parents=True, exist_ok=True)


def load_assignments() -> dict:
    with open(RESULTS_DIR / "final_nine_network_assignments.json", encoding="utf-8") as f:
        return json.load(f)


def plot_original_vs_peak(network: str, data: dict) -> None:
    """Original vs Peak steady slot load comparison."""
    orig = data.get("original", {}).get("steady_slot_loads", [])
    peak = data.get("peak", {}).get("steady_slot_loads", [])

    if not orig or not peak:
        print(f"  [{network}] No slot load data, skipping Original vs Peak plot")
        return

    fig, ax = plt.subplots(figsize=(12, 5))
    x = range(len(orig))

    ax.fill_between(x, orig, alpha=0.3, color="#4472C4", label=f"{network} Original", step="mid")
    ax.fill_between(x, peak, alpha=0.5, color="#ED7D31", label=f"{network} Peak", step="mid")
    ax.plot(x, orig, color="#4472C4", linewidth=1, drawstyle="steps-mid")
    ax.plot(x, peak, color="#ED7D31", linewidth=1.5, drawstyle="steps-mid")

    ax.set_xlabel("Steady Slot (5 ms)", fontsize=11)
    ax.set_ylabel("Slot Load (us)", fontsize=11)
    ax.set_title(f"{network} — Original vs Peak Steady Slot Load", fontsize=13, fontweight="bold")
    ax.legend(fontsize=10)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / f"{network}_original_vs_peak_steady.png", dpi=150)
    plt.close(fig)
    print(f"  [{network}] Original vs Peak plot saved")


def plot_mode_comparison(network: str, data: dict) -> None:
    """Peak vs Balanced vs Variance steady slot load."""
    peak_l = data.get("peak", {}).get("steady_slot_loads", [])
    bal_l = data.get("balanced", {}).get("steady_slot_loads", [])
    var_l = data.get("variance", {}).get("steady_slot_loads", [])

    if not peak_l or not bal_l or not var_l:
        print(f"  [{network}] Missing slot data, skipping mode comparison")
        return

    fig, ax = plt.subplots(figsize=(12, 5))
    x = range(len(peak_l))

    ax.plot(x, peak_l, color="#4472C4", linewidth=1.5, label="Peak", drawstyle="steps-mid")
    ax.plot(x, bal_l, color="#A5A5A5", linewidth=1.5, label="Balanced (5%)", drawstyle="steps-mid")
    ax.plot(x, var_l, color="#FFC000", linewidth=1.5, label="Variance", drawstyle="steps-mid")

    ax.set_xlabel("Steady Slot (5 ms)", fontsize=11)
    ax.set_ylabel("Slot Load (us)", fontsize=11)
    ax.set_title(f"{network} — Peak vs Balanced vs Variance Steady Slot Load", fontsize=13, fontweight="bold")
    ax.legend(fontsize=10)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / f"{network}_mode_comparison_steady.png", dpi=150)
    plt.close(fig)
    print(f"  [{network}] Mode comparison plot saved")


def main() -> None:
    print("Generating charts...")
    data = load_assignments()

    # Network 1: DK — clearly visible Original→Peak improvement + Variance trade-off
    if "DK" in data:
        plot_original_vs_peak("DK", data["DK"])
        plot_mode_comparison("DK", data["DK"])

    # Network 2: IC — largest Variance Qss improvement
    if "IC" in data:
        plot_original_vs_peak("IC", data["IC"])
        plot_mode_comparison("IC", data["IC"])

    # Network 3: LC — clear Variance Qss improvement, smaller scale
    if "LC" in data:
        plot_original_vs_peak("LC", data["LC"])
        plot_mode_comparison("LC", data["LC"])

    print(f"Charts saved to {PLOTS_DIR}")


if __name__ == "__main__":
    main()
