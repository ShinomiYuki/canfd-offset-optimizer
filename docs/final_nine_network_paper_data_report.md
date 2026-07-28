# 最终九网段论文数据报告

## 1. Final lock

- Source HEAD：`80b9ae3ec18d4c7f6ebce2eca02a6fb7b4f6922a`
- Manifest：`docs/final_nine_network_manifest.yaml`
- Routing SHA-256：`d4eabfd6725ff7f2d0db8d3c6c49a75be7ae898c651bee22846761cbc0ee84fc`
- 协议：九网段统一 CAN FD；权重：`frame_time_us`。
- Offset：15–100 ms，step=5 ms；候选集合按上界截断语义生成。
- Joint：rho=1（未标定默认场景），attempts=3，K=41，seed=0，refinement≤3。

## 2. 本轮解决的输入冲突

- 每个 DBC 显式指定 `selected_sender=FLZCU`，不存在即失败。
- 路由排除采用规范化目标网段、数值 CAN ID 与 extended flag 精确联合匹配。
- `Offset_max` 无需被 step 整除，也不额外补上 max。
- Original 只读取 `GenMsgStartDelayTime` 显式值或其声明默认值。
- 当前仓库不存在 DBC writer，本轮未额外发明写回路径。

## 3. Preflight

| network | periodic TX | route-excluded | eligible | joint decision | joint fixed | StartDelay explicit/default/unknown |
|---|---:|---:|---:|---:|---:|---:|
| CH | 9 | 0 | 9 | 8 | 1 | 9/0/0 |
| DA | 17 | 0 | 17 | 17 | 0 | 17/0/0 |
| DK | 25 | 0 | 25 | 16 | 9 | 25/0/0 |
| EP | 6 | 0 | 6 | 6 | 0 | 6/0/0 |
| GL | 25 | 0 | 25 | 23 | 2 | 25/0/0 |
| IC | 24 | 0 | 24 | 20 | 4 | 24/0/0 |
| LC | 8 | 0 | 8 | 8 | 0 | 8/0/0 |
| PT | 11 | 0 | 11 | 11 | 0 | 11/0/0 |
| SU | 7 | 0 | 7 | 7 | 0 | 7/0/0 |

## 4. CAN-only final results

| network | mode | Peak/steady Peak (µs) | Qss | startup Peak (µs) | runtime (s) | attempts |
|---|---|---:|---:|---:|---:|---:|
| CH | balanced | 327 | 1767529 | 247 | 0.312 | 1 |
| CH | greedy | 327 | 1767529 | 327 | 0.005 | - |
| CH | original | 327 | 1767529 | 327 | 0.000 | - |
| CH | peak | 327 | 1767529 | 247 | 0.229 | 20 |
| CH | variance | 327 | 1767529 | 247 | 2.075 | 20 |
| DA | balanced | 407 | 1288061 | 407 | 0.650 | 1 |
| DA | greedy | 532 | 1368561 | 407 | 0.008 | - |
| DA | original | 572 | 1583871 | 572 | 0.000 | - |
| DA | peak | 407 | 1288061 | 407 | 0.602 | 30 |
| DA | variance | 407 | 1288061 | 407 | 1.846 | 30 |
| DK | balanced | 532 | 17384489 | 532 | 9.100 | 1 |
| DK | greedy | 657 | 17351989 | 532 | 0.024 | - |
| DK | original | 859 | 17952297 | 859 | 0.000 | - |
| DK | peak | 532 | 17384489 | 532 | 8.933 | 40 |
| DK | variance | 657 | 16868739 | 532 | 8.043 | 40 |
| EP | balanced | 125 | 218750 | 125 | 0.214 | 1 |
| EP | greedy | 125 | 218750 | 125 | 0.002 | - |
| EP | original | 125 | 218750 | 125 | 0.000 | - |
| EP | peak | 125 | 218750 | 125 | 0.159 | 20 |
| EP | variance | 125 | 218750 | 125 | 1.089 | 20 |
| GL | balanced | 532 | 20981188 | 532 | 2.814 | 1 |
| GL | greedy | 657 | 21275438 | 532 | 0.030 | - |
| GL | original | 859 | 26569718 | 657 | 0.000 | - |
| GL | peak | 532 | 20981188 | 532 | 2.603 | 30 |
| GL | variance | 657 | 20770438 | 407 | 6.200 | 30 |
| IC | balanced | 572 | 44001873 | 572 | 3.154 | 1 |
| IC | greedy | 657 | 45189863 | 532 | 0.040 | - |
| IC | original | 859 | 51248091 | 859 | 0.000 | - |
| IC | peak | 572 | 44001873 | 572 | 2.872 | 20 |
| IC | variance | 657 | 42584863 | 532 | 7.273 | 20 |
| LC | balanced | 407 | 1110102 | 327 | 0.546 | 1 |
| LC | greedy | 532 | 1176602 | 327 | 0.002 | - |
| LC | original | 532 | 1176602 | 532 | 0.000 | - |
| LC | peak | 407 | 1110102 | 327 | 0.496 | 30 |
| LC | variance | 532 | 1055602 | 327 | 2.660 | 30 |
| PT | balanced | 327 | 694208 | 327 | 0.286 | 1 |
| PT | greedy | 327 | 694208 | 327 | 0.004 | - |
| PT | original | 492 | 802118 | 492 | 0.000 | - |
| PT | peak | 327 | 694208 | 327 | 0.251 | 20 |
| PT | variance | 327 | 694208 | 327 | 0.879 | 20 |
| SU | balanced | 165 | 245975 | 125 | 0.199 | 1 |
| SU | greedy | 165 | 245975 | 165 | 0.002 | - |
| SU | original | 165 | 245975 | 165 | 0.000 | - |
| SU | peak | 165 | 245975 | 125 | 0.158 | 20 |
| SU | variance | 165 | 245975 | 125 | 1.054 | 20 |

