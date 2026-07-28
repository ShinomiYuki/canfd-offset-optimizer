# CAN/CPU 联合细化、稳定性与 Knee 推荐验证报告

> 实验日期：2026-07-28
>
> 基线提交：`1362f81`（实验开始时的 `main` HEAD）
>
> 主实验参数：`frame_time_us`，`A_validate=3`，`rho=1`，seed 0，最多 3 个 refinement passes
>
> 精确性边界：给定完整 Offset assignment 后的 MainFunction partition 是 exact；外层 GCLS 搜索及本文 Pareto 前沿仍是 heuristic / observed。

# 1. Baseline

- 分支：`main`。
- 开始时 HEAD：`1362f81`。
- 开始时 `git status --short`：干净。
- 显式使用当前仓库 `src` 执行全量基线：

  ```powershell
  $env:PYTHONPATH=(Resolve-Path 'src').Path
  python -m pytest -q --basetemp $env:TEMP\canfd-validation-baseline
  ```

- 基线结果：`164 passed in 33.47s`。
- 审计了 `docs/can_cpu_joint_design.md`、上一阶段报告，以及 joint、GCLS、evaluator、restart、CLI、JSON writer 和相关测试。
- 本轮只扩展非 GUI 的 joint optimization path；未修改 GUI、热力图、旧 Peak/Balanced/Variance 路径、DBC writeback 或 ARXML。

# 2. 为什么需要 refinement

上一阶段已经出现初始 heuristic CAN anchor 被后续 epsilon 搜索改善的事实：

| 网络 | 初始 CAN anchor | 后续 epsilon endpoint | 关系 |
|---|---|---|---|
| GL | Q=21,569,436，P=3163 | Q=21,569,436，P=3053 | 相同 Q，CPU Proxy 更低 |
| IC | Q=43,946,685，P=2549 | Q=43,546,685，P=2449 | Q 与 CPU Proxy 同时更低 |

这不是 Pareto filter 错误，而是一次 GCLS 搜索只能产生 heuristic anchor。后续搜索可以发现更好的解，因此初始 anchors 只能作为审计记录与第一轮 incumbent，不能永久定义最终 endpoint。Peak reference 同理，也必须接受后续候选按正式 Peak comparator 的改善。

# 3. Refinement 算法

每次 joint run 维护按完整 assignment SHA-256 去重的 cumulative candidate archive。每个候选保留完整 assignment、正式 CAN objective、Peak、Qss、exact CPU Proxy、MainFunction groups、source、pass、seed、attempt 和 epsilon budget 等 provenance。

每个 refinement pass 的顺序为：

1. 以当前 archive 与 incumbent 做 Peak refinement；
2. 用正式 Peak comparator 更新 Peak reference；
3. 复用 `calculate_peak_budget_us()` 重算 guardrail，排除新预算下不可行的旧候选；
4. 以 observed CAN endpoint 为 incumbent 做 CAN endpoint refinement；
5. 以 observed CPU endpoint 和当前 CAN endpoint 为 incumbents 做 CPU endpoint refinement；
6. 由 refined endpoints 的 exact `P_min/P_max` 重新生成 `Fraction` epsilon budgets；
7. epsilon scan 按预算从 archive 中确定性选择少量优质可行 warm starts；
8. 合并 archive，按当前 Peak guardrail 过滤，再进行 assignment 去重和 Q/P dominance filtering；
9. 重新计算 observed CAN/CPU endpoints；
10. 比较 deterministic convergence signature。

Observed endpoint comparator：

- CAN endpoint：Qss、CPU Proxy、正式 Peak、canonical assignment 依次升序；
- CPU endpoint：CPU Proxy、Qss、正式 Peak、canonical assignment 依次升序。

Convergence signature 包含 Peak reference objective/signature、Peak budget、两个 endpoint 的 objective 和 assignment hash，以及有序 Pareto objective pairs 与 assignment hashes。只有相邻两个完整 pass 的 signature 完全相同才报告 `refinement_converged`；达到上限仍变化则报告 `refinement_limit_reached`。

默认最多 3 passes，参数显式有界。seed 由 base seed、stage、pass 和 attempt 的固定整数规则派生；attempts=1/3/5/10 使用相同前缀，未使用时间、`SystemRandom` 或 Python hash。

# 4. Knee 数学

