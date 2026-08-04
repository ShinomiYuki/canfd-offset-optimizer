# 理论增补审计：复杂性、参数化可解性与目标耦合结构

> 审计日期：2026-07-31
>
> 代码基线：`feature/joint-gui`，`5f6db41bcbc9bec7e57ab193cc68c4a4d4ff886b`
>
> 性质：独立审计稿，不是论文宣传稿；本轮不修改任何 `.tex` 或生产算法。

## 1. 审计目的与结论状态

本文审计四组理论命题，并把“形式证明”“有限枚举”“实现事实”和“真实网段观察”
分开：

| 编号 | 结论 | 状态 | 证据边界 |
|---|---|---|---|
| T1 | 显式有限时隙命中表示下的带权离散 Offset 峰值判定问题为 NP-complete | **VERIFIED** | 形式归约完整；V1 有限枚举通过；只由 PARTITION 得到受限两时隙子类的弱 NP 完全性，不证明一般问题强 NP-hard |
| T2-a | 当前线性、身份对称成本下，存在一个不拆分相同 D 类型的最优分组 | **VERIFIED** | 交换证明完整；V4 与报文级 Bell 枚举一致；不声称所有最优解均不拆分 |
| T2-b | 固定 Offset 的周期调用分组问题关于不同 D 类型数 \(m\) 为 FPT | **VERIFIED** | \(O(3^m\operatorname{poly}(|I|))\) 时间及位复杂度证明完整；V4 核对状态与转移数 |
| T3-a | \(P^\star\) 经 D 向量、进一步经 D 直方图因子分解 | **VERIFIED** | 当前成本的置换对称性证明完整；V3 与生产内层、独立 Bell oracle 一致 |
| T3-b | 软件水平数及二维非支配目标点数满足组合上界 | **VERIFIED** | 计数证明完整；V5 有限枚举通过 |
| T3-c | D 直方图对含报文特异成本的扩展模型仍充分 | **REJECTED** | V3 给出同直方图但不同最优成本的反例 |
| T4 | 通信均衡与软件代理成本可在两报文实例上严格冲突 | **VERIFIED** | 四个 Offset、全部划分的符号枚举完整；V2 对 20 个 \((\rho,w)\) 组合通过 |
| 新颖性 | 上述问题名称、FPT 算法或 NP-hardness 证明为首次提出 | **UNRESOLVED** | 已核对标准来源，但未完成独立、系统的 prior-art audit |

状态含义：

- **PROVED**：形式证明完整；
- **VERIFIED**：形式证明与独立有限枚举均通过；
- **CONDITIONAL**：结论依赖明确列出的模型假设；
- **UNRESOLVED**：证据不足；
- **REJECTED**：存在反例或原表述过强。

验证脚本为 `scripts/verify_theory_claims.py`。命令

```text
python scripts/verify_theory_claims.py --seed 20260731 --random-cases 1000 --output-dir output/diagnostics/theory_claims
```

在本次环境中得到 V1--V5 全部 `VERIFIED`。这表示独立有限枚举未发现反例，并与
下文形式证明一致；它本身不是数学证明。

## 2. 当前模型、符号和必要假设

### 2.1 仓库事实来源

事实优先级及定位如下：

1. 生产实现：
   - `src/canfd_offset_optimizer/optimization/main_function.py`
   - `src/canfd_offset_optimizer/optimization/objective.py`
   - `src/canfd_offset_optimizer/timeline/slot_map.py`
   - `src/canfd_offset_optimizer/optimization/joint.py`
2. 测试：
   - `tests/unit/test_main_function.py`
   - `tests/unit/test_joint.py`
3. 最终归档：
   - `output/final_paper_nine_network/`
   - `docs/final_nine_network_paper_data_report.md`
4. 当前论文：`paper/main.tex`。

`output/final_paper_nine_network/manifest_snapshot.yaml` 所属实验归档记录的源提交为
`80b9ae3ec18d4c7f6ebce2eca02a6fb7b4f6922a`，不是本审计基线 HEAD。因此本稿只把
它作为带自身 provenance 的既有归档，不伪称为当前提交现场复跑。该 manifest 的
`source_worktree_status` 还记录了非干净 worktree；即使归档内部数据验证为
`paper_ready`，这一事实仍须作为复现性限制保留。

### 2.2 当前真实公式

