# 九网段 D 结构诊断设计

> 设计状态：`DESIGN_ONLY`
>
> 未来只读命令：`analyze-d-structure`
>
> 本轮不实现 CLI、生产模块或正式配置项，不读取或生成真实 DBC 内容。

## 1. 诊断目的

`analyze-d-structure` 用于回答三个彼此不同的问题：

1. 每条报文的合法 Offset 候选经
   \(D_i(o)=\gcd(T_i,o)\) 后能到达哪些 D 类型？
2. 一个网段在**全部合法联合 Offset 空间**中能到达哪些 D 直方图及
   \(P^\star\) 水平？
3. 既有联合搜索 archive 实际观察到了其中多少结构？

命令只做读取、精确变换、计数和对照。它不得改变：

- Offset 或候选集合；
- GCLS、Peak reference 或 Peak budget；
- 联合搜索 archive、推荐点或 knee；
- MainFunction 分组求解逻辑；
- DBC/ARXML/路由表；
- 九网段 manifest、配置默认值或实验基线。

该诊断的首要用途是区分：

- “软件目标在全合法 Offset 空间内可证明为常数”；
- “现有 archive 只观察到一个水平”；
- “状态空间未枚举完，无法判断”。

## 2. 输入与事实来源

### 2.1 权威输入

九网段批处理按以下顺序读取事实：

1. `docs/final_nine_network_manifest.yaml`
   - network id；
   - DBC 路径及 SHA-256；
   - selected sender；
   - routing target、路由表路径及 SHA-256；
   - eligible-set hash；
   - Offset 网格及 joint decision/fixed 计数；
   - 归档源 commit。
2. 当前生产加载链
   - `src/canfd_offset_optimizer/final_experiment.py`
     的 `load_final_experiment_project()`；
   - `parsers/project_loader.py` 的 sender、routing exclusion、
     `GenMsgStartDelayTime` 和 timing 校验；
   - `optimization/joint.py` 的 decision/fixed domain 规则。
3. 当前精确软件内层
   - `optimization/main_function.py` 的
     `solve_main_function_proxy_exact()`。
4. 既有最终 archive
   - `output/final_paper_nine_network/joint/<network>/results/`
     `<network>_joint_summary.json`；
   - 其中 `candidate_archive.solutions` 是完整 observed assignment 集；
   - `pareto_solutions` 只用于附加对照，不能替代 archive。

不允许从论文表格反推报文输入或候选；论文和报告只作说明性背景。

### 2.2 运行参数

未来命令建议接受只读参数：

```text
analyze-d-structure \
  --manifest docs/final_nine_network_manifest.yaml \
  --network CH \
  --rho 1 \
  --archive output/final_paper_nine_network/joint/CH/results/CH_joint_summary.json \
  --output-root output/diagnostics \
  --max-histogram-states 1000000 \
  --max-exact-pstar-evaluations 1000000 \
  --timeout-s 300
```

批量模式可省略 `--network`，严格按 manifest 的 CH、DA、DK、EP、GL、IC、LC、PT、
SU 顺序运行。默认值在未来实现时通过 CLI 局部提供；本轮不修改正式 YAML 配置。

### 2.3 输入校验与 fail closed

进入计算前必须检查：

- manifest schema 和九个 network id；
- 文件存在性及 manifest 中记录的输入 hash；
- selected sender、routing exclusion、eligible-set hash；
- 当前加载后的每条报文 key 唯一、\(T_i>0\)；
- 每条候选为非负整数，候选集合非空；
- 当前 joint decision/fixed 数量与 manifest 一致；
- fixed message 的联合候选恰为 `{0}`；
- \(\rho\) 可精确归一化为正 `Fraction`；
- archive 的 network、输入/config/commit provenance 与本次输入可比较；
- archive 每个 assignment 完整覆盖 eligible messages、Offset 合法且 hash 可复算。