Knee 只在 final refined observed Pareto 上做 post-processing，不进入 GCLS objective、epsilon constraint 或 restart selection。

对 lower-is-better 的 Q/P 前沿，使用 exact `Fraction`：

```text
x_i = (Q_i - Q_min) / (Q_max - Q_min)
y_i = (P_i - P_min) / (P_max - P_min)
s_i = 1 - x_i - y_i
```

`s_i` 是点到连接两个归一化端点之 chord 的带比例公共因子距离。对内部点最大化 `s_i`；严格 tie-break 依次为更小的 ideal-point squared distance、更小 Q、更小 P、更小 canonical assignment。

退化规则：

- 存在内部点且最大 `s_i > 0`：`geometric_knee`；
- 所有内部 chord score 均为 0：`ideal_point_fallback`；
- 1 点：`unique_solution`；
- 2 点：`no_interior_knee`，不强行推荐；
- 空前沿或无效前沿：明确失败，不伪造推荐。

Peak 和 MainFunction 数量不参与 geometric ranking；它们只作为推荐结果的展示和审计信息。

Normalized symmetric Hausdorff distance 也使用 Q/P 两个目标。比较两个前沿时，先在二者并集的公共 min/max 上归一化，再计算双向最近距离的最大值；退化轴不除零，exact squared distance 排序，最后仅显示时开平方为 float。

# 5. 自动测试

新增/扩展测试覆盖：

- archive 对同 Q、更低 P，以及 Q/P 同时改善的 endpoint refinement；
- refined `P_max` 被下一 pass epsilon scan 使用；
- 正式 Peak reference 改善、budget 重算及旧超预算候选排除；
- 完整 signature 收敛与 max-pass limit；
- attempt seed schedule 的 prefix preserving；
- exact geometric knee、straight-front fallback、1/2/empty front；
- `Fraction` 排序、输入顺序稳定性、Peak 不影响 knee；
- Hausdorff identity、reorder、shift、重复目标和退化轴；
- JSON schema v2 的 initial/refined anchors、archive、stage results、refinement、recommendation 与性能字段；
- 旧模式和端到端回归。

最终检查命令与结果见文末“最终验证”。

# 6. Attempt saturation

设置：DK/GL/IC，seed 0，endpoint-only，`rho=1`，最多 3 passes。CAN/CPU 列为 `Qss / CPU Proxy`；H 为相邻 checkpoint endpoint-front 的 common-normalized symmetric Hausdorff。

| 网络 | attempts | Z* | budget | CAN endpoint | CPU endpoint | H(prev) | passes/status | runtime(s) |
|---|---:|---:|---:|---|---|---:|---|---:|
| DK | 1 | 2699 | 2834 | 23,801,955 / 2188 | 76,258,945 / 778 | — | 2/converged | 8.548 |
| DK | 3 | 2699 | 2834 | 23,801,955 / 2188 | 76,258,945 / 778 | 0.000000 | 2/converged | 16.955 |
| DK | 5 | 2699 | 2834 | 23,801,955 / 2188 | 76,258,945 / 778 | 0.000000 | 2/converged | 25.622 |
| DK | 10 | 2699 | 2834 | 23,801,955 / 2188 | 76,258,945 / 778 | 0.000000 | 2/converged | 46.284 |
| GL | 1 | 614 | 645 | 21,569,436 / 3053 | 31,225,936 / 1743 | — | 2/converged | 14.485 |
| GL | 3 | 614 | 645 | 21,569,436 / 3053 | 31,225,936 / 1743 | 0.000000 | 2/converged | 24.765 |
| GL | 5 | 614 | 645 | 21,569,436 / 3053 | 31,225,936 / 1743 | 0.000000 | 2/converged | 36.700 |
| GL | 10 | 614 | 645 | 21,569,436 / 3053 | 31,225,936 / 1743 | 0.000000 | 2/converged | 64.389 |
| IC | 1 | 986 | 1036 | 43,546,685 / 2449 | 79,231,205 / 1489 | — | 2/converged | 24.011 |
| IC | 3 | 986 | 1036 | 43,546,685 / 2449 | 79,231,205 / 1489 | 0.000000 | 3/converged | 57.743 |
| IC | 5 | 986 | 1036 | 43,546,685 / 2449 | 79,231,205 / 1489 | 0.000000 | 3/converged | 77.739 |
| IC | 10 | 986 | 1036 | 43,546,685 / 2449 | 79,231,205 / 1489 | 0.000000 | 3/limit | 153.402 |

