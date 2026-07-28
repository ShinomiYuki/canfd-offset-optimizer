# 九网段最终主结果统一回归报告

**生成时间：** 2026-07-27T08:12:28.157207+00:00
**Commit：** `0e3e6d6c`
**配置：** seed=0, adaptive 20/10/20/80, balanced tolerance 5%

## 九网段主结果总表

| 网段 | Orig Zss | Orig Qss | Peak Zss | Peak Qss | Bal Zss | Bal Qss | Var Zss | Var Qss | Peak runtime | Actual attempts |
|------|------|------|------|------|------|------|------|------|------|------|
| CH | 327 | 1767529 | 327 | 1767529 | 327 | 1767529 | 327 | 1767529 | 0.2s | 20 |
| DA | 572 | 1583871 | 407 | 1288061 | 407 | 1288061 | 407 | 1288061 | 0.5s | 30 |
| DK | 859 | 17952297 | 532 | 17384489 | 532 | 17384489 | 657 | 16868739 | 7.6s | 40 |
| EP | 125 | 218750 | 125 | 218750 | 125 | 218750 | 125 | 218750 | 0.1s | 20 |
| GL | 859 | 26569718 | 532 | 20981188 | 532 | 20981188 | 657 | 20770438 | 2.4s | 30 |
| IC | 859 | 51248091 | 572 | 44001873 | 572 | 44001873 | 657 | 42584863 | 2.5s | 20 |
| LC | 532 | 1176602 | 407 | 1110102 | 407 | 1110102 | 532 | 1055602 | 0.5s | 30 |
| PT | 492 | 802118 | 327 | 694208 | 327 | 694208 | 327 | 694208 | 0.2s | 20 |
| SU | 165 | 245975 | 165 | 245975 | 165 | 245975 | 165 | 245975 | 0.1s | 20 |

## Original → Peak 改善

| 网段 | Zss 改善 (abs) | Zss 改善 (%) | Qss 改善 (%) | stddev 改善 (%) |
|------|------|------|------|------|
| CH | 0 | 0.00% | 0.00% | 0.00% |
| DA | 165 | 28.85% | 18.68% | 47.04% |
| DK | 327 | 38.07% | 3.16% | 9.78% |
| EP | 0 | 0.00% | 0.00% | 0.00% |
| GL | 327 | 38.07% | 21.03% | 55.68% |
| IC | 287 | 33.41% | 14.14% | 42.47% |
| LC | 125 | 23.50% | 5.65% | 9.43% |
| PT | 165 | 33.54% | 13.45% | 30.44% |
| SU | 0 | 0.00% | 0.00% | 0.00% |

## Greedy → Peak GCLS 收益

| 网段 | Greedy Zss | Peak Zss | Zss 改善 | Qss 改善 (%) |
|------|------|------|------|------|
| CH | 327 | 327 | 0 | 0.00% |
| DA | 532 | 407 | 125 | 5.88% |
| DK | 657 | 532 | 125 | -0.19% |
| EP | 125 | 125 | 0 | 0.00% |
| GL | 657 | 532 | 125 | 1.38% |
| IC | 657 | 572 | 85 | 2.63% |
| LC | 532 | 407 | 125 | 5.65% |
| PT | 327 | 327 | 0 | 0.00% |
| SU | 165 | 165 | 0 | 0.00% |

## Peak / Balanced / Variance 关系

| 网段 | Peak Zss | Bal Zss | Var Zss | Bal Qss vs Peak | Var Qss vs Peak | Var stddev vs Peak | Bal fallback? | Bal within budget? |
|------|------|------|------|------|------|------|------|------|
| CH | 327 | 327 | 327 | 0.00% | 0.00% | 0.00% | no | YES |
| DA | 407 | 407 | 407 | 0.00% | 0.00% | 0.00% | no | YES |
| DK | 532 | 532 | 657 | 0.00% | 2.97% | 10.98% | no | YES |
| EP | 125 | 125 | 125 | 0.00% | 0.00% | 0.00% | no | YES |
| GL | 532 | 532 | 657 | 0.00% | 1.00% | 8.04% | no | YES |
| IC | 572 | 572 | 657 | 0.00% | 3.22% | 22.24% | no | YES |
| LC | 407 | 407 | 532 | 0.00% | 4.91% | 9.42% | no | YES |
| PT | 327 | 327 | 327 | 0.00% | 0.00% | 0.00% | no | YES |
| SU | 165 | 165 | 165 | 0.00% | 0.00% | 0.00% | no | YES |

## 运行时间与 Attempts

| 网段 | Peak runtime (s) | Bal runtime (s) | Var runtime (s) | Actual attempts | Stop reason |
|------|------|------|------|------|------|
| CH | 0.2317 | 0.3185 | 2.0051 | 20 | patience_exhausted |
| DA | 0.5216 | 0.5652 | 1.682 | 30 | patience_exhausted |
| DK | 7.6299 | 7.7711 | 6.6226 | 40 | patience_exhausted |
| EP | 0.1386 | 0.1777 | 0.9364 | 20 | patience_exhausted |
| GL | 2.4405 | 2.6136 | 5.7044 | 30 | patience_exhausted |
| IC | 2.5176 | 2.7824 | 6.4055 | 20 | patience_exhausted |
| LC | 0.5079 | 0.5357 | 2.181 | 30 | patience_exhausted |
| PT | 0.2291 | 0.2601 | 0.7661 | 20 | patience_exhausted |
| SU | 0.1325 | 0.1692 | 0.9262 | 20 | patience_exhausted |

## 一致性检查

- 完成网段数：9/9
- 所有 Peak Nvio=0：YES
- 所有 Balanced Zss ≤ budget：YES
- 所有 Balanced Qss ≤ Peak Qss：YES

## 输出文件

- `results/final_nine_network_raw.csv`
- `results/final_nine_network_summary.csv`
- `results/final_nine_network_improvements.csv`
- `results/final_nine_network_assignments.json`
- `results/final_nine_network_metadata.json`
- `results/final_nine_network_report.md`