所有时间在生产内层中为正整数微秒。对报文 \(i\)：

\[
D_i(O_i)=\gcd(T_i,O_i),\qquad \gcd(T_i,0)=T_i.
\]

对非空组 \(G\)：

\[
B_G=\gcd_{i\in G}D_i,\qquad
c(G)=\frac{\rho+|G|}{B_G},\qquad \rho>0.
\]

固定 Offset 向量 \(\boldsymbol O\) 后：

\[
P^\star(\boldsymbol O)
=\min_{\Pi}\sum_{G\in\Pi}\frac{\rho+|G|}{B_G}.
\]

生产返回值采用每秒尺度

\[
P^\star_{\rm impl}=10^6P^\star,
\]

见 `main_function.py` 中 `_MICROSECONDS_PER_SECOND` 和
`subset_cost[mask]`。正比例因子 \(10^6\) 不改变划分的成本排序，却必须在对照
JSON 数值时保留。提示中未写这一因子属于单位口径差异，不是模型冲突。

通信侧使用 SlotMap 的显式候选命中表。稳态时隙负载、峰值和平方和为

\[
L_s^{\rm ss}(\boldsymbol O)
=\sum_i w_i n_{i,s}^{\rm ss}(O_i),\quad
Z^{\rm ss}=\max_s L_s^{\rm ss},\quad
Q^{\rm ss}=\sum_s(L_s^{\rm ss})^2.
\]

联合 Pareto 支配只比较 \((Q^{\rm ss},P^\star)\)；Peak 是 hard guardrail，而不是
第三个几何目标。

### 2.3 T2/T3 的必要假设

下文软件结论共同依赖：

1. 时间量位于共同整数栅格；
2. 所有组使用共同的正有理数 \(\rho\)；
3. 单次组成本对报文身份对称，变量项恰为组内报文数；
4. 无禁止同组、容量、节点归属或报文特异处理成本；
5. 可行划分是报文全集的任意非空块集合划分；
6. \(P^\star\) 使用精确有理数比较。

缺少任一项时，D 类型压缩或直方图充分性均须重新证明。

## 3. 带权离散 Offset 峰值分配判定问题

### 3.1 编码明确的判定版本

定义 **Explicit Weighted Discrete Offset Peak Decision**（EWDOPD）：

- 报文索引集合 \(M=\{1,\ldots,n\}\)；
- 每条报文的二进制编码正整数权重 \(w_i\)；
- 有限候选集合 \(A_i\)；
- 对每个 \((i,o)\)，显式给出命中的稳态时隙索引列表
  \(H_{i,o}\)；列表允许同一时隙重复，以表达一个窗口内多次释放；
- 非负整数阈值 \(B\)。

一个证书为 \(\boldsymbol O\in\prod_i A_i\)。令

\[
L_s(\boldsymbol O)
=\sum_i w_i\,\operatorname{mult}_s(H_{i,O_i}),\qquad
Z^{\rm ss}(\boldsymbol O)=\max_sL_s(\boldsymbol O).
\]

问题问是否存在 \(\boldsymbol O\) 使 \(Z^{\rm ss}(\boldsymbol O)\le B\)。

这与当前 `SlotMap.hits[(message.name, offset)].steady` 的预计算形态一致：两者都在
求解前把候选映射到有限时隙命中。但复杂度结论针对**显式列表长度**；若超周期
\(H\) 由二进制大整数隐式给出，直接展开 \(H/\Delta\) 未必对数值输入长度为
多项式，故不声称所有编码方式都与 SlotMap 展开完全等价。

## 4. NP 完全性审计

### 4.1 NP 成员资格 — **PROVED**

给定证书 \(\boldsymbol O\)，验证器：

1. 检查每个 \(O_i\in A_i\)；
2. 扫描所选显式命中列表；
3. 用二进制整数累计每个时隙的负载；
4. 比较所有负载与 \(B\)。

最多执行显式列表总长度次加法。每个累计值的位长不超过
\(\log n+\max_i\log w_i+\log h_{\max}\) 的多项式量级。因此验证时间对显式输入
长度为多项式，EWDOPD 属于 NP。

### 4.2 从 PARTITION 的归约 — **VERIFIED**

给定正整数 \(a_1,\ldots,a_n\)。