从 attempts=1 到 10，三个网络的 Peak 与 endpoint objective 均未改善，所有相邻 endpoint-front H 均为 0。选择 `A_validate=3`：它是包含随机 restart、并已复现 endpoint 稳定的最小 checkpoint。5/10 仍作为更高预算验证。

限制：IC attempts=10 的 assignment-level signature 在 3 passes 内仍变化，故只能说 endpoint objective saturation 得到验证，不能据此声称完整 archive/front assignment 收敛。

# 7. Refined baseline

设置：attempts=3，seed=0，`rho=1`，K=21，最多 3 passes。各解列为 `Peak / Qss / P / MF count`。

| 网络 | initial CAN | refined CAN | initial CPU | refined CPU | Pareto | passes/status | recommendation | runtime(s) |
|---|---|---|---|---|---:|---|---|---:|
| DK | 2699 / 23,801,955 / 2188 / 6 | 2699 / 23,801,955 / 1878 / 6 | 2824 / 76,258,945 / 778 / 5 | 2824 / 76,258,945 / 778 / 5 | 31 | 3/limit | geometric_knee: Q=36,731,205, P=988 | 151.942 |
| GL | 614 / 21,569,436 / 3163 / 5 | 614 / 21,306,536 / 2773 / 6 | 622 / 31,081,436 / 1773 / 5 | 625 / 31,225,936 / 1743 / 6 | 33 | 3/limit | geometric_knee: Q=24,050,536, P=2173 | 214.224 |
| IC | 986 / 43,946,685 / 2549 / 7 | 986 / 43,546,685 / 2449 / 7 | 1029 / 76,780,565 / 1519 / 7 | 1032 / 79,231,205 / 1489 / 7 | 16 | 3/limit | geometric_knee: Q=52,345,685, P=1719 | 293.658 |

结论：

- GL/IC 的已知 initial CAN anchor 问题被自动修复；GL 还发现 Q 更低的 refined CAN endpoint。
- DK 在 Q 不变时把 CAN endpoint 的 P 从 2188 降到 1878。
- CPU endpoint comparator 优先 P，因此 GL/IC 出现 Q 或 Peak 略差但 P 更低的结果是定义内行为。
- 三个完整 baseline 都在 pass 3 后仍有 assignment-level/front signature 变化，必须报告 `refinement_limit_reached`，不能声称完全收敛。

# 8. Seed stability

H 相对于 seed 0，其他参数与 refined baseline 相同。

| 网络 | seed | CAN Q/P | CPU Q/P | Pareto | H(seed0) | knee Q/P/hash 前缀 | passes/status | runtime(s) |
|---|---:|---|---|---:|---:|---|---|---:|
| DK | 0 | 23,801,955/1878 | 76,258,945/778 | 31 | 0.000000 | 36,731,205/988/`02deb5b8a6bb` | 3/limit | 151.942 |
| DK | 1 | 23,801,955/1878 | 76,258,945/778 | 31 | 0.000000 | 36,731,205/988/`02deb5b8a6bb` | 3/limit | 156.128 |
| DK | 2 | 23,801,955/1878 | 76,258,945/778 | 31 | 0.000000 | 36,731,205/988/`02deb5b8a6bb` | 3/limit | 161.231 |
| GL | 0 | 21,306,536/2773 | 31,225,936/1743 | 33 | 0.000000 | 24,050,536/2173/`c2b18283b728` | 3/limit | 214.224 |
| GL | 1 | 21,306,536/2773 | 31,225,936/1743 | 33 | 0.049434 | 23,986,536/2173/`0725f281ecd1` | 3/limit | 203.677 |
| GL | 2 | 21,306,536/2773 | 31,225,936/1743 | 33 | 0.049434 | 23,986,536/2173/`0725f281ecd1` | 3/limit | 228.307 |
| IC | 0 | 43,546,685/2449 | 79,231,205/1489 | 16 | 0.000000 | 52,345,685/1719/`39e332867e40` | 3/limit | 293.658 |
| IC | 1 | 43,546,685/2449 | 79,231,205/1489 | 16 | 0.000000 | 52,345,685/1719/`39e332867e40` | 3/limit | 293.836 |
| IC | 2 | 43,546,685/2449 | 79,231,205/1489 | 16 | 0.000000 | 52,345,685/1719/`240c4939a048` | 3/limit | 282.627 |