任何数学前提失败均返回 `invalid_input`，不做“尽力猜测”。archive provenance 不一致
时仍可计算当前可达结构，但 archive coverage 必须标为 `not_comparable`，不得混合
两个输入口径。

## 3. 数学定义

对报文 \(i\)：

\[
D_i(o)=\gcd(T_i,o),\qquad
\mathcal D_i=\{D_i(o):o\in A_i\}.
\]

对 \(d\in\mathcal D_i\)：

\[
\mathcal F_{i,d}
=\{o\in A_i:D_i(o)=d\}.
\]

令全网段可达 D 并集按升序为

\[
R=(r_1,\ldots,r_q)=\operatorname{sort}\left(\bigcup_i\mathcal D_i\right).
\]

一个 D 直方图表示为长度 \(q\) 的 tuple：

\[
h=(h_1,\ldots,h_q),\qquad
h_j=|\{i:D_i(O_i)=r_j\}|,\quad \sum_jh_j=n.
\]

按当前身份对称成本，直方图对应规范输入

\[
H_D(h)=((r_j,h_j):h_j>0),
\]

其精确软件水平为

\[
P^\star(h)
=\operatorname{solve\_main\_function\_proxy\_exact}(H_D(h),\rho).
\]

生产返回值保留 `Fraction`，包含每秒尺度 \(10^6\)；不得用 float 代替相等性判断。

理论上界：

\[
V_{\max}=\prod_i|\mathcal D_i|,
\qquad
L_{\rm div}=\prod_i\tau(T_i),
\qquad
H_{\max}=
\min\left\{V_{\max},\binom{n+q-1}{q-1}\right\}.
\]

当前 joint domain 是各报文候选的笛卡尔积，故可达 D **向量**数恰为
\(\prod_i|\mathcal D_i|\)；如果未来引入跨报文 Offset 约束，这个等式失效，输入
必须拒绝或由新的约束感知算法处理。

## 4. 可达 D 集合计算

### 4.1 每报文算法

对每条报文按候选 Offset 升序扫描：

1. 精确计算 `d = gcd(period_us, offset_us)`；
2. 记录 `(offset_us, d)`；
3. 以 d 为键构造 gcd 纤维；
4. 对 d 去重、升序得到 `Dset_i`；
5. 用整数因数分解或试除计算 \(\tau(T_i)\)；
6. 检查 `Dset_i ⊆ Div(T_i)`。

不得把未出现在候选映射中的正约数补入 `Dset_i`。

### 4.2 每报文输出字段

`d_structure_messages.csv` 每行至少包含：

- `network_id`
- `message_key`
- `message_name`
- `definition_index`
- `can_id`
- `is_extended_id`
- `period_us`
- `joint_offset_candidates_us`
- `offset_to_d_us`
- `reachable_d_values_us`
- `gcd_fibers`
- `gcd_fiber_sizes`
- `tau_period`
- `reachable_d_count`
- `all_divisor_count`
- `single_reachable_d`
- `is_joint_fixed_message`

CSV 中复合字段使用规范 JSON 字符串；列表按数值升序，message 按稳定 key 排序。
message identity 不得只用可能重复的显示名称。

### 4.3 隐私与哈希

诊断可读取本地已授权输入，但输出不得复制 DBC 文本、信号定义或原始路由表行。
只输出本模型所需的报文 identity、周期、候选和哈希。真实 DBC 不进入 Git；报告
沿用 manifest 的 SHA-256。

## 5. 可达 D 直方图 DP

### 5.1 递推

禁止枚举完整 Offset 笛卡尔积。初始化

\[
\mathcal H_0=\{(0,\ldots,0)\}.
\]

依次按稳定 message key 处理报文 \(i\)：

\[
\mathcal H_i=
\left\{
h+e_d:
h\in\mathcal H_{i-1},
d\in\mathcal D_i
\right\},
\]

其中 \(e_d\) 是 d 在有序 \(R\) 中对应坐标的单位向量。每轮：