若总和为奇数，输出固定 no-instance：两条权重分别为 1 和 2 的报文均可选两个
时隙，阈值为 1。总负载为 3，放入两个时隙后至少一个时隙负载不小于 2，故必为
no-instance。

若总和为 \(2B\)，对每条报文构造：

\[
\Delta=5\text{ ms},\quad T_i=10\text{ ms},\quad
A_i=\{15\text{ ms},20\text{ ms}\},\quad w_i=a_i.
\]

取 \(O_{\max}=20\text{ ms}\) 及稳态窗口
\(I^{\rm ss}=[20,30)\text{ ms}\)。显式命中为：

- \(O_i=20\text{ ms}\)：唯一命中 \([20,25)\)；
- \(O_i=15\text{ ms}\)：窗口内下一次释放为 25 ms，唯一命中 \([25,30)\)。

于是每个 \(a_i\) 恰好被分到两个时隙之一。

**正向。** 若 PARTITION 存在和为 \(B\) 的子集，把该子集选择 20 ms，余集选择
15 ms；两个时隙负载均为 \(B\)，故 \(Z^{\rm ss}=B\)。

**反向。** 若某 Offset 分配满足 \(Z^{\rm ss}\le B\)，两时隙负载总和为 \(2B\)，
且各自不超过 \(B\)，所以二者都恰为 \(B\)。选择 20 ms 的报文权重构成原实例的
等和子集。

构造只产生 \(O(n)\) 个候选及命中项；除复制 \(a_i\) 和 \(B\) 外，所有时间常数
固定。输出数值的位长与输入位长成多项式关系。因此这是多项式 many-one 归约。

**严格结论。**

- EWDOPD 即使限制为相同周期、每条报文两个候选、两个稳态时隙、每候选只命中
  一次，仍为 NP-complete；
- 对应最小化峰值问题为 NP-hard；
- 该**受限两时隙子类**与 PARTITION 同属弱数值困难性，并存在按总权重参数化的
  伪多项式思路；
- 对更一般 EWDOPD，本归约只证明 NP-hard，**不能**据此排除它还存在另一强
  NP-hardness 归约。

因此禁止由本证明推出：

- 强 NP-hardness；
- 不存在伪多项式算法或 FPTAS；
- 实际规模的精确求解器不可用；
- “只能使用启发式”；
- 真实 CAN FD `frame_time_us` 物理权重子类也 NP-hard。

这里 \(w_i=a_i\) 是抽象模型中的任意正整数，不一定可由合法 CAN FD 帧时生成。
物理权重子类需要额外归约，当前状态为 **UNRESOLVED**。

### 4.3 联合判定问题的 NP-hard 推论 — **PROVED**

给 EWDOPD 实例附加整数 \(T_i,O_i\) 及共同正有理 \(\rho\)，定义联合判定：

\[
Z^{\rm ss}(\boldsymbol O)\le B,\qquad
P^\star_{\rm impl}(\boldsymbol O)\le U.
\]

对任意 assignment，单例划分可行，故

\[
P^\star_{\rm impl}(\boldsymbol O)
\le \sum_i\frac{10^6(\rho+1)}{\gcd(T_i,O_i)}.
\]

取候选感知的输入可计算上界

\[
U=\sum_i\max_{o\in A_i}
\frac{10^6(\rho+1)}{\gcd(T_i,o)}.
\]

有限候选显式给出，所有 gcd、分数比较及最大值均可在输入长度多项式时间内计算，
且 \(U\) 的位长为多项式。这个预算对所有 assignment 都宽松，软件约束不排除
任何 T1 解。因此联合问题包含 T1 为特例，故为 NP-hard。这只是安全预算推论，
不是第二个独立深归约。

## 5. 周期调用分组问题的一般化定义

定义 **Periodic Activation Grouping Problem**（周期调用分组问题，PAGP）。此名称
仅为本稿工作名称，不主张首次提出。

输入为：

- \(n\) 个对象及其正整数 \(D_i\)；
- 正有理数 \(\rho=p/q\)，其中 \(p,q\) 用二进制编码；
- 可选的正公共尺度 \(S\)；数学式取 \(S=1\)，生产式取 \(S=10^6\)。

可行解是对象集合的任意集合划分 \(\Pi\)。每个非空组 \(G\) 的最大精确调用周期及
成本为

\[
B_G=\gcd_{i\in G}D_i,\qquad
C(G)=S\frac{\rho+|G|}{B_G}.
\]