- DK 的 objective front、endpoints 和 knee assignment 均一致。
- IC 的 objective front 和 knee objective 一致，但 seed 2 找到同目标的不同 assignment，说明 assignment-level 稳定性未完全建立。
- GL endpoints 一致，但中间前沿有 `H=0.049434`，knee 在相同 P 下从 Q=24,050,536 移到 23,986,536。外层搜索仍存在可测 seed 敏感性。

# 9. Epsilon resolution

H 为 K=21 与 K=41 的 common-normalized symmetric Hausdorff。

| 网络 | K | Pareto | CAN Q/P | CPU Q/P | H(21,41) | knee Q/P/hash 前缀 | normalized knee (Q,P) | runtime(s) |
|---|---:|---:|---|---|---:|---|---|---:|
| DK | 21 | 31 | 23,801,955/1878 | 76,258,945/778 | 0.186824 | 36,731,205/988/`02deb5b8a6bb` | (`1292925/5245699`, `21/110`) | 151.942 |
| DK | 41 | 40 | 23,801,955/1928 | 76,258,945/778 | 0.186824 | 35,581,205/1008/`f99f7a08ef02` | (`1177925/5245699`, `1/5`) | 272.755 |
| GL | 21 | 33 | 21,306,536/2773 | 31,225,936/1743 | 0.089373 | 24,050,536/2173/`c2b18283b728` | (`13720/49597`, `43/103`) | 214.224 |
| GL | 41 | 32 | 21,306,536/2803 | 31,225,936/1743 | 0.089373 | 24,291,536/2143/`07c8286f43ea` | (`14925/49597`, `20/53`) | 340.166 |
| IC | 21 | 16 | 43,546,685/2449 | 79,231,205/1489 | 0.131505 | 52,345,685/1719/`39e332867e40` | (`73325/297371`, `23/96`) | 293.658 |
| IC | 41 | 27 | 43,546,685/2449 | 79,231,205/1489 | 0.131505 | 52,291,885/1709/`4c7761e1722b` | (`218630/892113`, `11/48`) | 476.752 |

K=41 明显增加运行时间，并在三个网络上改变 front geometry 和 knee；DK/GL 甚至在相同最小 Q 下得到不同的 endpoint P，反映外层 heuristic 搜索路径也受 budget grid 影响。因此：

- K=21 仍可作为生产默认的计算成本折中；
- K=21 不足以支持“validation-grade knee 已稳定”的结论；
- 需要更高可信度的离线验证时建议至少 K=41，并继续报告 K 敏感性，而不是只给单一 knee。

# 10. rho sensitivity

不同 rho 下的 CPU Proxy 定义不同，P 的绝对值不能当作同一物理标尺横向比较；本实验只观察结构和推荐随 rho 的变化，不选择“最佳 rho”。

