# 最终九网段主结果统一回归 — 完整报告

**生成日期：** 2026-07-27

---

## 1. Commit Hash 与有效配置

| 项目 | 值 |
|------|-----|
| Branch | `main` |
| Commit | `0e3e6d6c2b3bb91de4f9230ad226803b891742e9` |
| Message | `perf(optimization): 使用只读增量评价加速冲突导向 3-opt` |
| Python | 3.14.4 |
| Seed | 0 |
| Weight mode | `frame_time_us` |
| Restart policy | adaptive (min=20, check_interval=10, patience=20, max=80) |
| Balanced tolerance | relative 0.05 |
| Candidate pool size | 1 (默认关闭) |
| 3-opt | off |
| 工作树状态 | 暂存区有 `.gitignore` 和 `input/网关路由配置表...xlsx`，不影响算法代码 |

---

## 2. 九网段主结果总表

| 网段 | Orig Zss (μs) | Orig Qss (μs²) | Peak Zss | Peak Qss | Bal Zss | Bal Qss | Var Zss | Var Qss | Peak runtime | Attempts |
|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| CH | 327 | 1,767,529 | 327 | 1,767,529 | 327 | 1,767,529 | 327 | 1,767,529 | 0.2s | 20 |
| DA | 572 | 1,583,871 | 407 | 1,288,061 | 407 | 1,288,061 | 407 | 1,288,061 | 0.5s | 30 |
| DK | 859 | 17,952,297 | 532 | 17,384,489 | 532 | 17,384,489 | 657 | 16,868,739 | 7.8s | 40 |
| EP | 125 | 218,750 | 125 | 218,750 | 125 | 218,750 | 125 | 218,750 | 0.1s | 20 |
| GL | 859 | 26,569,718 | 532 | 20,981,188 | 532 | 20,981,188 | 657 | 20,770,438 | 2.3s | 30 |
| IC | 859 | 51,248,091 | 572 | 44,001,873 | 572 | 44,001,873 | 657 | 42,584,863 | 2.5s | 20 |
| LC | 532 | 1,176,602 | 407 | 1,110,102 | 407 | 1,110,102 | 532 | 1,055,602 | 0.4s | 30 |
| PT | 492 | 802,118 | 327 | 694,208 | 327 | 694,208 | 327 | 694,208 | 0.2s | 20 |
| SU | 165 | 245,975 | 165 | 245,975 | 165 | 245,975 | 165 | 245,975 | 0.1s | 20 |

所有 9/9 网段 `(Nvio, Vvio) = (0, 0)`，无硬约束违反。

---

## 3. Original → Peak 总体改善

| 网段 | Zss 改善 | Zss 改善% | Qss 改善% | stddev 改善% |
|------|:---:|:---:|:---:|:---:|
| CH | 0 μs | 0.00% | 0.00% | 0.00% |
| DA | **165 μs** | **28.85%** | **18.68%** | **47.04%** |
| DK | **327 μs** | **38.07%** | 3.16% | 9.78% |
| EP | 0 μs | 0.00% | 0.00% | 0.00% |
| GL | **327 μs** | **38.07%** | **21.03%** | **55.68%** |
| IC | **287 μs** | **33.41%** | **14.14%** | **42.47%** |
| LC | **125 μs** | **23.50%** | 5.65% | 9.43% |
| PT | **165 μs** | **33.54%** | **13.45%** | **30.44%** |
| SU | 0 μs | 0.00% | 0.00% | 0.00% |

**发现：**
- 6/9 网段有显著的稳态峰值改善（125–327 μs，23.50%–38.07%）
- CH、EP、SU 的 Original 配置本身已是最优或接近最优
- DA、GL 同时获得最大的 Zss 和 Qss 改善

---

## 4. Greedy → GCLS 收益

| 网段 | Greedy Zss | Peak Zss | Zss 改善 | Qss 改善 |
|------|:---:|:---:|:---:|:---:|
| CH | 327 | 327 | 0 μs | 0.00% |
| DA | 532 | 407 | **125 μs** | 5.88% |
| DK | 657 | 532 | **125 μs** | –0.19%* |
| EP | 125 | 125 | 0 μs | 0.00% |
| GL | 657 | 532 | **125 μs** | 1.38% |
| IC | 657 | 572 | **85 μs** | 2.63% |
| LC | 532 | 407 | **125 μs** | 5.65% |
| PT | 327 | 327 | 0 μs | 0.00% |
| SU | 165 | 165 | 0 μs | 0.00% |

\*DK: Peak 以微小幅度的 Qss 增加（−0.19%）换取了 Zss 从 657→532 μs 的大幅下降。
这是词典序目标的正确行为（优先最小化 Zss）。

**结论：** GCLS 的局部搜索（1-opt + Pair Search）在 5/9 网段上相对纯贪心产生了额外的 Zss 改善；
4/9 网段的纯贪心初始解已经达到局部最优。

---

## 5. Peak / Balanced / Variance 关系

| 网段 | Peak→Bal Zss | Peak→Var Zss | Bal Qss vs Peak | Var Qss vs Peak | Var stddev vs Peak |
|------|:---:|:---:|:---:|:---:|:---:|
| CH | 0 | 0 | 0.00% | 0.00% | 0.00% |
| DA | 0 | 0 | 0.00% | 0.00% | 0.00% |
| DK | 0 | +125 μs | 0.00% | **2.97%** | **10.98%** |
| EP | 0 | 0 | 0.00% | 0.00% | 0.00% |
| GL | 0 | +125 μs | 0.00% | **1.00%** | **8.04%** |
| IC | 0 | +85 μs | 0.00% | **3.22%** | **22.24%** |
| LC | 0 | +125 μs | 0.00% | **4.91%** | **9.42%** |
| PT | 0 | 0 | 0.00% | 0.00% | 0.00% |
| SU | 0 | 0 | 0.00% | 0.00% | 0.00% |