1. 使用整数 tuple 生成；
2. 去重；
3. 按 tuple 字典序稳定排序；
4. 记录输入状态数、候选扩展数、去重后状态数和耗时。

若未触发 cap，\(\mathcal H_n\) 恰为全部可达 D 直方图。

### 5.2 正确性

对 \(i\) 归纳。基础状态表示尚未处理报文时的零直方图。假设
\(\mathcal H_{i-1}\) 精确表示前 \(i-1\) 条报文的全部选择；第 i 条的任一合法
Offset 只通过某个 \(d\in\mathcal D_i\) 增加一个坐标，故递推覆盖所有新选择。
反向地，每个生成状态都由一个旧可达状态和一个实际可达 d 组成，所以可由候选
Offset 实现。去重只合并同一直方图，不删除结构。归纳成立。

### 5.3 不枚举 D 向量

报告中的可达 D 向量数在当前独立候选模型下直接取
\(\prod_i|\mathcal D_i|\)。不落盘 D 向量，也不从 D 向量再聚合直方图。

## 6. \(P^\star\) 水平精确计算与缓存

直方图枚举完成或产生可评价的稳定状态后：

1. 把 tuple 转成非零 `(d_us, count)` 规范直方图；
2. 以 `(rho_numerator, rho_denominator, histogram)` 为 cache key；
3. 对每个唯一直方图调用当前
   `solve_main_function_proxy_exact()` **一次**；
4. 保存精确分子、分母和规范字符串；
5. 按 `(P* exact, histogram tuple)` 稳定排序。

诊断层缓存与生产求解器自身 LRU 分开计数，以便报告：

- histogram evaluations requested；
- diagnostic cache hits/misses；
- production cache 前后差值；
- exact solver elapsed time。

如果完整直方图已知但 `max_exact_pstar_evaluations` 或 timeout 先到，则可报告精确
直方图数，却不能报告完整 \(P^\star\) 水平数。此时：

- 已观察水平数只是下界；
- 水平数上界为完整直方图数；
- `proven_constant_pstar` 不成立；
- 状态归为 `capped`，停止原因标为 `pstar_cap` 或 `timeout`。

## 7. 与联合搜索归档的对照

### 7.1 archive 读取

读取 `<network>_joint_summary.json`：

- 首选 `candidate_archive.solutions`；
- 每个 solution 读取完整 assignment，不只读取 Pareto 代表；
- 用本次已验证的 message facts 重新计算 D 向量和直方图；
- 用当前精确内层重算 \(P^\star\)；
- 与 JSON 中保存的 exact numerator/denominator 比较；
- 复算 assignment hash；
- 标记 solution 是否位于 `pareto_solutions`、是否为 recommendation。

不得仅根据 MainFunction 分组反推 Offset；不得使用展示 float 判断相等。

### 7.2 observed 指标

归档可比时输出：

- observed assignment 数；
- observed unique D vector 数；
- observed unique D histogram 数；
- observed unique \(P^\star\) level 数；
- observed Pareto histogram/level 数；
- 每个 observed histogram 的 archive 来源和 assignment hashes。

仅当可达直方图枚举为 `exact` 时计算：

\[
\text{histogram coverage}
=\frac{|\mathcal H_{\rm observed}|}
{|\mathcal H_{\rm reachable}|}.
\]

仅当完整 \(P^\star\) 水平已求出时计算：

\[
\text{P* level coverage}
=\frac{|P^\star_{\rm observed}|}
{|P^\star_{\rm reachable}|}.
\]

分数同时保存 numerator/denominator。若分母未知，字段为 `null`，并给
`coverage_status = "denominator_not_exact"`；禁止用理论上界伪造 coverage。

### 7.3 archive 不可证明的事项

即使 coverage 为 100%，它也只证明 D 直方图或 \(P^\star\) 水平覆盖，不证明：

- 每个 Offset assignment 已观察；
- 每个通信 \(Q^{ss}\) 水平已观察；
- 全局 Pareto frontier 已完整；
- recommendation 在完整空间中最优。