优化版本最小化

\[
P(\Pi)=\sum_{G\in\Pi}C(G).
\]

判定版本另给正有理阈值 \(K\)，询问是否存在 \(P(\Pi)\le K\)。

这一定义忠实于当前 `main_function.py`：没有额外报文系数、兼容性约束或固定的
全局常数项；`message_key` 只用于结果映射，不进入成本或 tie-break。

### 5.1 同 D 类型压缩 — **VERIFIED**

设同类型 \(d\) 分散在组 \(G_1,G_2\)，对应 gcd 为 \(B_1\le B_2\)。两者均整除
\(d\)。从 \(G_1\) 移一条类型 \(d\) 的对象到 \(G_2\)：

- 若 \(G_1\) 仍含类型 \(d\)，两组 gcd 不变，成本变化为
  \(S(-1/B_1+1/B_2)\le0\)；
- 若移出的是 \(G_1\) 最后一条 \(d\)，但余组 \(H\ne\varnothing\)，删除 gcd
  参数只会令 \(B'_1=\gcd_{i\in H}D_i\) 成为 \(B_1\) 的倍数，故相关成本变化不大于
  \(S(-1/B_1+1/B_2)\le0\)；
- 若 \(G_1\) 原为该对象的单例，则 \(B_1=d\)。由 \(B_1\le B_2\mid d\) 得
  \(B_2=d\)，合并后严格省去 \(S\rho/d\)。

对每个分散类型有限次重复，得到不拆分任何同类型对象、且成本不增的划分。从全局
最优解出发即得到同成本最优解。因此：

> 至少存在一个全局最优解，使相同 D 类型不被拆到多个组。

证明依赖公共 \(\rho\)、线性报文数项、身份对称和无兼容性约束。它不推出所有最优
解均具有该结构。

令不同类型为 \(d_1<\cdots<d_m\)，重数为 \(c_1,\ldots,c_m\)。对非空类型子集
\(A\subseteq[m]\)：

\[
N(A)=\sum_{j\in A}c_j,\quad
B(A)=\gcd_{j\in A}d_j,\quad
C(A)=S\frac{\rho+N(A)}{B(A)}.
\]

## 6. D 类型压缩与精确子集 DP

令 \(F(S)\) 为类型子集 \(S\subseteq[m]\) 的最小成本，\(F(\varnothing)=0\)。
对非空 \(S\) 取规范锚点 \(a(S)=\min S\)：

\[
F(S)=
\min_{\substack{A\subseteq S\\a(S)\in A}}
\{C(A)+F(S\setminus A)\}.
\]

每个无序划分中恰有一个块包含 \(a(S)\)；选定此块后，余块唯一构成
\(S\setminus A\) 的划分。因此递推不重不漏。对 \(|S|\) 归纳，固定锚点块时余集
必须取最优子结构，再对所有锚点块取最小，得到类型级全局最优。结合 5.1 的存在性
结论，类型级最优值等于报文级最优值。

当前实现还使用 `(cost, group_count, canonical_group_signature)` 作确定性消歧。
后两项只在成本完全相等时选择代表，不改变 \(P^\star\)。

## 7. 关于不同 D 类型数 \(m\) 的 FPT 性质

### 7.1 时间 — **PROVED**

全部非空状态的规范转移数恰为

\[
\sum_{\varnothing\ne S\subseteq[m]}2^{|S|-1}
=\frac{1}{2}\left(\sum_{k=0}^{m}\binom mk2^k-1\right)
=\frac{3^m-1}{2}.
\]

预计算全部 \(2^m\) 个子集的重数和、gcd、成本及签名需要
\(2^m\operatorname{poly}(|I|)\) 时间。加上转移，运行时间为

\[
O(3^m\operatorname{poly}(|I|)).
\]

这符合 FPT 的 \(f(m)|I|^{O(1)}\) 定义，故 PAGP 关于参数 \(m\) 为
fixed-parameter tractable。

不能省略 \(\operatorname{poly}(|I|)\)，也不能写成“一般多项式时间可解”。当
\(m=n\) 时仍可能为 \(O(3^n\operatorname{poly}(|I|))\)。

### 7.2 位复杂度 — **PROVED**

设输入整数最大位长为 \(L\)，\(\rho=p/q\) 的分子分母位长包含在 \(|I|\) 中。

- 子集 gcd 用 Euclid 算法，单次位复杂度为 \(L\) 的多项式；
- 子集重数和至多为 \(n\)，位长 \(O(\log n)\)；
- 单组成本可写为
  \(S(p+qN(A))/(qB(A))\)，分子分母位长为 \(\operatorname{poly}(|I|)\)；
- 一个 DP 值至多相加 \(m\) 个组成本。即使按分母乘积作保守估计，中间分子、
  分母位长也只线性累加 \(m\) 个输入级位长，仍为
  \(\operatorname{poly}(|I|)\)；
- 精确加法、约分和交叉乘比较因此均为输入长度的多项式；
- 由前驱重建至多取出 \(m\) 个组，另需
  \(O(m\operatorname{poly}(|I|))\) 时间。

### 7.3 空间 — **PROVED**

- 若每个状态只保存最优分数与一个前驱 mask：

  \[
  O(2^m\operatorname{poly}(|I|)).
  \]

- 当前实现同时为每个状态保存规范化分组结构，并预存子集签名；每个结构最坏含
  \(O(m)\) 个类型索引：

  \[
  O(m2^m\operatorname{poly}(|I|)).
  \]

既有 `docs/main_function_exact_solver_report.md` 的简写 `O(2^m)` 忽略了这一实现
表示成本；作为值/前驱算法口径可以成立，但不是当前对象存储的最紧审计口径。

### 7.4 新颖性边界 — **UNRESOLVED**

一般 complete set partitioning 已有指数时间精确 DP 和更快的代数/包含排除算法。
本工作的潜在理论价值不能归因于通用 \(O(3^m)\) 集合划分递推本身，只能审慎定位于：

1. 当前 gcd 组成本下 same-D 压缩是否严格保持至少一个最优解；
2. \(m\) 是否是自然参数；
3. 真实归档中 \(m=4\ldots6\) 是否使参数化视角具有工程意义。

在完成系统 prior-art audit 前，不声称算法、问题命名或 FPT 观察为首创。

## 8. Offset 到 D 结构的因子分解

### 8.1 可达约数子集 — **PROVED**

对候选集合 \(A_i\) 定义

\[
\mathcal D_i
=\{\gcd(T_i,o):o\in A_i\}.
\]

因为每个 gcd 都整除 \(T_i\)：

\[
\mathcal D_i\subseteq\operatorname{Div}(T_i).
\]

\(\operatorname{Div}(T_i)\) 在整除关系下构成有限格，meet 为 gcd，join 为 lcm。
但 \(\mathcal D_i\) 通常不封闭。例如 \(T_i=12,A_i=\{2,3\}\) 时
\(\mathcal D_i=\{2,3\}\)，其 gcd 1 和 lcm 6 均不在集合中。因此可达集合未必为
子格，且不能写成“恰为全部正约数”。

对 \(d\in\mathcal D_i\) 定义 gcd 纤维

\[
\mathcal F_{i,d}
=\{o\in A_i:\gcd(T_i,o)=d\}.
\]

关系

\[
o\sim_i o'\iff\gcd(T_i,o)=\gcd(T_i,o')
\]

