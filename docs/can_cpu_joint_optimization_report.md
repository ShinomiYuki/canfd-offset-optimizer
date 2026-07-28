# CAN/CPU 联合优化实验与实现报告

> 日期：2026-07-28  
> 分支：`main`  
> 口径：`rho=1`、`epsilon_points=21`；真实网段为控制运行时间使用固定 1 次 attempt。  
> 重要边界：固定 Offset 下的 MainFunction partition 是 exact；外层 Offset、anchor 与 ε 搜索是启发式 GCLS。

# 1. Baseline 与架构审计

- 开始时分支为 `main`，工作树干净。
- 显式使用当前仓库源码执行：

  ```powershell
  $env:PYTHONPATH=(Resolve-Path 'src').Path
  python -m pytest -q --basetemp $env:TEMP\canfd-joint-baseline
  ```

- Baseline：`152 passed in 27.20s`。
- 旧优化链路由 `cli.py → project_loader → SlotMap/SearchState → run_gcls` 组成；Peak、Balanced、Variance 共享正式 `score_state`、增量时隙状态和 restart 审计。
- 新功能没有复用旧 `balanced` 名称，而是新增独立 `joint` CLI、service 与 `optimize_can_cpu_balanced()` API。
- 对旧 GCLS 的改动仅增加默认关闭的 `fixed_messages/fixed_offsets` 可选参数；默认空集合，因此旧调用的目标、候选、restart 与结果语义保持不变。

# 2. 修改文件列表

| 路径 | 目的 |
|---|---|
| `src/canfd_offset_optimizer/optimization/joint.py` | Joint domain、评价器、anchors、exact ε budget、搜索、去重、Pareto 与 DTO |
| `src/canfd_offset_optimizer/timeline/state.py` | 支持不可变 fixed CAN load baseline；默认仍为空 |
| `src/canfd_offset_optimizer/optimization/greedy.py` | 在 fixed baseline 上构造 decision assignment |
| `src/canfd_offset_optimizer/optimization/gcls.py` | 将 fixed baseline 贯穿 Peak/Balanced；公开复用正式 Peak budget 函数 |
| `src/canfd_offset_optimizer/optimization/main_function.py` | 公开 `normalize_rho()`，不改变 exact solver 数学行为 |
| `src/canfd_offset_optimizer/joint_service.py` | 非 GUI service 入口 |
| `src/canfd_offset_optimizer/reporting/joint_writer.py` | 完整、精确、稳定 JSON 审计输出 |
| `src/canfd_offset_optimizer/cli.py` | 新增只读分析型 `joint` 命令 |
| `tests/unit/test_joint.py` | 业务规则、评价、anchors、ε、Pareto、穷举、确定性、JSON 测试 |
| `tests/integration/test_end_to_end.py` | Joint CLI 集成测试 |
| `docs/can_cpu_joint_optimization_report.md` | 本报告与 DK/GL/IC 实验记录 |

# 3. Joint domain

`build_joint_domain()` 先按稳定 identity 排序，再严格执行：

- `T_i <= offset_max_us`：decision message，继续使用原 candidate grid；
- `T_i > offset_max_us`：fixed message，联合模式副本的 `allowed_offsets_us=(0,)`；
- `T_i == offset_max_us` 仍属于 decision；
- 原 `CanMessage` 不被修改。

搜索向量只保存 decision offsets；`JointEvaluator.full_assignments()` 合并 fixed `Offset=0`，所有 solution、SHA-256、audit 与 MainFunction 分组均保存 full assignment。

`SearchState` 构造时先应用 fixed message 的稳态/启动期贡献。后续 greedy、1-opt、pair、triple 和 restart 只迭代 `state.messages`（decision subset），因此 fixed message 不可能被 move 修改，却始终保留在 CAN load baseline 中。

# 4. Joint evaluator

`JointEvaluator.evaluate_state()` 对同一个完整状态执行两条正式路径：