## 8. 输出格式

未来每网段生成：

```text
output/diagnostics/<network>/d_structure/
├── d_structure_messages.csv
├── reachable_histograms.csv
├── pstar_levels.csv
├── archive_comparison.csv
└── d_structure_summary.json
```

CSV 使用 UTF-8 with BOM (`utf-8-sig`)；JSON 使用 UTF-8、稳定 key 顺序及缩进。

### 8.1 `reachable_histograms.csv`

至少包含：

- `histogram_id`（由规范 tuple 的 SHA-256 派生，不使用运行序号作身份）；
- `histogram_tuple`
- `nonzero_histogram`
- `reachable_exact`
- `first_dp_layer_seen`
- `pstar_exact`
- `pstar_numerator`
- `pstar_denominator`
- `pstar_evaluated`
- `observed_in_archive`
- `observed_assignment_count`
- `pareto_observed`

若状态 capped，只允许落盘已确认可达的部分状态，并在每行及 summary 明确
`reachable_set_complete=false`。

### 8.2 `pstar_levels.csv`

每个精确水平一行：

- exact 分数三字段；
- 对应可达 histogram 数；
- 对应 observed histogram 数；
- 最小/最大已观察 Qss（仅 archive 事实）；
- 是否出现在 observed Pareto；
- 完整性状态。

### 8.3 `archive_comparison.csv`

每个 archive assignment 一行：

- network/source/stage/hash；
- Offset 合法性；
- D vector hash；
- histogram id；
- archived/recomputed \(P^\star\)；
- exact match；
- Qss、Peak；
- observed Pareto/recommended 标志；
- provenance comparability。

### 8.4 `d_structure_summary.json`

每网段至少输出：

- `network_id`
- `n`
- `decision_message_count`
- `fixed_message_count`
- `rho` exact fields
- `reachable_d_union`
- `r`
- `d_vector_count_exact`
- `product_reachable_d_counts`
- `product_divisor_counts`
- `stars_and_bars_upper_bound`
- `combined_histogram_upper_bound`
- `reachable_histogram_count`
- `reachable_histogram_lower_bound`
- `reachable_histogram_upper_bound`
- `reachable_pstar_level_count`
- `reachable_pstar_level_lower_bound`
- `reachable_pstar_level_upper_bound`
- `observed_histogram_count`
- `observed_pstar_level_count`
- exact coverage fractions或 `null`
- `structure_classification`
- `exactness_status`
- `state_cap_reached`
- `stop_reason`
- `stop_message_index`
- `input_sha256`
- `config_sha256`
- `eligible_set_sha256`
- `manifest_sha256`
- `archive_sha256`
- `commit_hash`
- `archive_source_commit`
- `provenance_comparable`
- cap、timeout、计数器和耗时。

大整数保持 JSON integer；分数保存 exact string、numerator 和 denominator。float
只可作为附加 display 字段，不能替代精确字段。

## 9. 完整性状态和失败关闭

### 9.1 `exactness_status`

只允许：

1. `exact`
   - 所有可达直方图完整枚举；
   - 所有直方图的 \(P^\star\) 已精确评价。
2. `bounded_only`
   - 只计算 \(\prod_i|\mathcal D_i|\)、约数上界、stars-and-bars 上界；
   - 未开始或按显式策略跳过状态枚举。
3. `capped`
   - histogram cap、P* evaluation cap 或 timeout 导致未完成。
4. `invalid_input`
   - 数学输入或 joint domain 前提不满足。

archive 不可比较不是数学输入无效；应单独报告
`archive_comparison_status=not_comparable`。

### 9.2 达到 histogram cap

实现按 message 层生成，发现第 `cap+1` 个不同状态时立即停止该层并记录：

- `state_cap_reached=true`
- `stop_reason=histogram_cap`
- `stop_message_index=i`
- 已确认不同状态数作为保守下界；
- `combined_histogram_upper_bound` 作为上界；
- 当前层是否完整为 false。