五组预先指定的相对比较（Original→Greedy/Peak/Balanced、Peak→Balanced/Variance）已保存到 `summary/can_only_improvements.csv`；原始值与差值、百分比同时保留。

这些是同一 eligible set 下的事实性结果；不据此评价旧结果“更好”或“更差”。

## 5. CAN/CPU final results

| network | CAN endpoint (Q,CPU) | CPU endpoint (Q,CPU) | Pareto | knee/fallback | recommended (Q,CPU) |
|---|---|---|---:|---|---|
| CH | (1767529, 1094/1) | (2861279, 654/1) | 4 | geometric_knee | (2548779, 674/1) |
| DA | (1288061, 2180/1) | (1723561, 1550/1) | 10 | geometric_knee | (1401811, 1830/1) |
| DK | (23801955, 1928/1) | (76258945, 778/1) | 40 | geometric_knee | (35581205, 1008/1) |
| EP | (218750, 920/1) | (218750, 920/1) | 1 | unique_solution | (218750, 920/1) |
| GL | (21306536, 2803/1) | (31225936, 1743/1) | 32 | geometric_knee | (24291536, 2143/1) |
| IC | (43546685, 2449/1) | (79231205, 1489/1) | 27 | geometric_knee | (52291885, 1709/1) |
| LC | (1110102, 1090/1) | (1110102, 1090/1) | 1 | unique_solution | (1110102, 1090/1) |
| PT | (694208, 1680/1) | (891708, 1280/1) | 4 | ideal_point_fallback | (819208, 1430/1) |
| SU | (245975, 860/1) | (245975, 860/1) | 1 | unique_solution | (245975, 860/1) |

## 6. Objective vs assignment stability

| network | passes | objective stable | assignment stable | termination |
|---|---:|---|---|---|
| CH | 2 | True | True | refinement_converged |
| DA | 3 | True | False | refinement_limit_reached |
| DK | 3 | False | False | refinement_limit_reached |
| EP | 2 | True | True | refinement_converged |
| GL | 3 | False | False | refinement_limit_reached |
| IC | 3 | False | False | refinement_limit_reached |
| LC | 2 | True | True | refinement_converged |
| PT | 3 | True | True | refinement_converged |
| SU | 2 | True | True | refinement_converged |

## 7. 特殊网络 / 退化情况

- EP：status=no_observed_cpu_tradeoff，Pareto=1，recommendation=unique_solution。
- LC：status=no_observed_cpu_tradeoff，Pareto=1，recommendation=unique_solution。
- PT：status=ok，Pareto=4，recommendation=ideal_point_fallback。
- SU：status=no_observed_cpu_tradeoff，Pareto=1，recommendation=unique_solution。

## 8. Runtime

| network | joint total (s) | exact solver (s) | solver share | calls | cache hit rate |
|---|---:|---:|---:|---:|---:|
| CH | 49.804 | 6.056 | 0.1216 | 147591 | 0.9993 |
| DA | 134.984 | 32.131 | 0.2380 | 507914 | 0.9967 |
| DK | 291.441 | 39.580 | 0.1358 | 390433 | 0.9911 |
| EP | 4.535 | 1.130 | 0.2493 | 35767 | 0.9981 |
| GL | 379.063 | 56.893 | 0.1501 | 700078 | 0.9948 |
| IC | 567.239 | 87.182 | 0.1537 | 624277 | 0.9952 |
| LC | 3.688 | 0.659 | 0.1788 | 20800 | 0.9985 |
| PT | 55.739 | 12.733 | 0.2284 | 266717 | 0.9994 |
| SU | 5.739 | 1.487 | 0.2591 | 38272 | 0.9971 |

## 9. 质量门禁

- 修改前 baseline：176 passed；Ruff、mypy 通过。
- 修改后：189 passed；Ruff、mypy（48 个 source files）通过。
- 数据验证：`paper_ready=true`，见 `summary/data_validation.json`。

## 10. 与旧九网段结果的差异

旧九网段结果降级为开发期证据。本轮同时改变了 sender 显式锁、路由排除、StartDelay-only Original 解析与 current worktree，因此消息数、Peak、Qss 的变化属于输入与代码口径差异，不用于宣称新结果天然更优。

### 10.1 逐网数值核对

旧开发期 CAN-only artifacts 与本轮最终 artifacts 间，九个网络的 eligible message count、Peak 模式 Zss 与 Qss 均逐网相同；Original、Balanced、Variance 的对应 Zss/Qss 也未出现数值变化。这是因为权威 sender 恰好均为旧路径选到的 FLZCU、routing 精确交集为 0，且最终 eligible messages 均有显式 GenMsgStartDelayTime。修复关闭了输入污染风险并提升了可追溯性，但没有人为制造数值差异。

## 11. 论文可用性

- Paper-ready：本目录下九网段 CAN-only 与 rho=1/K=41 joint 主结果。
- Preliminary/sensitivity：既有 DK/GL/IC seed、rho、K、attempt saturation 结果。
- 全部 machine-readable 原始结果位于 `output/final_paper_nine_network/`。