1. CAN：直接调用现有 `score_state()`，得到正式 Peak、Qss、启动期指标与阈值违反指标；
2. CPU：为所有 decision + fixed message 构造稳定 key  
   `definition_index:can_id:name`，调用 `solve_main_function_partition()`。

输出 `JointMetrics` 同时保存：

- 完整 `ObjectiveValue`；
- `Peak=steady_peak`；
- `Qss=sum_square_load`；
- exact `Fraction` CPU Proxy；
- exact MainFunction groups、每组 TimeBase 和 group cost。

测试用相同 full assignment 分别调用正式 CAN evaluator 与 exact solver，结果与 Joint evaluator 完全相等。fixed message 的存在会同时改变 CAN 指标和 D histogram/CPU 结果。

# 5. Peak guardrail

联合模式先在自己的 decision/fixed domain 上运行原 Peak GCLS，得到 `Z_joint*`。随后调用公开包装 `calculate_peak_budget_us()`，完全复用当前 Balanced tolerance 规则生成 `Z_budget`，未手写另一套 5% 公式。

CAN anchor、CPU anchor 和每个 ε run 同时满足：

- `Peak <= Z_budget`；
- 阈值违反 pair 不劣于 joint Peak reference；
- ε stage 额外满足 exact `CPU Proxy <= ε`。

Peak 仅为 hard guardrail，不进入 Pareto dominance 维度。

# 6. CAN anchor

- 目标：在 joint Peak guardrail 内按现有 Balanced 语义降低 Qss；
- 算法：直接复用原 `run_gcls(..., mode=BALANCED)`；
- fixed load：作为 `SearchState` 不可变基线贯穿完整搜索；
- seed：使用调用方 base seed；
- comparator：仍为当前正式 Balanced comparator，没有加入 CPU weighted score；
- 输出：full assignment、正式 CAN objective、exact CPU Proxy、MainFunction groups、restart audit。

# 7. CPU anchor

- 第一目标：exact CPU Proxy；
- tie-break：Qss、Peak、canonical full assignment；
- hard constraints：统一 Peak budget 与 Peak reference violation guardrail；
- CAN anchor 始终作为已知可行 incumbent，因此实现后置检查  
  `P_CPU_anchor <= P_CAN_anchor`；
- restart seed 从 `base_seed + 10_000` 开始，未使用 Python `hash()`；
- 外层仍是启发式搜索，不声称 CPU anchor 全局最优。

# 8. ε-constraint

若 `P_min < P_max`，使用 exact `Fraction`：

```text
ε_k = P_min + k/(K-1) * (P_max-P_min), k=0..K-1
```

- 默认 `K=21`，配置要求 `K>=2`；
- 预算从 CPU anchor 端单调递增到 CAN anchor 端；
- 每轮以 Qss 为第一目标，CPU 仅为 hard constraint；
- 前一 ε solution、CPU anchor、CAN anchor 中当前可行者全部作为 incumbents；
- 第一个预算保留 CPU anchor 可行性，最后一个预算保留 CAN anchor 可行性；
- `P_min==P_max` 时不做重复扫描，返回 `no_observed_cpu_tradeoff`；
- 全部 message fixed 时直接返回唯一 full assignment。

# 9. Pareto

候选先按 full assignment SHA-256 去重，再按 exact `(Qss, CPU Proxy)` 去重。同 objective 点依次选择：

1. Peak 更低；
2. MainFunction 数更少；
3. canonical assignment 更小。

支配定义只使用 Qss 与 CPU Proxy；至少一维严格更优才构成支配。最终按：

```text
(Qss, CPU Proxy, Peak, canonical assignment)
```

稳定排序。这里输出的是 **discovered candidates 中的 non-dominated set**，不是全局 Pareto frontier。

# 10. DTO / Service / CLI

`JointOptimizationResult` 保存 Peak reference、统一 budget、CAN/CPU anchors、每个 ε run、Pareto 全集、状态和性能统计。每个 `JointSolution` 保存：

- full assignments 与稳定 SHA-256；
- 正式 CAN objective、Peak、Qss；
- exact CPU Proxy；
- exact MainFunction result；
- source、ε budget；
- stage/restart seed、约束、attempt、耗时与 assignment audit。