禁止：

- 把 cap 数写成完整可达数；
- 继续计算伪 coverage；
- 从部分状态断言 \(P^\star\) 只有一个水平；
- 丢弃停止层和上下界信息。

### 9.3 结构分类

只允许：

1. `fixed_d_vector`
   - 所有报文 \(|\mathcal D_i|=1\)；
   - 可严格推出全部 Offset 的 D 直方图相同、\(P^\star\) 恒定。
2. `proven_constant_pstar`
   - `exactness_status=exact`；
   - 完整可达直方图的精确 \(P^\star\) 水平数为 1。
3. `multiple_reachable_pstar_levels`
   - `exactness_status=exact`；
   - 精确水平数大于 1。
4. `incomplete_due_to_cap`
   - histogram、P* 或 timeout cap 使全空间未知。
5. `observed_single_level_only`
   - 只有 archive 观察事实或本次选择 `bounded_only`；
   - archive 中恰观察到一个 \(P^\star\) 水平；
   - 全部可达水平未知。

优先级：

- `fixed_d_vector` 可在不运行 histogram DP 时直接认定；
- 发生 cap 时用 `incomplete_due_to_cap`，不得被 observed 单水平覆盖；
- `observed_single_level_only` 仅用于没有更强 exact/cap 分类的纯观察口径。

只有 `fixed_d_vector` 和 `proven_constant_pstar` 允许输出：

> 软件目标在该实例全部合法 Offset 空间内退化为常数。

存在多个 \(P^\star\) 水平也不能推出完整 Pareto 前沿必有多个点，因为较高或较低
软件水平上的全部目标向量可能被其他水平支配。

## 10. 复杂度与状态爆炸风险

每报文 Dset 计算时间为

\[
O\left(\sum_i|A_i|\operatorname{poly}(\log T_i)\right).
\]

Histogram DP 第 i 层候选扩展至多
\(|\mathcal H_{i-1}||\mathcal D_i|\)，空间为去重后
\(|\mathcal H_i|q\) 个整数。最坏直方图数受

\[
\min\left\{\prod_i|\mathcal D_i|,
\binom{n+q-1}{q-1}\right\}
\]

约束，但两项仍可很大。每个完整直方图还触发一次关于其非零类型数 \(m_h\) 的
\(O(3^{m_h}\operatorname{poly}(|I|))\) 精确内层。

风险控制参数：

- `max_histogram_states`
- `max_exact_pstar_evaluations`
- `timeout_s`

实现应在每个 message 层和每次 P* 调用前检查单调时钟。cap 是结果语义的一部分，
不是日志警告。

为避免内存峰值：

- 每层只保留上一层和下一层；
- tuple 采用全局 R 的固定坐标；
- 稳定排序在去重后执行；
- CSV 可在最终 exact 时流式写；capped 时写明确 partial 标记；
- 不保留 Offset witness，除非未来另设有界、可选的单 witness 前驱。

## 11. 九网段分析口径

### 11.1 固定顺序与共同语义

顺序固定为：

```text
CH, DA, DK, EP, GL, IC, LC, PT, SU
```

所有网段必须使用同一 manifest 中锁定的：

- explicit sender；
- routing exclusion；
- CAN FD 协议范围；
- `frame_time_us` 权重口径（尽管本诊断不使用权重，仍用于 provenance 对齐）；
- Offset min/max/step；
- joint decision/fixed 规则；
- \(\rho\) 场景。

不得为某个网段单独缩小候选以让 exact 枚举通过；若触发 cap，诚实报告
`incomplete_due_to_cap`。

### 11.2 汇总表

未来另生成批量 summary（可由九个 JSON 汇总，不增加每网段事实）：

- n；
- \(R,r\)；
- \(\prod_i|\mathcal D_i|\)；
- stars-and-bars 及 combined upper bound；
- 精确/下界可达直方图数；
- 精确/下界 \(P^\star\) 水平数；
- archive observed histogram/level 数；
- coverage exact fractions；
- classification；
- exactness/cap/timeout；
- input/config/commit/archive hashes。

