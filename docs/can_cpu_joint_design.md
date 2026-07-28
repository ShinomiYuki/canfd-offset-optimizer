# 周期报文 Offset 与 Com_MainFunctionTx 的 CAN/CPU 平衡联合优化

> 本文只描述新增的 **Offset - MainFunction - TimeBase 联合优化**。不要混入保守占用时间、DBC 回写、GUI 热力图等既有功能。
>
> 目标：在保持 CAN 总线释放均衡性的同时，降低 `Com_MainFunctionTx` 的结构性调度开销，并直接输出建议的 MainFunction 分组和 `ComMainTxTimeBase`。

---

## 1. 问题边界

AUTOSAR Classic Platform R25-11 中，`ComMainTxTimeBase` 表示对应 `Com_MainFunctionTx` 实例连续两次调用之间的周期；COM generator 可以基于该 TimeBase 将通信 timing 参数转换为内部 counter/tick，但内部 timing handling 是 implementation-specific。

因此，本设计使用“整数 tick 精确可表示”作为工具生成配置建议的工程模型，而不是声称这是 AUTOSAR 唯一实现方式。

参考：AUTOSAR CP R25-11, `AUTOSAR_CP_SWS_COM.pdf`, `ComMainFunctionTx / ComMainTxTimeBase`。

设周期 Tx 报文集合为：

\[
\mathcal M=\{1,2,\ldots,n\}
\]

每条报文 `i` 有：

- `T_i`：周期；
- `O_i`：最终 Offset；
- `w_i`：现有 CAN evaluator 使用的权重；
- `O_max = max_offset_ms`：当前 Offset 搜索上限。

工程规则固定为：

\[
T_i>O_{\max}\Rightarrow O_i=0
\]

这些慢周期报文：

- **不再优化 Offset**；
- **不能从问题中删除**；
- `Offset=0` 后仍参与 CAN Peak / `Qss`；
- 同样参与 MainFunction 分组与 CPU Proxy。

对于：

\[
T_i\le O_{\max}
\]

继续使用现有 Offset 候选集合。

---

## 2. MainFunction 时间栅格模型

### 2.1 时间统一为整数

所有时间在进入联合优化前统一转换为整数微秒（或统一整数 tick）：

```text
period_us
offset_us
timebase_us
```

禁止：

- 对浮点 `ms` 直接做 `%`；
- 对浮点做 gcd；
- 用 `math.isclose()` 代替精确可表示性判断。

### 2.2 单报文可表示性

若报文 `i` 属于 MainFunction `g`，TimeBase 为 `B_g`，第一版采用**零相位整数 tick 模型**：

\[
B_g\mid T_i
\]

且

\[
B_g\mid O_i
\]

`O_i=0` 时第二个条件天然成立。

定义：

\[
D_i=\gcd(T_i,O_i)
\]

并约定：

\[
\gcd(T_i,0)=T_i
\]

于是该报文允许的 MainFunction TimeBase 必须满足：

\[
B_g\mid D_i
\]

`D_i` 可以理解为：**这条报文在当前 `(T_i,O_i)` 下能够支持的最大 MainFunction 调度节拍。**

示例：

```text
T=100ms, O=15ms -> D=5ms
T=100ms, O=20ms -> D=20ms
T=200ms, O=0    -> D=200ms
```

这说明 Offset 不是纯 CAN 变量，它会改变 CPU 侧可用的 MainFunction TimeBase。

### 2.3 固定一个分组后，TimeBase 不需要搜索

对一个 MainFunction 组 `G`：

\[
B_G^*=\gcd_{i\in G}D_i
      =\gcd_{i\in G}(T_i,O_i)
\]

这是该组最大的可行 TimeBase。

任何更小的 TimeBase 都会增加 MainFunction 调用频率，却不会增加时序可表示能力，因此固定分组后必须直接使用 `B_G*`。

**实现结论：**

`TimeBase` 不是外层搜索变量。

```text
group membership -> gcd -> unique optimal TimeBase
```

---

## 3. CPU 指标推导

## 3.1 理想的真实 CPU 利用率

经典周期任务利用率形式：

\[
U=\sum_j\frac{C_j}{T_j}
\]