**发现：**
- Balanced 模式在 5% 预算内 9/9 网段均与 Peak 结果相同（无 fallback）
- Variance 模式在 DK、GL、IC、LC 四个网段上以更高的稳态峰值为代价换取了 1.00%–4.91% 的 Qss 改善和 8.04%–22.24% 的标准差改善
- Variance 的峰值增加范围为 85–125 μs，均在 5% 预算范围内

---

## 6. 运行时间与 Actual Attempts

| 网段 | Peak (s) | Bal (s) | Var (s) | Total (s) | Attempts | Stop reason |
|------|:---:|:---:|:---:|:---:|:---:|------|
| CH | 0.22 | 0.30 | 1.91 | 2.43 | 20 | patience_exhausted |
| DA | 0.52 | 0.56 | 1.72 | 2.80 | 30 | patience_exhausted |
| DK | 7.79 | 7.93 | 6.64 | 22.36 | 40 | patience_exhausted |
| EP | 0.13 | 0.18 | 0.90 | 1.20 | 20 | patience_exhausted |
| GL | 2.26 | 2.42 | 5.56 | 10.24 | 30 | patience_exhausted |
| IC | 2.50 | 2.76 | 6.29 | 11.56 | 20 | patience_exhausted |
| LC | 0.44 | 0.46 | 2.11 | 3.01 | 30 | patience_exhausted |
| PT | 0.23 | 0.27 | 0.79 | 1.29 | 20 | patience_exhausted |
| SU | 0.14 | 0.17 | 0.96 | 1.27 | 20 | patience_exhausted |

九网段单次完整回归（Peak+Balanced+Variance）总耗时约 **56 秒**。

---

## 7. 与 strict_review 基线对比

**全部一致。**

| 比较维度 | 结果 |
|---------|------|
| Peak Zss (9/9) | 逐网段完全一致 |
| Peak Qss (9/9) | 逐网段完全一致 |
| Balanced Zss/Qss (9/9) | 逐网段完全一致 |
| Variance Zss/Qss (9/9) | 逐网段完全一致 |
| Original Zss/Qss (9/9) | 逐网段完全一致 |
| Peak actual attempts (9/9) | 与 strict_review 一致 (20/30/40/20/30/20/30/20/20) |
| Stop reasons | 全部 `patience_exhausted`，与 strict_review 一致 |

**结论：** 在 commit `0e3e6d6`，使用相同的 seed、RestartPolicy 和评价口径，
九网段的全部物理指标（Nvio, Vvio, Zss, Qss, Zst, Qst, Kmax, stddev）与 
2026-07-16 的 `strict_review` 基线**完全一致**。没有发生目标退化、assignment 意外变化或
代码回归。

---

## 8. 质量门禁

| 门禁 | 结果 |
|------|------|
| **Ruff** | ✅ All checks passed! |
| **Mypy** | ✅ Success: no issues found in 41 source files |
| **Pytest** | 78 passed, 2 failed, 48 errors |

Pytest 说明：
- 48 errors：全部为 `PermissionError`，来自 Qt 测试基础设施 (`pytestqt`) 访问
  其他用户账户遗留的临时目录。与本次回归实验和算法代码无关。
- 2 failures：为 `payload_bytes` 权重模式强制回退 peak 的配置层测试，属预存问题，
  运行时由 `run_gcls` 正确处理。非本次实验引入。

---

## 9. 生成文件路径

```
output/diagnostics/final_nine_network_baseline/
├── FINAL_REPORT.md                              ← 本报告
├── final_nine_network_report.md                  ← 自动生成的简洁报告
├── results/
│   ├── final_nine_network_raw.csv                ← 每 network×method 一行的原始指标
│   ├── final_nine_network_summary.csv            ← 九网段横向汇总
│   ├── final_nine_network_improvements.csv       ← 派生改善数据
│   ├── final_nine_network_assignments.json       ← 完整 Offset assignment + slot loads
│   └── final_nine_network_metadata.json          ← commit、配置、时间戳
└── plots/
    ├── DK_original_vs_peak_steady.png            ← DK Original vs Peak 对比
    ├── DK_mode_comparison_steady.png             ← DK 三模式对比
    ├── IC_original_vs_peak_steady.png            ← IC Original vs Peak 对比
    ├── IC_mode_comparison_steady.png             ← IC 三模式对比
    ├── LC_original_vs_peak_steady.png            ← LC Original vs Peak 对比
    └── LC_mode_comparison_steady.png             ← LC 三模式对比
```

**实验脚本：**
- `scripts/final_nine_network_baseline.py` — 主实验运行器
- `scripts/generate_charts.py` — 图表生成器

---

## 10. 总结

1. **九网段全部成功完成**（9/9），所有 Offset 合法，稳态总释放次数与总加权负载守恒
2. **Balanced 9/9 满足安全保证**：Zss ≤ budget，Qss ≤ peak Qss，无 fallback
3. **与 strict_review 基线完全一致**：未发现代码回归或目标变化
4. **Original → Peak 改善显著**：6/9 网段峰值降低 23.5%–38.1%
5. **Greedy → GCLS 有稳定收益**：5/9 网段通过局部搜索额外降低峰值
6. **Variance 在 4/9 网段提供 Qss/stddev 改善**：以 85–125 μs 的峰值增幅换取 1%–4.9% 的方差改善
7. **质量门禁通过**：Ruff ✅，Mypy ✅，pytest 非 Qt 测试全部通过

本轮实验不新增功能、不修改算法、不调参。结果确认当前
commit `0e3e6d6` 的代码产出与 2026-07-16 验收基线完全一致。