JSON 中所有 `Fraction` 均输出：

```json
{
  "numerator": 1,
  "denominator": 3,
  "exact": "1/3",
  "display_value": 0.3333333333333333
}
```

非 GUI service：`run_joint_optimization()`。CLI 示例：

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
python -m canfd_offset_optimizer.cli joint `
  --dbc <network.dbc> `
  --arxml input/arxml `
  --config input/config/project.yaml `
  --output <output-dir> `
  --channel <ARXML-channel> `
  --seed 0 `
  --rho 1 `
  --epsilon-points 21
```

结果位于 `results/<prefix>_joint_summary.json`。没有改动 GUI 或 writeback。

# 11. 自动测试

新增自动测试覆盖：

- `T==max` decision、`T>max` fixed；
- fixed `Offset=0` 绕过正的 `min_offset`；
- fixed message 同时参与 CAN 和 CPU；
- fixed message 与 decision move 隔离；
- Joint evaluator 与正式 CAN/exact solver 等价；
- exact ε endpoints、单调性与 hard constraint；
- CAN/CPU anchor guardrail、incumbent 保证；
- Pareto dominance、重复 objective、Peak 非 dominance 维、稳定顺序；
- 最多 3 个候选的微型穷举 oracle，返回 observed Pareto 与 exact frontier objective pair 一致；
- 同 seed/config 两次运行的 assignment hash 与 Pareto 顺序一致；
- 全 fixed 退化域；
- exact Fraction JSON 与 CLI 集成；
- 全量旧 Peak/Balanced/Variance/GUI/writeback 回归。

执行命令：

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
python -m pytest -q --basetemp $env:TEMP\canfd-joint-final
python -m ruff check .
python -m mypy
```

最终结果见提交前验证记录：`164 passed`，Ruff 与 mypy 均通过。

# 12. DK / GL / IC 实际结果

真实运行统一使用 `frame_time_us`、seed 0、`rho=1`、21 个 ε points、固定 1 次 attempt。

| 网段 | eligible n | decision | fixed | Z* | Z_budget | CAN anchor (Peak/Qss/P/MF) | CPU anchor (Peak/Qss/P/MF) | ε 唯一解 | Pareto | 优化耗时 |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|---:|
| DK | 25 | 16 | 9 | 2699 | 2834 | 2699 / 23,801,955 / 2188 / 6 | 2824 / 76,258,945 / 778 / 5 | 16 | 16 | 19.437 s |
| GL | 25 | 23 | 2 | 614 | 645 | 614 / 21,569,436 / 3163 / 5 | 622 / 31,081,436 / 1773 / 5 | 16 | 16 | 21.803 s |
| IC | 24 | 20 | 4 | 986 | 1036 | 986 / 43,946,685 / 2549 / 7 | 1029 / 76,780,565 / 1519 / 7 | 14 | 14 | 30.803 s |

“优化耗时”来自 joint service 内部计时，不包含 DBC/ARXML 加载。完整 assignment、groups、attempts 和完整 SHA-256 保存在对应 JSON artifact；以下列出所有 Pareto objectives（hash 显示前 12 位）。

### DK Pareto