映射到 MainFunction：

\[
U_{COM-Tx}=\sum_g\frac{C_g}{B_g}
\]

其中：

- `C_g`：MainFunction `g` 一次真实执行时间；
- `B_g`：`ComMainTxTimeBase`。

问题：DBC + 当前工具无法可靠得到 `C_g`。

所以第一版不能把结果叫“真实 CPU 占用率”。

---

## 3.2 为什么不能只用 `Σ Ng/Bg`

最直接的结构 proxy：

\[
P_0=\sum_g\frac{N_g}{B_g}
\]

`N_g` 是组内周期 Tx I-PDU 数。

这个指标存在**分裂退化**。

如果组 `G` 的 TimeBase 为 `B`，拆成两个子组：

\[
B_1\ge B,\qquad B_2\ge B
\]

因此：

\[
\frac{N_1}{B_1}+\frac{N_2}{B_2}
\le
\frac{N_1+N_2}{B}
\]

所以只用 `Σ Ng/Bg` 时：

> 拆 MainFunction 永远不会让目标变差，算法天然倾向把 MainFunction 越拆越碎，甚至退化到一条报文一个 MainFunction。

原因：它只计算组内报文检查成本，没有计算“多调用一个 MainFunction 本身也要付固定开销”。

因此 **`Σ Ng/Bg` 不作为最终 CPU 指标。**

---

## 3.3 最终 CPU Proxy

用线性结构模型近似一次 MainFunction 的执行成本：

\[
C_g\approx C_0+C_1N_g
\]

其中：

- `C0`：一次 MainFunction 调用的固定开销；
- `C1`：每增加一条 I-PDU 的平均增量处理开销。

代入真实利用率：

\[
U_{COM-Tx}
\approx
\sum_g\frac{C_0+C_1N_g}{B_g}
\]

提取 `C1`：

\[
U_{COM-Tx}
\approx
C_1\sum_g\frac{\rho+N_g}{B_g}
\]

其中：

\[
\rho=\frac{C_0}{C_1}
\]

因为 `C1 > 0` 是所有方案共享的正比例因子，所以用于优化时定义：

\[
\boxed{
P_{CPU}
=
\sum_g\frac{\rho+N_g}{B_g}
}
\]

这才是第一版 CPU 侧最终指标。

### `rho` 的含义

`rho` 表示：

> 一次 MainFunction 的固定调用开销，大约等价于多少条 I-PDU 的平均增量检查开销。

### 第一版默认值

固定：

\[
\rho=1
\]

含义仅为单位归一化：

> 把一次固定调用开销暂时视为与一条 I-PDU 的平均增量成本同量级。

这不是物理测量值。

因此 UI / 报告必须叫：

```text
CPU Cost Proxy
CPU 调度成本代理指标
```

禁止叫：

```text
CPU Usage
CPU Utilization %
真实 CPU 占用率
```

### 后续标定

未来有目标 ECU profiling 数据时，拟合：

\[
C(N)=\beta_0+\beta_1N
\]

则：

\[
\rho=\frac{\beta_0}{\beta_1}
\]

无需改变算法结构。

---

# 4. 固定 Offset 后的 MainFunction 精确子问题

给定一个 Offset assignment：

\[
\mathbf O=(O_1,\ldots,O_n)
\]

每条报文得到：

\[
D_i=\gcd(T_i,O_i)
\]

此时 CPU 子问题是：

\[
\min_{\Pi}
\sum_{G\in\Pi}
\frac{\rho+|G|}{\gcd_{i\in G}D_i}
\]

这里 `Pi` 是对所有周期 Tx 报文的 MainFunction 分区。

要求：**这个子问题使用确定性精确求解器，不用随机启发式。**

这样可以保证：

> 对同一个 Offset assignment，MainFunction 分组一定是当前 CPU Proxy 模型下的全局最优分组。

---

## 4.1 关键压缩：相同 D 的报文不需要拆分

假设多条报文拥有相同：

\[
D_i=d
\]

若同一 `d` 类型被拆到两个组，TimeBase 分别 `b1 <= b2`：