| 网络 | rho | Pareto | knee Q/P | MF | TimeBase multiset (us) | method | runtime(s) |
|---|---:|---:|---|---:|---|---|---:|
| DK | 1/4 | 26 | 36,731,205 / 3313/4 | 6 | 10000, 20000, 25000, 50000, 500000, 1000000 | geometric_knee | 149.671 |
| DK | 1/2 | 29 | 35,581,205 / 1803/2 | 6 | 10000, 20000, 25000, 50000, 500000, 1000000 | geometric_knee | 149.973 |
| DK | 1 | 31 | 36,731,205 / 988 | 6 | 10000, 20000, 25000, 50000, 500000, 1000000 | geometric_knee | 151.942 |
| DK | 2 | 21 | 36,731,205 / 1201 | 6 | 10000, 20000, 25000, 50000, 500000, 1000000 | geometric_knee | 150.968 |
| DK | 4 | 18 | 33,586,205 / 1666 | 4 | 10000, 20000, 25000, 500000 | geometric_knee | 146.753 |
| GL | 1/4 | 34 | 24,050,536 / 7459/4 | 6 | 5000, 10000, 20000, 25000, 50000, 1000000 | geometric_knee | 198.942 |
| GL | 1/2 | 34 | 24,050,536 / 3935/2 | 6 | 5000, 10000, 20000, 25000, 50000, 1000000 | geometric_knee | 202.830 |
| GL | 1 | 33 | 24,050,536 / 2173 | 6 | 5000, 10000, 20000, 25000, 50000, 1000000 | geometric_knee | 214.224 |
| GL | 2 | 26 | 24,068,936 / 2584 | 5 | 5000, 10000, 20000, 25000, 1000000 | geometric_knee | 197.829 |
| GL | 4 | 12 | 23,628,936 / 3306 | 4 | 5000, 20000, 25000, 1000000 | geometric_knee | 232.569 |
| IC | 1/4 | 16 | 52,345,685 / 11271/8 | 8 | 5000, 10000, 20000, 25000, 50000, 500000, 1000000, 2000000 | geometric_knee | 305.657 |
| IC | 1/2 | 16 | 52,345,685 / 6049/4 | 8 | 5000, 10000, 20000, 25000, 50000, 500000, 1000000, 2000000 | geometric_knee | 279.942 |
| IC | 1 | 16 | 52,345,685 / 1719 | 7 | 5000, 10000, 20000, 25000, 50000, 500000, 1000000 | geometric_knee | 293.658 |
| IC | 2 | 17 | 52,145,685 / 4263/2 | 5 | 5000, 20000, 25000, 500000, 2000000 | geometric_knee | 315.563 |
| IC | 4 | 13 | 52,145,685 / 2716 | 4 | 5000, 20000, 25000, 500000 | geometric_knee | 264.873 |

15 个运行均得到 `geometric_knee`。rho 增大后固定 MainFunction 调用成本权重上升，三个网络的推荐均趋向更少分组：DK/GL 在 rho=4 时为 4 组，IC 从 rho=1/4 的 8 组降到 rho=4 的 4 组。结论对 rho 显著敏感；`rho=1` 只是未标定工程参数，不能解释为真实 ECU 参数。

# 11. Knee / Recommendation

以下为 `rho=1`、K=21、seed 0 refined baseline 上的推荐及其 Q 排序左右相邻点。

## DK：`geometric_knee`

- normalized Q：`1292925/5245699`
- normalized CPU：`21/110`
- exact knee score：`324645461/577026890`

| 位置 | Qss | CPU Proxy | Peak | MF | assignment hash |
|---|---:|---:|---:|---:|---|
| left | 34,323,705 | 1048 | 2824 | 6 | `fb40d456cc8a06317435b334215cfbfd4ed7e5d51ad43a325252c93891b84ccd` |
| selected | 36,731,205 | 988 | 2824 | 6 | `02deb5b8a6bb3c0d924119cd6405d18e0a82126fb61fd56533a54e9fc67aee18` |
| right | 42,638,205 | 938 | 2824 | 6 | `7773ade21f5216605f2b864d84b3c35730f0e376e9aed7a7302e29ab67118b67` |

## GL：`geometric_knee`

- normalized Q：`13720/49597`
- normalized CPU：`43/103`
- exact knee score：`1562660/5108491`

| 位置 | Qss | CPU Proxy | Peak | MF | assignment hash |
|---|---:|---:|---:|---:|---|
| left | 23,930,536 | 2213 | 614 | 6 | `415c7d4dcf4641df11fe378e5422ee2e7a76093516abb62a2a30d6bb3d9734d5` |
| selected | 24,050,536 | 2173 | 614 | 6 | `c2b18283b728b9ebcd87c28e9a32ce64693f3b671a87a3191ae95e497f0cf0d0` |
| right | 25,463,936 | 2163 | 614 | 6 | `b8fd1fc14ce19918737e728ce12b27bd90b512d3070dd6dd822db4259fb1e6bc` |

## IC：`geometric_knee`

- normalized Q：`73325/297371`
- normalized CPU：`23/96`
- exact knee score：`14668883/28547616`

| 位置 | Qss | CPU Proxy | Peak | MF | assignment hash |
|---|---:|---:|---:|---:|---|
| left | 52,145,685 | 1739 | 986 | 6 | `b5876c3a2c1925493016b02009f1d9e3388ba3cba0724c7c2f904a985cf859c7` |
| selected | 52,345,685 | 1719 | 986 | 7 | `39e332867e40d1ed0c5f7a02abfaad73c30fac3ebfd6bc1ff77fc4e9d87f03d7` |
| right | 55,768,885 | 1679 | 986 | 7 | `106faef7bc165744699865fff9b1be4a1403041b2e850b8dd19eb2a72ce93204` |