| source | Qss | CPU Proxy | Peak | MF 数 | hash |
|---|---:|---:|---:|---:|---|
| epsilon_20 | 23801955 | 2188 | 2699 | 6 | `67e4dd738312` |
| epsilon_17 | 23833955 | 1928 | 2699 | 6 | `0c28a07754f3` |
| epsilon_16 | 24114455 | 1848 | 2699 | 6 | `d98b95eee5fa` |
| epsilon_14 | 24739455 | 1748 | 2699 | 7 | `a3fbdde3b28c` |
| epsilon_13 | 25926205 | 1668 | 2824 | 7 | `cbdb54bae5a2` |
| epsilon_12 | 27276205 | 1618 | 2824 | 7 | `8937969f91c5` |
| epsilon_11 | 28926205 | 1538 | 2824 | 7 | `a2fa0cf4059a` |
| epsilon_10 | 29338705 | 1478 | 2824 | 7 | `083d71b02b27` |
| epsilon_07 | 33386205 | 1208 | 2824 | 5 | `8ee2fa0ed66c` |
| epsilon_06 | 33486205 | 1148 | 2824 | 5 | `d1adec5be54c` |
| epsilon_05 | 33698705 | 1128 | 2824 | 6 | `8ad784d7914b` |
| epsilon_04 | 34323705 | 1048 | 2824 | 6 | `fb40d456cc8a` |
| epsilon_03 | 36731205 | 988 | 2824 | 6 | `02deb5b8a6bb` |
| epsilon_02 | 45545185 | 918 | 2824 | 5 | `64498701a3c2` |
| epsilon_01 | 50070085 | 838 | 2824 | 5 | `8f40f75fb4eb` |
| cpu_anchor | 76258945 | 778 | 2824 | 5 | `d4513104b673` |

### GL Pareto

| source | Qss | CPU Proxy | Peak | MF 数 | hash |
|---|---:|---:|---:|---:|---|
| epsilon_20 | 21569436 | 3053 | 614 | 5 | `b6df1b52f889` |
| epsilon_18 | 21681936 | 3003 | 614 | 5 | `4a4aef86dca` |
| epsilon_16 | 21894436 | 2853 | 614 | 5 | `4159591002dd` |
| epsilon_13 | 22206436 | 2653 | 614 | 5 | `d0a9a671a97d` |
| epsilon_12 | 22326436 | 2603 | 614 | 5 | `bde89d0104d5` |
| epsilon_11 | 22618936 | 2503 | 614 | 5 | `10fcd3059ec9` |
| epsilon_10 | 23236436 | 2443 | 614 | 5 | `092fabc6eb0b` |
| epsilon_09 | 23428936 | 2393 | 614 | 5 | `7c0d96af9dc1` |
| epsilon_07 | 24550436 | 2233 | 614 | 5 | `5eb46b571cbe` |
| epsilon_06 | 25581536 | 2153 | 614 | 6 | `a6363af2d3d1` |
| epsilon_05 | 26403036 | 2073 | 614 | 5 | `179c79d49708` |
| epsilon_04 | 27538936 | 2003 | 614 | 6 | `ed21e3fb8c95` |
| epsilon_03 | 28701436 | 1933 | 614 | 5 | `fdfd4f400ebd` |
| epsilon_02 | 30576436 | 1883 | 614 | 5 | `481be49efb0e` |
| epsilon_01 | 30768936 | 1833 | 614 | 5 | `fce3a44c66ec` |
| cpu_anchor | 31081436 | 1773 | 622 | 5 | `283881f0f6a3` |

### IC Pareto

| source | Qss | CPU Proxy | Peak | MF 数 | hash |
|---|---:|---:|---:|---:|---|
| epsilon_20 | 43546685 | 2449 | 986 | 7 | `b76650d6a584` |
| epsilon_17 | 47136685 | 2359 | 986 | 6 | `d305579b72fe` |
| epsilon_14 | 47761685 | 2219 | 986 | 6 | `07621fbcb48d` |
| epsilon_11 | 48786685 | 2059 | 986 | 6 | `0ba00754b1e8` |
| epsilon_09 | 49811685 | 1959 | 986 | 6 | `8101183b7bcd` |
| epsilon_08 | 50221685 | 1909 | 986 | 6 | `0318b032b735` |
| epsilon_07 | 51232045 | 1859 | 986 | 6 | `d73af111818b` |
| epsilon_06 | 51657045 | 1799 | 986 | 6 | `42ccd25436e3` |
| epsilon_05 | 52097045 | 1769 | 986 | 7 | `0f14ad996493` |
| epsilon_04 | 53101885 | 1719 | 986 | 7 | `1a896d619a56` |
| epsilon_03 | 56808285 | 1669 | 986 | 7 | `55c9fd711b97` |
| epsilon_02 | 58097085 | 1609 | 986 | 7 | `f6e51dd0c3bf` |
| epsilon_01 | 60265885 | 1569 | 986 | 7 | `7c7365ef9fee` |
| cpu_anchor | 76780565 | 1519 | 1029 | 7 | `2fe77d5f6d45` |