1. `b1`、`b2` 都整除 `d`；
2. 把一个 `d` 报文加入 `b2` 组不会降低该组 gcd；
3. 从 `b1` 组删除该报文后，该组 gcd 只可能保持或变大；
4. 单报文变量成本从 `1/b1` 变成 `1/b2`，不会增加；
5. 如果 `b1` 组被搬空，还能删除一个固定 MainFunction 开销。

因此：

> 至少存在一个全局最优解，使所有相同 `D_i` 的报文整体分配到同一个 MainFunction，不需要拆分同类型。

把报文压缩成不同 `D` 类型：

```text
D=d1 -> n1 条
D=d2 -> n2 条
...
D=dm -> nm 条
```

通常：

```text
m << n
```

这一步非常重要，因为精确算法复杂度只依赖 `m`，不依赖报文总数 `n`。

---

## 4.2 一个类型子集作为一个 MainFunction 时的成本

对非空类型集合 `A`：

\[
B(A)=\gcd_{j\in A}d_j
\]

\[
N(A)=\sum_{j\in A}n_j
\]

该 MainFunction 的最优 CPU Proxy 成本：

\[
\boxed{
c(A)=\frac{\rho+N(A)}{B(A)}
}
\]

所以 MainFunction 分组问题变成标准集合划分：

\[
\min_{\Pi_D}\sum_{A\in\Pi_D}c(A)
\]

---

# 5. 确定性精确子求解器：bitmask subset DP

设 `S` 是尚未分组的 `D` 类型集合。

定义：

\[
F(S)=S\text{ 的最小 CPU Proxy}
\]

边界：

\[
F(\varnothing)=0
\]

为了不重复枚举无序 partition，固定 `p(S)` 为 `S` 中最小的 type index，只枚举包含这个 pivot 的子集 `A`：

\[
\boxed{
F(S)=
\min_{A\subseteq S,\ p(S)\in A}
\left[c(A)+F(S\setminus A)\right]
}
\]

记录最优 `A`，最后回溯出所有 MainFunction。

## 复杂度

\[
Time=O(3^m)
\]

\[
Memory=O(2^m)
\]

但这里的 `m` 是**不同 gcd 类型数量**。

当前项目周期与 Offset 都是离散值，`D_i` 只能来自这些离散值的公约数集合，所以实际 `m` 预计很小。不要因为总报文数可能上百，就误判这个 DP 会按报文数指数爆炸。

---

## 5.1 预计算

对所有非空 bitmask 预计算：

```text
subset_gcd[mask]   = B(A)
subset_count[mask] = N(A)
subset_cost[mask]  = (rho + N(A)) / B(A)
```

可用 lowbit 递推，不要每次重新遍历整个子集。

---

## 5.2 CPU 子问题缓存

CPU 精确结果只依赖：

```text
sorted((D_value, count), ...)
```

不依赖具体 message id。

定义稳定 signature：

```text
cpu_signature = tuple(sorted((d_us, count) ...))
```

缓存：

```text
cpu_signature -> ExactCpuPartitionResult
```

不同 Offset assignment 只要产生相同 `D` 直方图，直接复用：

- CPU Proxy；
- group type partition；
- group TimeBase。

这是外层 GCLS 高频评价时非常重要的性能优化。

---

## 5.3 精确数值

`P_CPU` 是有理数。

DP 内部禁止用普通 `float` 决定全局最优分区。

推荐：

- 时间：整数 `us`；
- CPU cost：`Fraction` 或等价整数缩放；
- 只有 GUI 展示和 Pareto 归一化时转 `float`。

---

# 6. CAN 侧目标：直接复用现有 Balanced

不要重新发明 CAN 指标。

## 6.1 稳态负载

超周期：

\[
H=\operatorname{lcm}(T_1,\ldots,T_n)
\]

时隙：

\[
I_k=[k\Delta,(k+1)\Delta)
\]

释放：

\[
r_{i,q}=O_i+qT_i
\]

时隙负载：

\[
L_k(\mathbf O)
=
\sum_i w_i\sum_q
\mathbf 1(r_{i,q}\in I_k)
\]

CAN 均衡目标保持现有：