这些点是当前 observed front 上按 exact `1-x-y` 选出的可解释折中，不是物理意义上的唯一最优方案。seed/K 实验已经证明 GL 及三个网络的 knee 仍可能随外层搜索预算或网格变化。

# 12. 性能

Previous 为上一阶段 attempts=1、单次 21-point scan；refined 为本轮 attempts=3、最多 3-pass cumulative refinement。

| 网络 | 版本 | eval/calls | hits | misses | hit rate | unique hist | solver(s) | total(s) | solver/total | epsilon(s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DK | previous | 28,163 | 27,602 | 561 | 98.008% | 540 | 3.208 | 19.437 | 16.50% | — |
| DK | refined | 216,145 | 213,438 | 2,707 | 98.748% | 1233 | 21.134 | 151.942 | 13.91% | 127.604 |
| GL | previous | 41,049 | 40,465 | 584 | 98.577% | 565 | 3.295 | 21.803 | 15.11% | — |
| GL | refined | 407,447 | 404,179 | 3,268 | 99.198% | 1176 | 32.631 | 214.224 | 15.23% | 174.328 |
| IC | previous | 31,907 | 31,391 | 516 | 98.383% | 507 | 6.689 | 30.803 | 21.72% | — |
| IC | refined | 353,687 | 350,781 | 2,906 | 99.178% | 1008 | 51.931 | 293.658 | 17.68% | 235.793 |

Refinement 明显增加外层评估量与总时间，但 cache hit 仍为 98.748%～99.198%，exact solver 占总时间 13.91%～17.68%，均满足“hit >95% 且 solver <约25%”的审计参考。因此没有证据支持修改现有 bounded LRU=256。

# 13. 精确性与局限

- 对固定 full Offset assignment，MainFunction D-type compression、subset-DP、TimeBase 与 CPU Proxy 求解是 exact。
- Peak、CAN、CPU 和 epsilon 的 Offset 搜索仍由 GCLS/local search 启发式完成。
- Pareto 是 cumulative archive 在当前 Peak guardrail 下发现的 observed non-dominated set，不是全局 Pareto frontier。
- attempts endpoint saturation 良好，但三个主 baseline 均达到 refinement pass 上限；完整 front 尚未证明收敛。
- GL 有 seed sensitivity；K=21 与 K=41 的 Hausdorff 和 knee movement 明显。因此当前 observed front 可用于展示真实 tradeoff 和生成候选，但不足以声称“已经稳定到唯一 knee”。
- rho 尚未用 ECU WCET/profiling 标定，CPU Proxy 不是 CPU utilization。
- Knee 是 exact Pareto geometry post-processing；推荐不进入搜索，也不是唯一工程最优解。
- 需要保留 seed、attempts、K、rho、refinement status 和 assignment hash，避免脱离搜索条件引用推荐。

# 14. 第四阶段接口

JSON schema v2 已提供后续 GUI 所需的非 GUI 数据：

- `anchors.refined_peak_reference`、`refined_can_endpoint`、`refined_cpu_endpoint`；
- `pareto_solutions` 中的完整 assignments、Peak/Qss、exact CPU Proxy、MainFunction groups 与 TimeBase；
- `recommendation` 的 method、hash、exact normalized coordinates、knee score 和展示指标；
- `refinement` 的 passes、converged/limit、per-pass signature 与 endpoints；
- `candidate_archive` 和 `stage_results` 的完整 provenance；
- joint performance 与 cache 统计。

本轮没有实现 GUI，没有修改 DBC Offset writeback，也没有实现 ARXML MainFunction writeback。

## 最终验证

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
python -m ruff check .
python -m mypy
python -m pytest -q --basetemp $env:TEMP\canfd-joint-validation-final
git diff --check
```

最终结果：

- Ruff：`All checks passed!`
- mypy：`Success: no issues found in 46 source files`
- pytest：`176 passed in 28.57s`
- `git diff --check`：通过（仅有 Git 的 LF/CRLF 工作区提示，无 whitespace error）