### 11.3 归档 provenance

当前最终 manifest 记录的实验源提交与本设计时 HEAD 不同。未来运行必须同时保存：

- 诊断运行 commit；
- archive source commit；
- archive source worktree status；
- 两者是否相同；
- 若不同，相关模型文件 hash 是否相同；
- 是否通过显式 comparability 检查。

即使数值碰巧一致，也不能省略提交差异。

## 12. 测试与验收方案

### 12.1 单元测试

1. **Dset/fiber**
   - \(T=12,A=\{2,3\}\Rightarrow Dset=\{2,3\}\)；
   - 验证非子格例；
   - offset 0、重复 gcd、候选稳定排序。
2. **Histogram DP oracle**
   - \(n\le6\) 时枚举完整 Dset 笛卡尔积聚合直方图；
   - 与 DP 集合逐 tuple 相等；
   - 输入 message 顺序规范化后输出稳定。
3. **P* cache**
   - 同直方图只调用生产精确内层一次；
   - exact Fraction、rho 和 cache key 隔离；
   - 与 `solve_main_function_partition()` materialized 结果相等。
4. **理论上界**
   - 实际 histogram 数不超过两个上界；
   - P* 水平数不超过 histogram 数。
5. **cap/fail closed**
   - histogram cap 在 `cap+1` 时停止；
   - P* cap、timeout、invalid input；
   - coverage 为 null，classification 不误报常数。
6. **archive**
   - assignment 完整性、合法 Offset、hash、exact P*；
   - 输入 hash 不同标记 `not_comparable`；
   - observed 单水平不升级为 proven constant。
7. **序列化**
   - CSV `utf-8-sig`；
   - JSON 大整数和 Fraction 往返无损；
   - 两次运行 byte-for-byte 稳定（时间字段除外时需单独规范）。

### 12.2 集成验收

在本地具备授权九网段输入时：

1. 只读加载 manifest 与九个项目；
2. 不修改输入 mtime/hash；
3. 逐网运行到 exact 或明确 cap；
4. 对 exact 小网段用独立 Offset/D-vector oracle 交叉；
5. 与当前 joint archive 重算全部 exact P*；
6. 校验输出中没有 DBC 原文或信号内容；
7. 校验 GCLS、推荐、baseline 文件 hash 前后相同；
8. `git status --short` 只出现预期未跟踪诊断输出，且该目录被忽略。

### 12.3 命令级验收

未来实现时至少运行：

```text
python -m pytest -q
python -m ruff check src tests
python -m mypy src
git diff --check
```

并为 `analyze-d-structure` 增加 `--help`、单网段、九网段、cap 和 invalid-input
端到端测试。本轮仅交付设计，不新增这些生产测试。

## 13. 不能据此作出的结论

无论诊断结果如何，均不得据此单独声称：

- 外层 Offset 搜索为 exact；
- observed Pareto front 为完整全局前沿；
- archive coverage 100% 意味着 assignment coverage 100%；
- 多个 \(P^\star\) 水平必然带来多点 Pareto 前沿；
- observed 单水平意味着全空间软件目标恒定；
- cap 前看到的状态数是完整状态数；
- stars-and-bars 中每个直方图都可达；
- 不同直方图必有不同 \(P^\star\)；
- 当前 \(\rho=1\) 是真实 ECU 标定值；
- D 类型压缩对报文特异成本、兼容性或容量扩展仍成立；
- 九网段的观测权衡已排除搜索遗漏；
- 诊断运行 commit 与旧 archive commit 可无条件比较；
- 该诊断构成算法新颖性或理论首创证据。

诊断只把“候选 Offset → 可达 D → 可达直方图 → 精确 \(P^\star\) 水平 → archive
观察覆盖”这一数据链透明化。所有超出这条链的结论必须另有证明或实验。