\[
\boxed{
Q_{ss}(\mathbf O)=\sum_kL_k(\mathbf O)^2
}
\]

越小越均匀。

## 6.2 Peak 仍然是 guardrail

概念上可以写：

\[
Z_{ss}=\max_kL_k
\]

但代码必须**复用当前已经实现和验证的 Peak/Balanced guardrail**，包括当前已有的 lexicographic peak 目标、违规计数/违规量、relative tolerance 等语义。

不要在这个新功能里重写一套“简化 Peak”。

抽象表示为：

\[
\mathbf O\in\mathcal F_{peak}
\]

`Qss` 只在满足现有 Peak 预算的方案中比较。

## 6.3 长周期固定 Offset 的报文仍进入 CAN evaluator

规则：

```text
T_i > max_offset_ms
=> O_i = 0
```

这只表示 `O_i` 不再是 decision variable。

它们必须继续进入：

- steady load；
- Peak；
- `Qss`；
- MainFunction grouping；
- CPU Proxy。

禁止把它们从 optimizer request / evaluator 中完全 exclude。

---

# 7. 联合双目标模型

对一个 Offset assignment `O`，CPU 子求解器返回：

\[
\Phi(\mathbf O)
=
\min_{\Pi}P_{CPU}(\Pi\mid\mathbf O)
\]

于是整个问题变成：

\[
\boxed{
\min_{\mathbf O\in\mathcal F_{peak}}
\left(
Q_{ss}(\mathbf O),
\Phi(\mathbf O)
\right)
}
\]

并满足：

\[
T_i>O_{\max}\Rightarrow O_i=0
\]

### 重要结构结论

不要让 GCLS 同时搜索：

```text
Offset
x MainFunction membership
x TimeBase
```

正确结构：

```text
Offset assignment
    |
    +--> existing CAN evaluator -> Peak, Qss
    |
    +--> D_i = gcd(T_i, O_i)
           |
           +--> exact subset-DP
                  -> optimal groups
                  -> group TimeBase
                  -> Phi(O)
```

原因：

> 对同一个 Offset assignment，所有 MainFunction 分组的 CAN 指标完全相同。因此只需要保留 CPU 子问题的精确最优分组；其他分组必然被同一个 Offset 下的最优分组支配。

---

# 8. 多目标方法：epsilon-constraint

不使用：

\[
0.5Q_{ss}+0.5P_{CPU}
\]

也不使用任意 `alpha/beta` 加权和。

原因：

- 两个指标量纲不同；
- 数值尺度不同；
- 固定权重缺少工程解释；
- 非凸/离散 Pareto 前沿可能被简单 weighted-sum 漏掉。

采用 `epsilon-constraint`。

为了最大限度复用现有 Balanced / GCLS，选择：

> **继续最小化 Qss，把 CPU Proxy 变成预算约束。**

---

# 9. 两个锚点

## 9.1 CAN anchor

求：

\[
\mathbf O^Q
=
\arg\min_{\mathbf O\in\mathcal F_{peak}}Q_{ss}(\mathbf O)
\]

tie-break：更小的 `Phi(O)`。

记录：

\[
Q_{min}=Q_{ss}(\mathbf O^Q)
\]

\[
P_Q=\Phi(\mathbf O^Q)
\]

这基本就是现有 Balanced 方向，只增加 CPU exact evaluator 作为次级评价和记录。

## 9.2 CPU anchor

求：

\[
\mathbf O^P
=
\arg\min_{\mathbf O\in\mathcal F_{peak}}\Phi(\mathbf O)
\]

Tie-break：更小 `Qss`。

记录：

\[
P_{min}=\Phi(\mathbf O^P)
\]

\[
Q_P=Q_{ss}(\mathbf O^P)
\]

注意：

- CPU grouping 对固定 Offset 是 exact；
- 但 CPU anchor 的 **Offset 搜索本身仍是 GCLS heuristic**；
- 所以不要把 `P_min` 在文档里称作数学证明的全局 CPU 下界，只能叫当前搜索找到的 CPU anchor。

---

# 10. epsilon 扫描

固定：

```text
J = 20
=> 21 个 CPU budget point
```

定义：

