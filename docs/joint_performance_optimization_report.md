# CAN-CPU Joint 无损性能优化审计报告

## 1. 初始状态

- 工作区：`E:\DesktopFiles\canfd-offset-optimizer`
- 分支：`feature/joint-gui`
- 性能基线 SHA：`bd1c747d5452acabc4cd40ea73644ea2e66dea25`
- 基线说明：以上本地 `HEAD` 是本轮开始时的正式基线；没有回退到较旧的远端版本。
- Python：3.14.4
- 导入路径：`E:\DesktopFiles\canfd-offset-optimizer\src\canfd_offset_optimizer\__init__.py`
- 系统：Windows 11 10.0.22621，AMD64 Family 25 Model 116，16 个逻辑处理器
- Benchmark 固定参数：K=21、attempts=3、max refinement passes=3、seed=0、
  `endpoint_only=false`、`rho=1`、Peak tolerance=0.05。

所有 Python、pytest、benchmark 和 GUI 验证命令都显式设置：

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
```

## 2. 最近一次真实 GUI 输出审计

最近的可完整审计输出是：

```text
release/CANFDOffsetOptimizer-1.0-win-x64/user_output/20260729_171100_767435
```

其 `run_config.json` 与要求的 K=21、attempts=3、refinement=3、seed=0、
`endpoint_only=false`、`rho=1` 一致，批处理日志记录：

- wall clock：2377.856674 s（39.631 min）
- discovered：22 个网络输入
- succeeded：19
- failed：1
- skipped：2
- 已生成 Joint summary：20
- 20 个 Joint summary 的算法时间合计：2371.478448 s

因此它确实是用户所述“约 40 分钟”的真实 GUI 输出，但**不是可唯一确认的九网络运行**；
不能把 22 个输入的批处理误报为九网络基线。该目录只读审计，没有被 benchmark 修改。

### 2.1 真实 GUI 输出逐网络统计

`total/refinement/epsilon/solver` 均为秒；`hit` 为 MainFunction exact solver cache
命中率。推荐 hash、完整 Pareto、端点和 refinement provenance 保存在各自
`joint_summary.json` 中。LC 的 Joint 搜索形成了 summary，但因没有可自动推荐的内部折中点，
批处理最终状态为 failed。

| 网络 | Joint 状态 | total | refinement | epsilon | evaluations | solver calls | hits | misses | hit | unique D | solver | Pareto |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BD | ok | 97.930 | 96.091 | 76.644 | 252520 | 252520 | 252266 | 254 | 99.90% | 254 | 16.316 | 5 |
| BD_2 | ok | 98.243 | 95.306 | 76.357 | 265402 | 265402 | 265077 | 325 | 99.88% | 288 | 16.856 | 5 |
| CH | ok | 30.466 | 29.543 | 24.755 | 121539 | 121539 | 121089 | 450 | 99.63% | 298 | 7.136 | 8 |
| CH_2 | ok | 37.529 | 36.743 | 31.730 | 197849 | 197849 | 197718 | 131 | 99.93% | 131 | 7.624 | 7 |
| DA | ok | 78.519 | 76.843 | 65.567 | 272073 | 272073 | 269327 | 2746 | 98.99% | 1131 | 20.943 | 14 |
| DA_2 | ok | 83.927 | 83.422 | 78.143 | 315302 | 315302 | 314933 | 369 | 99.88% | 289 | 18.581 | 6 |
| DK | ok | 137.275 | 134.009 | 112.226 | 212475 | 212475 | 209852 | 2623 | 98.77% | 1060 | 28.211 | 25 |
| DK_2 | ok | 202.210 | 198.697 | 164.760 | 344337 | 344337 | 338263 | 6074 | 98.24% | 1772 | 45.098 | 18 |
| DM | no_observed_cpu_tradeoff | 3.069 | 2.161 | 0.000 | 14548 | 14548 | 14326 | 222 | 98.47% | 222 | 0.661 | 1 |
| EP | no_observed_cpu_tradeoff | 6.173 | 4.690 | 0.000 | 35767 | 35767 | 35698 | 69 | 99.81% | 69 | 1.528 | 1 |
| EP_2 | ok | 168.506 | 165.930 | 147.355 | 138109 | 138109 | 138050 | 59 | 99.96% | 59 | 8.854 | 5 |
| GL | ok | 276.847 | 272.189 | 236.973 | 382851 | 382851 | 378807 | 4044 | 98.94% | 1356 | 39.893 | 22 |
| GL_2 | ok | 267.611 | 261.375 | 221.290 | 462962 | 462962 | 461973 | 989 | 99.79% | 432 | 35.272 | 7 |
| IC | ok | 354.677 | 344.977 | 293.440 | 346026 | 346026 | 343499 | 2527 | 99.27% | 1006 | 60.671 | 14 |
| IC_2 | ok | 378.124 | 370.720 | 313.850 | 477248 | 477248 | 472990 | 4258 | 99.11% | 1660 | 81.213 | 16 |
| LC | ok | 19.846 | 18.747 | 13.293 | 85680 | 85680 | 85566 | 114 | 99.87% | 114 | 3.611 | 2 |
| PT | ok | 33.959 | 33.158 | 26.802 | 183408 | 183408 | 181565 | 1843 | 99.00% | 646 | 7.979 | 14 |
| PT_2 | ok | 60.194 | 58.835 | 50.493 | 212224 | 212224 | 211781 | 443 | 99.79% | 279 | 13.334 | 10 |
| SU | ok | 14.634 | 14.093 | 10.734 | 83535 | 83535 | 83345 | 190 | 99.77% | 190 | 2.575 | 3 |
| SU_2 | ok | 21.740 | 21.150 | 18.122 | 140357 | 140357 | 139319 | 1038 | 99.26% | 435 | 6.544 | 8 |

## 3. Profiling：约 40 分钟花在哪里

从真实输出选择 IC（慢）、CH（中）、LC（快）作为 representative networks。
未插 profiler 的基线分别为 280.272 s、27.580 s、3.682 s。

对最慢 representative IC 运行标准库 `cProfile`。Profiler 将 wall clock 放大到
1094.262 s，因此该时间不参与 speedup 计算，只用于热点归因。

| 函数 | calls | cumulative | 占 profiled total |
|---|---:|---:|---:|
| `optimize_can_cpu_balanced` | 1 | 1094.260 s | 100.0% |
| `_run_joint_search` | 70 | 1086.222 s | 99.3% |
| `JointEvaluator.evaluate_state` | 353687 | 772.666 s | 70.6% |
| `_joint_single_search` | 480 | 766.884 s | 70.1% |
| `SearchState._change_contribution` | 10446084 | 413.940 s | 37.8% |
| `SearchState.validate_invariants` | 354364 | 397.579 s | 36.3% |
| `calculate_objective` | 942408 | 256.041 s | 23.4% |
| `solve_main_function_partition` | 353687 | 204.261 s | 18.7% |
| `_solve_histogram_cached`（cache miss） | 2906 | 94.591 s | 8.6% |
| `_joint_pair_search` | 21 | 79.202 s | 7.2% |
| `JointEvaluator.full_assignments` | 540033 | 29.718 s | 2.7% |

这些 cumulative 时间互相包含，不能相加。测量结论是：主要时间在
Joint refinement/epsilon 的 inner search 中反复执行完整候选评价，而不是 PNG、CSV、
DBC 或 JSON 输出。即使 exact solver cache 命中，旧路径仍重复执行完整 invariant validation、
assignment/MainFunction message/group 物化、objective 扫描及已知 baseline/old-offset 评价。

当前代码的 CH 复测 profile（30.416 s，仍只用于热点）显示，MainFunction proxy 快路径累计仅
0.772 s，D histogram 0.681 s；剩余主要热点转移到
`conflict_pair_search`（20.368 s）、`_change_contribution`（13.624 s）和
`calculate_objective`（7.007 s）。

## 4. 已实施的无损优化

1. **去掉 single search 的重复 old-offset 评价。** 当前状态已经是正式 baseline；
   遍历 candidate 时跳过相同 offset，comparator、candidate 顺序和 tie-break 不变。
2. **携带 current metrics。** single/pair search 在状态未变化时复用已知 exact metrics，
   接受 move 后携带被选 candidate 的 metrics，不重复评价同一 state。
3. **exact CPU Proxy-only 路径。** `solve_main_function_proxy_exact()` 直接返回既有
   `_solve_histogram_cached()` 的 exact `Fraction` 结果，没有另写近似公式。
4. **延迟 MainFunction group 物化。** inner candidate 只计算 CAN Objective 与 exact CPU
   Proxy；仅在形成正式 `JointSolution` 时调用完整 partition solver，并 assert 两条路径的
   CAN objective 与 CPU Proxy 完全相等。正式输出仍包含完整 groups 和 message membership。
5. **直接构造 exact D histogram。** fixed message 的 `D=T` 预计算；decision message 使用
   原定义 `gcd(period_us, offset_us)`，避免为每个候选创建临时 assignment 和
   MainFunctionMessage。
6. **直接构造 canonical signature。** 按既有 canonical message 顺序，从 state/fixed offset
   直接构造相同 tuple，不为每个候选创建 `OffsetAssignment` 对象。
7. **合并 objective 扫描。** 在同一次遍历中完成非负校验、peak、平方和及 release-count
   peak 计算；数学字段、比较顺序和 guardrail 不变。

没有修改 K、attempts、refinement、offset domain、seed、Pair Search、Peak guardrail、
epsilon stage、Pareto、knee、rho、Qss、MainFunction exact partition 或任何搜索预算。

### 4.1 Cache 决策

没有调整 bounded LRU cache 大小。最终九网络的基线 aggregate hit rate 已为 99.324%，
misses 仅 10939；没有证据支持以更高内存占用换取收益。优化后 unique D histogram 总数也与
基线完全相同（4489）。

### 4.2 网络并行决策

没有接入网络级并行。Profile 确认工作负载是 CPU-bound，线程池不会绕过 Python CPU 限制；
正式接入多进程还必须同时证明 Windows spawn、GUI cancellation、partial failure、
顺序收集、输出隔离和 PyInstaller packaging。单网络无损优化已使九网络算法时间合计获得
2.537x，现阶段为进一步 wall-clock 收益引入该复杂度和发布风险不划算。worker 数因此为
不适用；可在后续独立任务中对 1/2/4 个进程做受控实验。

## 5. GUI 时间单位修复

Joint MainFunction 报文明细现在同时显示：

- `TimeBase(μs)` 与 `TimeBase(ms)`
- `Cycle(ms)`
- `Offset(ms)`
- `D(μs)` 与 `D(ms)`

正式 DTO 的 `d_us` 保持不变。统一整数格式化 helper 不使用二进制浮点，验证：

- 5000 μs → 5 ms
- 20000 μs → 20 ms
- 1500 μs → 1.5 ms
- 1250 μs → 1.25 ms
- 1 μs → 0.001 ms

该修改已单独提交为 `5e08e46 fix(gui): 改善联合调度时间单位显示`。

## 6. 语义等价验证

Benchmark 工具保存并逐字段比较完整 machine-readable semantic JSON，性能计数器不参与
语义比较。比较范围包括：

- initial/refined Peak reference、CAN/CPU endpoints 和所有 hashes；
- 每个 epsilon budget、solution hash、assignment、objective；
- ordered Pareto objectives、hashes、assignments；
- recommendation method/hash/index 与 exact normalized values；
- 完整 recommendation/stage assignments；
- MainFunction group timebase、proxy、D types、message membership；
- 每次 refinement 的 endpoints、front、signature、终止原因和稳定性；
- seed schedule、actual attempts、accepted moves、stop reason。

九网络 `comparison.json` 的 `all_semantic_equal=true`。CH、DA、DK、EP、GL、IC、LC、PT、
SU 每个网络的上述全部字段均 identical；不只是推荐值“接近”。

证据目录：

```text
output/diagnostics/joint_performance_optimization/baseline_nine
output/diagnostics/joint_performance_optimization/optimized_nine
```

## 7. Representative benchmark

所有数据均为未启用 profiler、相同输入与固定参数的算法时间。

| Network | Before | After | Speedup | Recommendation Hash Equal |
|---|---:|---:|---:|---|
| IC（慢） | 280.272 s | 123.342 s | 2.272x | yes |
| CH（中） | 27.580 s | 14.714 s | 1.874x | yes |
| LC（快） | 3.682 s | 2.184 s | 1.686x | yes |

## 8. 最终九网络 K21 benchmark

最终九网络只执行了一次 optimized full run。该次进程 wall clock 为约 465.7 s；
各网络记录的 load+optimization wall time 合计 464.058 s。严格可比的算法时间合计从
786.502 s 降至 309.954 s，即 **2.537x**。

| Network | Before | After | Speedup | Eval before | Eval after | Solver before | Solver after | Semantic equal |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| CH | 27.580 | 14.714 | 1.874x | 87937 | 80513 | 3.363 | 0.209 | yes |
| DA | 68.249 | 18.696 | 3.650x | 297474 | 269507 | 15.805 | 1.460 | yes |
| DK | 149.007 | 73.733 | 2.021x | 216145 | 195420 | 20.611 | 7.015 | yes |
| EP | 5.113 | 1.819 | 2.812x | 35767 | 34785 | 1.270 | 0.086 | yes |
| GL | 214.894 | 60.165 | 3.572x | 407447 | 367614 | 32.642 | 4.262 | yes |
| IC | 280.272 | 123.342 | 2.272x | 353687 | 318856 | 49.467 | 28.049 | yes |
| LC | 3.682 | 2.184 | 1.686x | 20800 | 19814 | 0.641 | 0.058 | yes |
| PT | 32.541 | 13.038 | 2.496x | 161569 | 147516 | 7.321 | 0.507 | yes |
| SU | 5.163 | 2.263 | 2.281x | 38272 | 37156 | 1.268 | 0.126 | yes |

真实 GUI 的 39.631 min 来自 22 个输入，最终 benchmark 来自锁定的九网络，故两者只能做
observed wall-clock 描述，不能声称是严格同样批次的 scientific speedup。严格 speedup 使用
同一九网络、同一配置的 before/after 算法时间。

## 9. Aggregate performance counters

| Counter | Before | After | Change |
|---|---:|---:|---:|
| algorithm seconds | 786.502 | 309.954 | -60.59% |
| refinement seconds | 765.835 | 300.269 | -60.79% |
| epsilon seconds | 621.837 | 245.474 | -60.52% |
| evaluations | 1,619,098 | 1,471,181 | -9.14% |
| solver calls | 1,619,098 | 1,471,181 | -9.14% |
| solver seconds | 132.389 | 41.771 | -68.45% |
| cache hits | 1,608,159 | 1,460,244 | expected lower with fewer calls |
| cache misses | 10,939 | 10,937 | effectively unchanged |
| cache hit rate | 99.324% | 99.257% | expected counter change |
| unique D histograms | 4,489 | 4,489 | identical |

## 10. Tests与验证

新增或扩展的自动验证覆盖：

- exact proxy-only 与完整 partition solver 的 deterministic/randomized 对照；
- Offset=0 对应的 `D=T`、重复 D、多 D、单/多组及 Fraction/string/float rho；
- 非法 histogram 拒绝；
- candidate path 不物化 groups、正式 solution 完整物化；
- 新旧 canonical assignment signature 完全相等；
- test-local before-style single search 与 optimized search 的 state/objective/CPU/accepted moves
  一致，且 optimized evaluation 次数更少；
- GUI μs→ms 精确格式、列标题/顺序、DTO `d_us` 不变。

最终命令与结果在提交前重新执行并记录：

```text
python -m pytest -q                                        511 passed in 71.64s
python -m ruff check .                                     All checks passed
python -m mypy                                             90 source files, no issues
python -m canfd_offset_optimizer.gui --portable-smoke-test exit 0
```

另以 `QT_QPA_PLATFORM=offscreen` 实例化正式 Joint result page、填入 recommendation 与
MainFunction group 并抓取 1400×900 截图。表格实际 headers 为
`组 / TimeBase (μs) / TimeBase (ms) / 报文 / Cycle (ms) / Offset (ms) / D (μs) /
D (ms)`，横向滚动最大值为 0；有限 smoke 未发现列拥挤或数值乱码。普通模式回归包含在
511 个全量测试中。

## 11. 剩余瓶颈

当前最大的剩余热点是普通 CAN local pair search 的大量 SearchState apply/remove/rollback、
`_change_contribution` 的 Counter 更新，以及每个候选的 CAN objective 计算。它们同时服务
普通 Peak/Balanced/Variance 路径；在没有更强等价证明与显著收益前，本轮不冒险改动公共
SearchState 语义。输出 I/O 不是主要瓶颈。

## 12. 提交与最终状态

- GUI commit：`5e08e46 fix(gui): 改善联合调度时间单位显示`
- Joint performance commit：本报告所在提交（完整 SHA 以 `git log` 为准）
- 分支：`feature/joint-gui`
- push：本轮不 push
- worktree：将在最终回归和提交后确认 clean