不对任何点做“最好”或推荐判断。

# 13. MainFunction solver 性能

| 网段 | joint evaluations | solver calls | hits | misses | hit rate | unique D histograms | solver time | total | solver/total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DK | 28,163 | 28,163 | 27,602 | 561 | 98.008% | 540 | 3.208 s | 19.437 s | 16.50% |
| GL | 41,049 | 41,049 | 40,465 | 584 | 98.577% | 565 | 3.295 s | 21.803 s | 15.11% |
| IC | 31,907 | 31,907 | 31,391 | 516 | 98.383% | 507 | 6.689 s | 30.803 s | 21.72% |

虽然每个 joint evaluation 都调用 exact solver，D-histogram LRU 仍取得 98% 以上 hit rate。三个网段没有出现需要立即调整 cache size 的证据；miss 数大于 cache 容量并不自动等于 thrashing，实际 hit rate 与 solver/total 占比仍可接受。

# 14. 精确性边界

- **Exact**：给定一个固定 full Offset assignment，MainFunction D-type compression、subset-DP partition、TimeBase 与 CPU Proxy 是全局精确最优，比较使用 `Fraction`。
- **Heuristic**：Peak reference、CAN anchor、CPU anchor、各 ε Offset 搜索均由配置的 GCLS/局部搜索发现。
- **Observed Pareto**：仅是 anchors 与 ε runs 所发现候选中的非支配集合。
- 微型穷举测试证明 evaluator、约束、ε 和 Pareto 数学实现正确；不能外推为真实网段的全局 Pareto 最优性。
- CPU Proxy 是工程代理指标，不是实际 CPU utilization 或百分比。

# 15. 对旧功能影响

| 功能 | 影响 |
|---|---|
| Peak | 默认 fixed 参数为空，行为不变 |
| Balanced | 仍是纯 CAN Balanced，未加入 CPU |
| Variance | 行为不变 |
| GCLS restart | 默认路径 seed、attempt、停止条件不变 |
| GUI | 未修改 |
| DBC writeback | 未修改，joint CLI 只读分析 |
| old CLI | 原命令和输出保持不变 |
| old service/API | 未替换单结果接口，仅新增独立 service |

全量回归用于证明没有新增失败。

# 16. 尚未做的事情

- 未实现 knee point；
- 未实现 GUI、Pareto 图或 MainFunction 表；
- 未自动选择任何推荐方案；
- 未标定 `rho`，真实网段仅使用默认 `rho=1`；
- 未接入 WCET，CPU Proxy 不是实际 CPU utilization；
- 未引入 ARXML MainFunction 配置或 writeback 新语义；
- 未证明 GCLS anchors 或 observed Pareto 的全局最优性；
- 未做 `rho` 敏感性扫描；
- 未扩展到全部真实网段。

# 17. 第三阶段建议

仅根据本次数据：

1. DK、GL、IC 都观察到明确的 Qss/CPU tradeoff，Pareto 点分别为 16、16、14，因此后续研究 knee 有数据基础，但本轮不选 knee。
2. 21 个 ε budgets 最终保留 14–16 个不同 objective points，当前分辨率不是明显过密；是否足够仍应结合相邻点变化和更高分辨率对照，而非直接下结论。
3. `rho=1` 决定固定调用成本与报文增量成本的比例，必须做敏感性实验或由测量标定后才能形成工程推荐。
4. LRU hit rate 均超过 98%，目前不建议仅因 misses 超过 256 就调整容量；应先记录逐阶段 reuse distance 或做 cache-size A/B。
5. 后续 knee 若实现，应对 exact `(Qss, CPU Proxy)` 做规范化并保留“无明显 knee”的合法结果；仍不得替代人工工程决策。
