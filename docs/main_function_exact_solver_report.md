# 固定 Offset 下 MainFunction 精确子求解器实验报告

## 1. 实验目的与边界

本轮实现并验证一个独立的 MainFunction 子求解器：

```text
固定周期 T 与最终 Offset O
    ↓
D_i = gcd(T_i, O_i)
    ↓
精确求解 MainFunction 分组
    ↓
为每组取最大可行 TimeBase
    ↓
最小化 CPU Cost Proxy
```

本模块只解决固定 Offset assignment 下的 MainFunction partition 子问题，不读取
ARXML MainFunction 配置，不修改 Offset、DBC、GUI 或现有 GCLS 搜索流程，也不实现
ε-constraint、Pareto front、knee point 或 CAN/CPU 联合搜索。

实验日期：2026-07-28。

基线分支：`main`。

基线提交：`0e3e6d6`。

## 2. 数学模型

### 2.1 单报文调度节拍

对周期报文 `i`：

\[
D_i=\gcd(T_i,O_i)
\]

其中 `T_i > 0`、`O_i >= 0`，时间统一使用整数微秒。当 `O_i = 0` 时：

\[
\gcd(T_i,0)=T_i
\]

### 2.2 分组 TimeBase

对 MainFunction 分组 `G`：

\[
B_G=\gcd_{i\in G}D_i
\]

`B_G` 是能够同时整除组内全部周期和 Offset 的最大正整数 TimeBase。CPU Cost
Proxy 随 TimeBase 增大而单调下降，因此固定分组后不需要再搜索 TimeBase。

### 2.3 CPU Cost Proxy

本轮使用：

\[
P_{CPU}=\sum_G\frac{\rho+N_G}{B_G}
\]

其中：

- `N_G`：组内报文数；
- `rho > 0`：一次 MainFunction 固定调用成本与单报文增量成本的比值；
- 默认 `rho = 1`。

内部 `B_G` 使用微秒，因此公开结果返回每秒尺度的精确值：

\[
P_{CPU/s}
=
\sum_G\frac{(\rho+N_G)\times 1{,}000{,}000}{B_{G,\mu s}}
\]

该指标是 CPU 调度成本代理值，不是实际 CPU utilization。

## 3. 算法实现

实现文件：

```text
src/canfd_offset_optimizer/optimization/main_function.py
```

主要结构如下：

- `MainFunctionMessage`：不可变输入，只包含 `message_key`、`period_us` 和
  `offset_us`；
- `MainFunctionGroup`：不可变分组结果，包含具体报文、`timebase_us`、组成本和
  D 类型；
- `MainFunctionSolveResult`：不可变总结果，包含精确 CPU Proxy、`rho` 和分组；
- `calculate_message_d_us()`：计算 `D_i = gcd(T_i, O_i)`；
- `calculate_group_timebase_us()`：计算 `B_G = gcd(D_i)`；
- `_solve_histogram_exact()`：D 类型压缩后的 exact subset-DP；
- `_solve_histogram_cached()`：256 项有界 LRU cache；
- `solve_main_function_partition()`：公开纯领域 API。

### 3.1 相同 D 类型压缩

目标函数只依赖 D 值及其报文数量，不依赖 message identity。因此先把输入压缩为：

```text
((d_1, count_1), ..., (d_m, count_m))
```

相同 D 的多条报文加入同一个相关组不会进一步降低组 gcd；集中同类型报文不会增加
变量成本，并可能减少一次固定 `rho` 成本。因此至少存在一个不拆分相同 D 类型的最优
解。实现和 message-level brute-force oracle 同时验证了该性质。

### 3.2 Exact subset-DP

对任意非空 D 类型子集 `A`：

\[
Cost(A)=\frac{\rho+N(A)}{B(A)}
\]

DP 状态为：

\[
F(S)
=
\min_{A\subseteq S,\ anchor(S)\in A}
\left[Cost(A)+F(S\setminus A)\right]
\]

每个状态固定最低 set bit 为 anchor，只枚举包含 anchor 的首组，从而使每个无序
partition 恰好被覆盖一次。

复杂度：

```text
时间：O(3^m)
空间：O(2^m)
```

其中 `m` 是 distinct D type count，而不是报文总数。

### 3.3 精确数值与 tie-break

所有方案成本使用 `fractions.Fraction` 比较。float 只用于最终展示，不参与最优性
判断。

完全同成本时按以下顺序稳定选择：

1. MainFunction 数量更少；
2. D 类型 partition canonical signature 字典序更小。

cache key 只包含精确 `rho` 和排序后的 D histogram，不包含 message identity 或输入
顺序。

## 4. 自动化测试

测试文件：

```text
tests/unit/test_main_function.py
```

覆盖内容包括：

- 单报文 gcd：
  - `100 ms / 15 ms -> 5 ms`
  - `100 ms / 20 ms -> 20 ms`
  - `200 ms / 0 ms -> 200 ms`
  - `500 ms / 0 ms -> 500 ms`
- group gcd：
  - `20, 100 -> 20 ms`
  - `20, 50, 100 -> 10 ms`
- `rho` 对额外 MainFunction 的固定成本惩罚；
- 完全同成本时优先更少分组；
- 所有输出 TimeBase 同时整除组内周期与 Offset；
- 报文不丢失、不重复，组间互斥；
- CPU Proxy 等于全部 group cost 之和；
- 输入顺序、reverse 和固定 shuffle 不改变 canonical 结果；
- 相同输入连续运行 100 次结果一致；
- 非法周期、Offset、rho、空输入、重复 key 和错误类型；
- 精确十进制 rho 和接近成本场景；
- 256 项缓存上界、identity-independent 命中及具体报文映射；
- frozen dataclass 不可变性。