\[
\varepsilon_j
=P_{min}
+\frac{j}{J}(P_Q-P_{min})
\]

其中：

```text
j = 0..20
```

对每个 budget 求：

\[
\min Q_{ss}(\mathbf O)
\]

subject to：

\[
\mathbf O\in\mathcal F_{peak}
\]

\[
\Phi(\mathbf O)\le\varepsilon_j
\]

以及长周期 Offset 固定规则。

同 `Qss` 时继续比较更小 `Phi`：

```text
objective = lexicographic(Qss, cpu_proxy)
```

## 扫描顺序

从严格 CPU 端开始：

```text
epsilon_0 = P_min
```

逐步放宽：

```text
epsilon_20 = P_Q
```

优点：

> 上一个预算的解在下一个更宽松预算中仍然可行，可以直接作为 warm start。

因此理论上随着 CPU budget 放宽，搜索到的最佳 `Qss` 应保持或下降；若明显反向恶化，应作为搜索质量诊断信号。

---

# 11. Pareto front

汇总：

- CAN anchor；
- CPU anchor；
- 21 个 epsilon scan 结果。

先按 `(Qss, CPU Proxy)` 去重。

定义支配：方案 `a` 支配 `b` 当且仅当：

\[
Q_a\le Q_b
\]

且：

\[
P_a\le P_b
\]

并且至少一项严格更小。

删除所有 dominated solution。

剩余集合是：

```text
search-derived non-dominated set
搜索得到的非支配解集
```

不要在报告里无条件写：

```text
exact Pareto front
全局 Pareto front
```

因为外层 GCLS 仍是 heuristic。

---

# 12. 默认推荐点：几何 knee

对最终非支配点：

\[
(Q_k,P_k)
\]

归一化：

\[
\hat Q_k
=
\frac{Q_k-Q_{min}}
{Q_{max}-Q_{min}}
\]

\[
\hat P_k
=
\frac{P_k-P_{min}}
{P_{max}-P_{min}}
\]

两个指标均满足：

```text
0 = 当前 Pareto 集中最好
1 = 当前 Pareto 集中最差
```

连接两个极端点的 chord：

\[
\hat Q+\hat P=1
\]

定义朝理想点 `(0,0)` 的 knee score：

\[
\boxed{
\kappa_k
=
\frac{1-\hat Q_k-\hat P_k}{\sqrt2}
}
\]

默认推荐：

\[
k^*=\arg\max_k\kappa_k
\]

直觉：

> 选择相对于“纯 CAN 最优”和“纯 CPU 最优”连线，最明显向左下理想方向鼓出的点。这个点通常是继续改善一个目标时，另一个目标开始付出明显更高边际代价的位置。

## 无明显 knee 时

若：

```text
max(kappa) <= 0
```

或者多个点在 numerical tolerance 内并列，则不要假装存在明显膝点。

退化为理想点距离：

\[
R_k=\sqrt{\hat Q_k^2+\hat P_k^2}
\]

选择：

\[
k^*=\arg\min_kR_k
\]

---

# 13. 最终 deterministic tie-break

推荐点发生数值并列时，按以下顺序：

1. 更小的 ideal-point distance；
2. 更少 MainFunction 数量；
3. 更小 `Qss`；
4. 更小 CPU Proxy；
5. stable offset assignment signature；
6. stable group signature。

CPU exact partition 本身若存在相同 Proxy 的多个 partition，也使用：

1. MainFunction 数更少；
2. `TimeBase` 降序序列更大；
3. `D-type` group signature 字典序稳定。

禁止依赖：

- Python set iteration order；
- dict 未显式排序的遍历结果；
- random tie-break。

---

# 14. rho 的默认与敏感性

默认：

```text
rho = 1.0
```

但它必须进入：

- run configuration；
- audit/result metadata；
- cache key。

研究/验证时至少扫描：

```text
rho = 0.5, 1, 2, 4
```

观察：

- 推荐 MainFunction 数量；
- 主要 TimeBase；
- knee Offset assignment；
- `Qss`；
- CPU Proxy ranking。

如果上述结构在这组 `rho` 下稳定，可称“对固定调用成本假设较鲁棒”。

如果变化很大：