把有限候选集划分为软件侧 D 等价类。一般 gcd 纤维不是普通同余类，也不是单一
同步模类。

### 8.2 D 向量因子分解 — **PROVED**

令

\[
\Phi(\boldsymbol O)
=(D_1(O_1),\ldots,D_n(O_n)).
\]

若 \(\Phi(\boldsymbol O)=\Phi(\boldsymbol O')\)，任一报文集合 \(G\) 在两个
assignment 下的 gcd、组大小及成本都相同；全部可行划分集合也相同。故逐划分成本
相等，取最小后有

\[
P^\star(\boldsymbol O)=P^\star(\boldsymbol O').
\]

### 8.3 D 直方图充分性 — **VERIFIED**

对 \(d\in R=\bigcup_i\mathcal D_i\)，定义

\[
h_d(\boldsymbol O)
=|\{i:D_i(O_i)=d\}|.
\]

若两个 assignment 的直方图相同，则存在保持 D 值的报文双射。当前组成本不依赖
报文身份；该双射在两实例的集合划分之间建立双射，并逐组保持 gcd、基数与成本。
因此：

\[
h(\boldsymbol O)=h(\boldsymbol O')
\Longrightarrow
P^\star(\boldsymbol O)=P^\star(\boldsymbol O').
\]

所以在 2.3 假设下，D 直方图是当前软件代理子问题的充分统计量。

该命题在以下扩展中不自动成立：

- 报文具有不同执行成本；
- 某些报文禁止同组；
- MainFunction 有容量或节点约束；
- 成本显式依赖报文身份；
- \(\rho\) 随组或报文变化。

**反例。** 令两个身份的变量成本为 1 和 10，\(\rho=1\)。实例一把
\((D_1,D_2)=(20,5)\)，实例二把身份对换为 \((5,20)\)。两者直方图相同。扩展组
成本取 \((\rho+\sum_{i\in G}c_i)/\gcd_{i\in G}D_i\) 时，独立 Bell 枚举分别得到
\(23/10\) 和 \(19/20\)，故最优成本不同。V3 已机器核对该反例。

不同直方图也可能得到同一个 \(P^\star\)。例如 \(\rho=1\) 时，
\((10,10)\) 与 \((10,20)\) 的最优成本都为 \(3/10\)。所以准确表述是：

> 跨越 D 等价类是软件代价发生变化的必要途径，但不是充分条件。

禁止写“跨 D 类时 \(P^\star\) 必然跳跃”。

## 9. 通信均衡与软件代价的严格冲突构造

取

\[
T_1=T_2=20\text{ ms},\quad
A_1=A_2=\{20,25\}\text{ ms},\quad
w_1=w_2=w>0,\quad \rho>0,
\]

\[
O_{\max}=25\text{ ms},\quad
I^{\rm ss}=[25,45)\text{ ms},\quad \Delta=5\text{ ms}.
\]

Offset 20 ms 的窗口内释放为 40 ms；Offset 25 ms 的释放为 25 ms。每条报文在
稳态窗口恰释放一次。以下软件成本使用毫秒倒数的无公共尺度形式；生产每秒值只是
正比例换算。

| assignment | 释放关系 | \(Q^{ss}\) | D 向量 | 合并成本 | 两单例成本 | \(P^\star\) |
|---|---|---:|---|---:|---:|---:|
| (20,20) | 同槽 | \(4w^2\) | (20,20) | \((\rho+2)/20\) | \(2(\rho+1)/20\) | \((\rho+2)/20\) |
| (20,25) | 异槽 | \(2w^2\) | (20,5) | \((\rho+2)/5\) | \((\rho+1)/4\) | 两者较小值 |
| (25,20) | 异槽 | \(2w^2\) | (5,20) | \((\rho+2)/5\) | \((\rho+1)/4\) | 与上行相同 |
| (25,25) | 同槽 | \(4w^2\) | (5,5) | \((\rho+2)/5\) | \(2(\rho+1)/5\) | \((\rho+2)/5\) |

对任意 \(\rho>0\)，令 A=(20,20)、B=(20,25)。A 的成本小于 B 的两个候选划分
成本：

\[
\frac{\rho+2}{20}<\frac{\rho+2}{5},\qquad
\frac{\rho+2}{20}<\frac{\rho+1}{4}.
\]

同时 \(2w^2<4w^2\)。故

\[
Q_B^{ss}<Q_A^{ss},\qquad P_B^\star>P_A^\star.
\]

(25,25) 与 A 有相同 \(Q^{ss}\) 而软件成本更高，受 A 支配；两个混合 assignment
产生同一目标向量 B。完整目标像恰有两个非支配目标点 A、B。

结论为 **VERIFIED**：

> 通信均衡与软件代理成本在一般模型中并非天然同向，联合优化具有非冗余的数学
> 基础。

### 9.1 Peak guardrail 边界

A 的 Peak 为 \(2w\)，B 的 Peak 为 \(w\)。上述前沿结论只适用于无 Peak 约束，
或 guardrail 至少容纳 A 的情形。如果预算落在 \([w,2w)\)，A 被排除，严格权衡可
消失。因此 T4 不证明：

- 每个 Peak budget 下都有权衡；
- 默认 5% budget 下必然多点；
- 真实网段观测前沿已经完整；
- 外层搜索未遗漏其他点。

## 10. 软件代价水平与 Pareto 目标点数上界

### 10.1 D 向量及直方图上界 — **PROVED**

每个 Offset assignment 先映射到
\(\prod_i\mathcal D_i\)，再映射到 \(P^\star\)，故

\[
|\operatorname{range}(P^\star)|
\le\prod_i|\mathcal D_i|
\le\prod_i\tau(T_i),
\]

其中 \(\tau(T_i)=|\operatorname{Div}(T_i)|\)。

令 \(R=\bigcup_i\mathcal D_i\)，\(r=|R|\)，并令
\(\mathcal H_{\rm reachable}\) 为实际可达直方图集合。由直方图充分性：

\[
|\operatorname{range}(P^\star)|
\le|\mathcal H_{\rm reachable}|
\le
\min\left\{
\prod_i|\mathcal D_i|,
\binom{n+r-1}{r-1}
\right\}.
\]

第二项是 stars-and-bars 对所有总和为 \(n\) 的 \(r\) 维非负直方图的计数。由于
不同报文的可达集合不同，并非每个直方图都可达；不同可达直方图也可能给出相同
\(P^\star\)。

### 10.2 二维目标前沿上界 — **PROVED**

在不同目标向量意义下，对每个固定 \(P^\star=p\)，只有该层最小
\(Q^{ss}\) 的向量可能非支配；同层更大的 \(Q^{ss}\) 被它支配。因此

\[
|\mathrm{PF}_{\rm objective}|
\le|\operatorname{range}(P^\star)|.
\]

这里计数的是不同 \((Q^{ss},P^\star)\) 向量，不是 assignments 或相同向量的多个
代表。加入 Peak guardrail 只会缩小可行 assignment 集，证明仍适用于受限集合。

## 11. 对真实网段能够和不能够作出的解释

既有最终归档报告称九网段不同 D 类型数为 4--6，中位数为 5，固定 Offset 内层
冷启动均低于 1 ms。这支持“\(m\) 是当前数据上的小参数”这一工程观察，但不是一般
复杂度结论。

最终 joint 汇总中的 observed Pareto 点数分别为：

| CH | DA | DK | EP | GL | IC | LC | PT | SU |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 4 | 10 | 40 | 1 | 32 | 27 | 1 | 4 | 1 |

可以陈述：

- 固定 Offset 的内层由当前模型精确评价；
- 归档 observed front 是 archive 内的二维非支配集合；
- EP、LC、SU 在该次 archive 中只观察到一个软件水平/非支配点；
- DK、GL、IC 达到 refinement pass 上限，不能称数学收敛。

不能陈述：

- observed front 是完整 Pareto frontier；
- 单点 observed front 证明全 Offset 空间 \(P^\star\) 恒定；
- 多个可达 \(P^\star\) 水平必然产生多点 Pareto 前沿；
- T4 证明九网段默认 Peak budget 下必有权衡；
- 归档源提交与当前 HEAD 相同。

只有未来诊断得到 `fixed_d_vector` 或在完整可达直方图枚举后得到
`proven_constant_pstar`，才能严格宣称软件目标在全部合法 Offset 空间中退化为
常数。

## 12. 文献定位与新颖性边界

本轮检索用于核对术语和限制新颖性表述，不构成系统综述。

1. Richard M. Karp, “Reducibility Among Combinatorial Problems,” 1972,
   [doi:10.1007/978-1-4684-2001-2_9](https://doi.org/10.1007/978-1-4684-2001-2_9)。
   用于经典 NP 完全性与多项式归约背景。
2. Rodney G. Downey and Michael R. Fellows, *Fundamentals of Parameterized
   Complexity*, 2013,
   [doi:10.1007/978-1-4471-5559-1](https://doi.org/10.1007/978-1-4471-5559-1)。
3. Jörg Flum and Martin Grohe, *Parameterized Complexity Theory*, 2006,
   [doi:10.1007/3-540-29953-X](https://doi.org/10.1007/3-540-29953-X)。
   后两项支持 FPT 的标准 \(f(k)|I|^{O(1)}\) 口径。
4. Andreas Björklund, Thore Husfeldt, and Mikko Koivisto,
   “Set Partitioning via Inclusion–Exclusion,” *SIAM Journal on Computing*
   39(2), 2009,
   [doi:10.1137/070683933](https://doi.org/10.1137/070683933)。
   该文给出多类 set partitioning 的 \(2^n n^{O(1)}\) 指数算法，并讨论多项式空间
   \(3^n n^{O(1)}\) 算法，足以否定“通用 \(O(3^m)\) 思想本身新颖”的表述。
5. Tomasz Michalak et al., “A Hybrid Exact Algorithm for Complete Set
   Partitioning,” *Artificial Intelligence* 230, 2016,
   [doi:10.1016/j.artint.2015.09.006](https://doi.org/10.1016/j.artint.2015.09.006)。
   用于 complete set partitioning 的既有 exact-DP/搜索定位。
6. Matthias Ehrgott, *Multicriteria Optimization*, 2nd ed., 2005,
   [doi:10.1007/3-540-27659-9](https://doi.org/10.1007/3-540-27659-9)。
   用于 efficiency/nondominance、标量化和多目标组合优化术语。
7. George Mavrotas, “Effective implementation of the
   \(\varepsilon\)-constraint method in Multi-Objective Mathematical
   Programming problems,” 2009,
   [doi:10.1016/j.amc.2009.03.037](https://doi.org/10.1016/j.amc.2009.03.037)。
   用于 \(\varepsilon\)-constraint 的标准定位。

审计结论：

- “PAGP” 是临时名称；
- 通用规范锚点子集 DP、FPT 定义、Pareto dominance 和
  \(\varepsilon\)-constraint 均有既有理论背景；
- same-D 压缩对本特定 gcd 成本的 prior art 尚未系统核完；
- T1 对该具体显式 Offset 表示的既有复杂性结果尚未系统核完。

所以“首次提出”“首个 NP-hardness 证明”“新的 FPT 算法”等新颖性宣称全部为
**UNRESOLVED**，本轮禁止使用。

## 13. Blocking / Major / Minor / Verified

### Blocking

1. **一般问题强 NP-hardness：UNRESOLVED。** 当前 PARTITION 归约不能支持。
2. **物理 `frame_time_us` 权重子类：UNRESOLVED。** 任意整数权重归约不能直接
   迁移。
3. **九网段完整 Pareto 前沿：UNRESOLVED。** 外层搜索未穷举。
4. **新颖性：UNRESOLVED。** 需要独立 prior-art audit。

### Major

1. D 压缩与直方图充分性必须始终附带身份对称、公共 \(\rho\)、无兼容约束假设。
2. 单点 archive 不等于全空间常数目标。
3. 实验 manifest 源提交与当前 HEAD 不同，引用时必须保留 provenance。
   manifest 还记录了非干净源 worktree，不能改写为 clean-commit 复跑。
4. FPT 只关于 \(m\)，不是关于总报文数 \(n\) 的一般多项式算法。

### Minor

1. 数学成本与生产每秒成本相差公共 \(10^6\) 尺度。
2. 当前 DP 对象存储空间应按 \(O(m2^m\operatorname{poly}(|I|))\) 审计。
3. 可达 D 集合只是约数格子集，通常不是子格。

### Verified

- T1 的 NP 成员资格及 PARTITION 双向归约；
- 联合判定的宽松软件预算推论；
- same-D 存在性压缩；
- 规范锚点递推、转移总数和 FPT 位复杂度；
- D 向量/直方图因子分解；
- 身份特异成本边界反例；
- T4 四 assignment 完整目标像；
- 软件水平与 Pareto 目标点数上界；
- V1--V5 在固定种子与 1000 个随机案例口径下通过。

## 14. 未来论文章节映射，但本轮不修改论文

| 未来位置 | 可映射内容 | 前置条件 |
|---|---|---|
| 复杂性小节 | EWDOPD 定义、NP-complete、弱困难性边界 | 明确保留显式命中编码和物理权重限制 |
| MainFunction 模型 | PAGP 定义、same-D 交换证明 | 不改变当前成本假设 |
| 参数化分析 | \(O(3^m\operatorname{poly}(|I|))\)、位复杂度、空间双口径 | 不宣称通用 DP 新颖 |
| Offset--CPU 结构 | 可达约数、gcd 纤维、直方图充分性 | 同时写出扩展模型反例 |
| 联合优化动机 | 两报文严格冲突构造 | 单独写 Peak guardrail 边界 |
| 实验解释 | D 诊断的 exactness 分类与 coverage | 先实现并完成九网段只读诊断 |
| 局限性 | strong hardness、物理权重、全局 Pareto、新颖性 | 维持 UNRESOLVED，等待后续工作 |

本轮未修改论文正文、生产求解器、GUI、配置或既有实验结果。