### 4.1 Message-level brute-force oracle

测试中独立实现了未压缩的 Bell partition 枚举器，直接按具体报文计算：

\[
\sum_G\frac{\rho+N_G}{\gcd(D_i,\ i\in G)}
\]

对照规模：

- `n = 1..7`；
- 固定随机种子 `20260728`；
- 47 个构造及固定随机样本；
- `rho = 1/2, 1, 3`；
- 共 141 次 exact cost 对照；
- 明确包含多条报文具有相同 D 的样本。

结果：compressed subset-DP 与 message-level brute-force oracle 的精确成本全部一致。

## 5. 测试与静态检查结果

由于本机原有 editable install 指向相邻的 `canfd-offset-optimizer-gui` 工作区，全部
权威测试命令均显式设置当前仓库的 `PYTHONPATH`：

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
```

现有测试 baseline：

```powershell
python -m pytest -q --ignore=tests/unit/test_main_function.py
```

```text
128 passed in 26.54s
```

新模块测试：

```powershell
python -m pytest -q tests/unit/test_main_function.py
```

```text
24 passed in 0.41s
```

全量回归：

```powershell
python -m pytest -q
```

```text
152 passed in 28.81s
```

静态检查：

```powershell
python -m ruff check src tests
python -m mypy src
```

```text
All checks passed!
Success: no issues found in 42 source files
```

覆盖率：

```powershell
python -m pytest -q --cov=canfd_offset_optimizer --cov-report=term-missing
```

```text
152 passed
全仓覆盖率：89%
main_function.py：92%
```

## 6. 真实网段数据实验

使用仓库现有九网段 Balanced assignment 结果和对应 DBC 周期，构造固定 Offset
MainFunction 输入。统计及运行结果如下：

| 网段 | 报文数 n | distinct D 数 m | 最优组数 | 冷启动 ms | 缓存命中 ms |
|---|---:|---:|---:|---:|---:|
| CH | 9 | 4 | 4 | 0.257 | 0.044 |
| DA | 17 | 5 | 5 | 0.368 | 0.056 |
| DK | 25 | 6 | 5 | 0.791 | 0.061 |
| EP | 6 | 4 | 3 | 0.231 | 0.041 |
| GL | 25 | 6 | 5 | 0.895 | 0.113 |
| IC | 24 | 6 | 5 | 0.853 | 0.063 |
| LC | 8 | 4 | 3 | 0.183 | 0.040 |
| PT | 11 | 5 | 4 | 0.337 | 0.045 |
| SU | 7 | 4 | 4 | 0.187 | 0.043 |

九网段实际 `m` 范围为 `4..6`，中位数为 `5`。当前真实规模下，冷启动均低于
`1 ms`，相同 histogram 的缓存调用约为 `0.04..0.11 ms`。

## 7. 合成性能实验

对不同 distinct D type count 运行三次冷启动，报告中位数：

| m | 冷启动中位数 ms | 最小 ms | 最大 ms | 缓存命中 ms |
|---:|---:|---:|---:|---:|
| 5 | 0.333 | 0.294 | 0.398 | 0.038 |
| 8 | 5.481 | 5.369 | 5.956 | 0.059 |
| 10 | 49.256 | 48.844 | 49.529 | 0.086 |
| 12 | 450.994 | 445.973 | 457.772 | 0.091 |
| 13 | 1378.542 | 1375.437 | 1380.302 | 0.099 |

`m=12` 后开始明显变慢，符合 `O(3^m)` 复杂度。当前真实网段最大 `m=6`，因此本轮
没有添加缺乏实测依据的 `max_exact_types` 硬限制。调用方仍需认识到极端高 `m`
输入的指数复杂度风险；后续若增加保护，应明确 fail closed，不能静默退化为启发式。

## 8. 对现有系统的影响

生产路径引用审计确认新 solver 只存在于独立模块和测试中，没有被以下流程导入：

```text
DBC
→ eligibility
→ request
→ GCLS
→ result
→ GUI/reporting
→ write-back
```

因此本轮对以下功能的行为影响均为“无”：

- Peak；
- Balanced；
- Variance；
- Qss；
- GCLS；
- GUI；
- 热力图；
- DBC write-back；
- CLI。

## 9. 后续接口与风险

后续第 2 阶段可在获得最终 Offset assignment 后调用：

```python
messages = tuple(
    MainFunctionMessage(
        message_key=message.name,
        period_us=message.cycle_time_us,
        offset_us=final_offsets[message.name],
    )
    for message in periodic_messages
)

main_function_result = solve_main_function_partition(messages, rho=1)
```

概念链路：

```text
Offset assignment
    ├─ existing CAN evaluator → Peak / Qss
    └─ MainFunction exact solver → CPU Cost Proxy / groups / TimeBase
```

本轮尚未实现上述集成。剩余风险与边界：

- `rho` 仍是工程参数，尚未由目标 ECU profiling 标定；
- CPU Cost Proxy 不是实际 CPU utilization；
- gcd 时间栅格是项目工程模型，不是 AUTOSAR 强制规则；
- exact DP 在高 `m` 下存在 `O(3^m)` 风险；
- 缓存是进程内 256 项 LRU，不跨进程持久化；
- 尚未接入 GCLS；
- 尚未实现或验证 ε-constraint、Pareto、knee 及真实 CAN/CPU 联合行为。