```text
CPU model sensitivity = high
```

不要把 `rho=1` 的结果包装成物理最优；后续需要 ECU profiling 标定：

\[
C(N)=\beta_0+\beta_1N
\]

\[
\rho=\beta_0/\beta_1
\]

---

# 15. 推荐的 evaluator 结构

对任意候选 Offset assignment：

```text
1. existing peak / balanced evaluator
   -> Peak objective / guardrail
   -> Qss

2. build all final offsets
   - optimizable messages: candidate offset
   - T > max_offset_ms: forced 0

3. compute D_i = gcd(T_i, O_i)

4. aggregate histogram
   D_i -> count

5. lookup exact CPU cache
   if miss:
       run deterministic subset-DP

6. return
   - Qss
   - peak metrics
   - exact CPU Proxy for this Offset
   - exact optimal MainFunction partition
```

对 GCLS 而言，外层 decision variable **仍然只有 Offset**。

---

# 16. Exact CPU DP 伪代码

```python
from fractions import Fraction
from math import gcd


def solve_exact_cpu_partition(histogram, rho=Fraction(1, 1)):
    # histogram: sorted list[(d_us: int, count: int)]
    d = [item.d_us for item in histogram]
    n = [item.count for item in histogram]
    m = len(d)

    full = (1 << m) - 1

    subset_gcd = [0] * (1 << m)
    subset_count = [0] * (1 << m)
    subset_cost = [None] * (1 << m)

    for mask in range(1, 1 << m):
        bit = mask & -mask
        j = bit.bit_length() - 1
        prev = mask ^ bit

        if prev == 0:
            subset_gcd[mask] = d[j]
        else:
            subset_gcd[mask] = gcd(subset_gcd[prev], d[j])

        subset_count[mask] = subset_count[prev] + n[j]

        subset_cost[mask] = (
            rho + subset_count[mask]
        ) / subset_gcd[mask]

    # memoized exact set partition
    # dp[mask] = best exact Fraction cost
    # choice[mask] = chosen first group subset

    dp = {0: Fraction(0, 1)}
    choice = {}

    def solve(mask):
        if mask in dp:
            return dp[mask]

        pivot = mask & -mask
        rest = mask ^ pivot

        best = None
        best_group = None

        sub = rest
        while True:
            group = sub | pivot
            remain = mask ^ group

            candidate = subset_cost[group] + solve(remain)

            if better_cpu_partition_candidate(
                candidate,
                group,
                remain,
                best,
                best_group,
                choice,
                subset_gcd,
            ):
                best = candidate
                best_group = group

            if sub == 0:
                break
            sub = (sub - 1) & rest

        dp[mask] = best
        choice[mask] = best_group
        return best

    best_cost = solve(full)
    groups = reconstruct(choice, full)

    return best_cost, groups
```

`better_cpu_partition_candidate()` 必须执行前述 deterministic tie-break，不允许只比较 float。

---

# 17. epsilon scan 伪代码

```text
CAN_ANCHOR = GCLS(
    primary = Qss,
    secondary = CPU_PROXY,
    peak_guardrail = existing_guardrail,
)

CPU_ANCHOR = GCLS(
    primary = CPU_PROXY,
    secondary = Qss,
    peak_guardrail = existing_guardrail,
)

P_min = CPU_ANCHOR.cpu_proxy
P_Q   = CAN_ANCHOR.cpu_proxy

if P_min == P_Q:
    candidates = {best_of(CAN_ANCHOR, CPU_ANCHOR)}
else:
    J = 20
    previous = CPU_ANCHOR

    for j in 0..J:
        epsilon = P_min + (j / J) * (P_Q - P_min)

        result = GCLS(
            primary = Qss,
            secondary = CPU_PROXY,
            constraint = CPU_PROXY <= epsilon,
            peak_guardrail = existing_guardrail,
            warm_start = previous,
        )

        save(result)
        previous = result

candidates += CAN_ANCHOR
candidates += CPU_ANCHOR

pareto = deduplicate_and_remove_dominated(candidates)
recommended = choose_geometric_knee(pareto)
```

注意：`j/J` 的预算构造如果 CPU Proxy 使用 `Fraction`，预算也应尽量保持 exact rational，直到 GCLS evaluator 需要比较时仍用同一表示。

---

# 18. 结果对象必须包含

单个网段联合优化结果至少包含：

```text
recommended_assignment
recommended_qss
recommended_peak_metrics
recommended_cpu_proxy
rho

main_functions[]:
  - stable_group_id
  - timebase_us
  - message_ids[]
  - message_count
  - d_types[]

pareto_points[]:
  - qss
  - cpu_proxy
  - normalized_q
  - normalized_cpu
  - knee_score
  - assignment_hash
  - mainfunction_count

selection_reason:
  method = geometric_knee | ideal_point_fallback
```

每条报文最终还应能审计：

```text
message_id
period_ms
final_offset_ms
offset_source = optimized | forced_zero_long_period
D_i_us
recommended_mainfunction
recommended_timebase_us
```

---

# 19. 必须验证的不变量

### Timing

对每个最终 group `g`、每条成员 `i`：

```text
T_i % B_g == 0
O_i % B_g == 0
```

且：

```text
B_g == gcd(all T_i and O_i in group)
```

### Long-period rule

```text
T_i > max_offset_ms
=> final_offset == 0
```

但该消息必须仍出现在：

```text
CAN evaluator
CPU grouping
final audit
```

### Exact CPU partition

对小型 `m`，测试中可暴力枚举所有 set partitions，与 DP 最优值逐例一致。

### Same-D compression

压缩前暴力解与按 `D -> count` 压缩后的 DP 最优 CPU cost 必须一致。

### Determinism

同输入重复运行 exact CPU subsolver 100 次：

```text
cost identical
groups identical
timebases identical
```

### Pareto

最终 `pareto_points` 中不存在任意两点 `a,b` 使 `a` 支配 `b`。

### epsilon monotonic diagnostic

预算逐渐放宽时：

```text
best found Qss should be non-increasing
```

若因为 heuristic 搜索出现逆转，不能 silently reorder/伪造结果；记录 search-quality warning，并允许用更高 restart budget 重跑异常区间。

---

# 20. 精确性声明

文档、README、GUI 必须保持以下措辞边界：

## 可以说

> 给定一个 Offset assignment 后，MainFunction 分组在当前 CPU Proxy 模型下由确定性子集 DP 精确求解。

> 联合优化通过 epsilon-constraint 框架搜索 CAN/CPU 非支配折中方案。

> 推荐方案是当前搜索得到的非支配集合中的几何 knee 点。

## 不可以说

> 整个 CAN/CPU 联合问题已经证明全局最优。

> CPU Proxy 就是真实 CPU 占用率。

> AUTOSAR 标准强制要求 TimeBase 必须等于这些 gcd。

原因：

- 外层 Offset 仍由 GCLS heuristic 搜索；
- `rho` 未经 ECU 测量标定时只是结构参数；
- AUTOSAR 明确允许内部 timing handling implementation-specific，本设计的 gcd/tick 约束是工具生成精确可表示建议的工程模型。

---

# 21. 理论来源

1. AUTOSAR, *Specification of Communication*, Classic Platform R25-11, Document ID 15.  
   <https://www.autosar.org/fileadmin/standards/R25-11/CP/AUTOSAR_CP_SWS_COM.pdf>

2. C. L. Liu, J. W. Layland, “Scheduling Algorithms for Multiprogramming in a Hard-Real-Time Environment,” *Journal of the ACM*, 20(1), 46-61, 1973.  
   DOI: <https://doi.org/10.1145/321738.321743>

3. G. Mavrotas, “Effective implementation of the ε-constraint method in Multi-Objective Mathematical Programming problems,” *Applied Mathematics and Computation*, 213(2), 455-465, 2009.  
   DOI: <https://doi.org/10.1016/j.amc.2009.03.037>

4. V. Satopaa, J. Albrecht, D. Irwin, B. Raghavan, “Finding a Kneedle in a Haystack: Detecting Knee Points in System Behavior,” *ICDCS Workshops*, 166-171, 2011.  
   DOI: <https://doi.org/10.1109/ICDCSW.2011.20>
