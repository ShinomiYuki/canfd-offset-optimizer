# T1–T4 定向相关工作与新颖性审计

> 审计日期：2026-08-04
> 审计对象：[`theory_to_paper_mapping.md`](theory_to_paper_mapping.md) 所定义的 T1–T4
> 理论事实源：T1 对应[第 3–4 节](theory_extension_audit.md#3-带权离散-offset-峰值分配判定问题)，T2 对应[第 5–7 节](theory_extension_audit.md#5-周期调用分组问题的一般化定义)，T3 对应[第 8、10 节](theory_extension_audit.md#8-offset-到-d-结构的因子分解)，T4 对应[第 9 节](theory_extension_audit.md#9-通信均衡与软件代价的严格冲突构造)
> 性质：定向、可复核的 prior-art audit；不是系统综述，也不能证明世界范围内“绝无同构结果”。

## 1. 审计问题与裁决词表

本审计针对四个窄问题：

- **T1**：显式列出有限候选及命中列表的带权离散 Offset 峰值决策之 NP-completeness；
- **T2**：特定 identity-symmetric gcd 组成本下的 same-D 存在性，以及关于不同 D 类型数 `m` 的 FPT；
- **T3**：当前成本下 `P*(O)` 经 D 向量/直方图因子化及其可达结构；
- **T4**：两报文完整枚举给出的 `Qss`–`P*` 严格冲突。

每项只使用以下裁决词：

- `ESTABLISHED_BACKGROUND`
- `DIRECT_PRIOR_ART_FOUND`
- `CLOSE_PRIOR_ART_FOUND`
- `NO_ISOMORPHIC_RESULT_FOUND_IN_TARGETED_SEARCH`
- `UNRESOLVED`

“未发现同构结果”只说明本次检索范围和日期内没有定位到；它不是新颖性证明。

## 2. 检索范围、数据库与查询记录

### 2.1 检索站点

优先使用出版者或官方机构：IEEE Xplore/IEEE DOI、ACM Digital Library、ScienceDirect、SpringerLink、SIAM、INFORMS、Taylor & Francis、AUTOSAR 官方规范、SciTePress，以及作者/大学机构仓储用于获取合法全文。Crossref/DOI resolver、DBLP 与普通网页搜索只用于发现或核对元数据，不把 ResearchGate、聚合摘要或 AI 摘要作为最终证据。

### 2.2 代表性精确查询

以下查询在 2026-08-04 执行；大小写和标点差异不影响复查：

```text
CAN periodic message offset optimization peak load NP-hard phase assignment
"Efficient scheduling of periodic information monitoring requests"
"A note on Efficient scheduling of periodic information monitoring requests"
"Scheduling of Offset Free Systems" periodic offsets
"The peak load minimization problem in cyclic production"
"Replenishment Schedule to Minimize Peak Storage" weakly NP-hard
"Scheduling periodic messages on a shared link without buffering"
site:ieeexplore.ieee.org CAN offsets response time analysis Yomsi
"Pushing the Limits of CAN" offsets Grenier Havet Navet
AUTOSAR runnable task mapping offset gcd period
"A Novel Heuristic Algorithm for Mapping AUTOSAR Runnables to Tasks"
"Efficient mapping of runnables to tasks for embedded AUTOSAR applications"
AUTOSAR schedule table memory optimization periods offsets gcd
complete set partitioning inclusion exclusion 3^n dynamic programming
fixed parameter tractability scheduling number of types
symmetry integer programming interchangeable items aggregation
epsilon constraint multiobjective combinatorial optimization Pareto knee point
```

对进入核心表的 18 个 DOI 还分别执行了引号包围的精确查询（形式为 `"10.xxxx/..."`），核对返回的作者、题名、年份和载体；核对串为：

```text
10.1109/WFCS.2012.6242539
10.1023/A:1021782503695
10.1016/j.ejor.2005.01.057
10.1016/j.ejor.2009.03.011
10.1016/S0305-0548(00)00055-1
10.1287/opre.2018.1839
10.1007/s10951-024-00813-0
10.1109/TC.2017.2722443
10.1145/3431232
10.5220/0005234202390246
10.1016/j.sysarc.2020.101800
10.1145/3672608.3707710
10.1137/070683933
10.1016/j.artint.2015.09.006
10.1007/s10107-014-0830-9
10.1007/978-3-540-68279-0_17
10.1016/j.amc.2009.03.037
10.1080/0305215X.2010.548863
```

### 2.3 检索分区

| 分区 | 目的 |
|---|---|
| A. periodic phase/offset peak load | 找 T1 的直接或近似复杂度结果 |
| B. CAN/实时系统 Offset | 区分响应时间/可调度性与本文时隙峰值目标 |
| C. AUTOSAR runnable/MainFunction mapping | 审查 gcd、Offset、任务分组是否已有直接先例 |
| D. set partition/FPT/symmetry | 区分通用算法背景与 T2/T3 的特定结构 |
| E. multiobjective methods | 确认 `epsilon`-constraint、Pareto、膝点属于既有方法 |

## 3. 证据与可访问性规则

文献表的 `access_scope` 使用：

- `full_text`：实际取得出版者开放全文、官方规范、作者稿或机构稿；
- `publisher_preview`：出版者页面可见摘要之外的引言/模型片段，但没有取得完整正文；
- `abstract_only`：只核对出版者摘要、题录、DOI 和可见预览；
- `unverified`：无法从稳定来源核实。本文最终核心表中没有 `unverified` 项。

对于 `abstract_only`，只采用摘要明示的正面事实，不据此断言全文“没有”某定理。对“未发现同构结果”的判断同时依赖问题定义差异、可访问全文和多个相邻方向的交叉检索，并在第 11 节列为残余风险。

## 4. 模型同构判据

只有同时满足下列要点，才把来源视为 T1 的 direct/isomorphic prior art：

1. 决策变量是每个对象从有限离散 phase/Offset 候选中选择一个；
2. 输入显式列出有限时隙命中，而非仅以二进制编码周期隐式展开超周期；
3. 时隙负载是可加权的，目标或决策阈值是最大时隙负载；
4. 复杂度结论对应同一输入编码；
5. 限制子类足以覆盖 T1 所声明的受限结构。

T2/T3 的同构还要求组成本正是 `(rho+|G|)/gcd(D_i)` 或数学等价形式、message identity 不进入成本，并明确得到 same-D 整体最优解/按不同 D 类型数的算法/直方图充分性。只使用 gcd、Offset 或 subset DP 不算同构。

## 5. 总体裁决摘要

| 理论项 | 裁决 | 主要理由 | 入稿影响 |
|---|---|---|---|
| T1 | `CLOSE_PRIOR_ART_FOUND` | 周期 phase 峰值最小化与复杂度已有很接近结果；尤其 Zeng–Dror–Chen 与 Short。其隐式周期编码及复杂度层级与本文显式命中 NP 模型不同 | 保留窄定理，删除任何“首次周期峰值困难性”措辞 |
| T2 | `CLOSE_PRIOR_ART_FOUND` | AUTOSAR runnable 映射已明确使用 period/offset/gcd；通用 set partition 与按类型参数化是成熟背景。未定位到当前精确成本下 same-D 存在性 + `m`-FPT 的同构组合 | 贡献限定为“特定成本的结构定理与参数化精确算法” |
| T3 | `NO_ISOMORPHIC_RESULT_FOUND_IN_TARGETED_SEARCH` | gcd/offset 与对称聚合有相邻工作，但未定位到当前 `P*` 对 D 直方图充分性的同构结果 | 可以窄述因子化；必须承认 gcd 与 symmetry 背景，并保留检索限定 |
| T4 | `ESTABLISHED_BACKGROUND` | 多目标冲突、Pareto、`epsilon`-constraint 和 knee 均成熟；两报文符号枚举是本文模型的解释性见证，不宜包装成广泛新理论 | 作为建模动机/例证，不列为独立广泛方法创新 |

## 6. 核心文献证据表

本表共 **20** 项：9 项取得全文，1 项读取出版者扩展预览，10 项仅使用出版者摘要/元数据；0 项不可核验。18 个 DOI 均通过出版者、作者/机构题录或 DOI 精确检索逐一核对；PA-A01 无 DOI，PA-C01 为官方规范稳定 URL。

| ID | 文献（题名；年份；载体） | DOI / 稳定 URL | 模型或结论 | 与 T1–T4 的关系 | 新颖性威胁 | access_scope |
|---|---|---|---|---|---|---|
| PA-A01 | Grenier, Havet, Navet, *Pushing the Limits of CAN—Scheduling Frames with Offsets Provides a Major Performance Boost*；2008；ERTS | [author PDF](https://nicolas.navet.eu/publi/erts2008_offsets.pdf)；无 DOI | 为 CAN 报文选择 Offset，改善高负载下的时序/调度表现，含启发式配置 | CAN Offset 的直接领域背景；目标不是本文显式带权时隙峰值决策 | 高：禁止声称首先优化 CAN Offset；低于 T1 同构阈值 | `full_text` |
| PA-A02 | Yomsi, Bertrand, Navet, Davis, *Controller Area Network (CAN): Response Time Analysis with Offsets*；2012；WFCS | [10.1109/WFCS.2012.6242539](https://doi.org/10.1109/WFCS.2012.6242539) | 带 Offset 的 CAN response-time analysis | 直接支持 Offset 影响 CAN 时序；不以最大时隙带权释放量为目标 | 中：相关工作必须明确目标差异 | `abstract_only` |
| PA-A03 | Goossens, *Scheduling of Offset Free Systems*；2003；Real-Time Systems 24(2) | [10.1023/A:1021782503695](https://doi.org/10.1023/A:1021782503695) | 在周期实时系统中选择初始 Offset，研究等价类和精确/近似调度方法 | 与 phase assignment 变量接近；目标主要为可调度性 | 中高：禁止宽述“周期 Offset 选择此前未研究” | `abstract_only` |
| PA-A04 | Zeng, Dror, Chen, *Efficient Scheduling of Periodic Information Monitoring Requests*；2006；EJOR 173(2) | [10.1016/j.ejor.2005.01.057](https://doi.org/10.1016/j.ejor.2005.01.057) | 为周期请求选择起始时刻/phase 以最小化峰值负载，给出困难性与启发式 | 数学目标与 T1 最接近；周期由紧凑参数隐式表示，而非本文显式 hit-list 输入 | **重大**：足以否定“首次周期 phase 峰值困难性” | `abstract_only` |
| PA-A05 | Short, *A Note on “Efficient Scheduling of Periodic Information Monitoring Requests”*；2010；EJOR 201(1) | [10.1016/j.ejor.2009.03.011](https://doi.org/10.1016/j.ejor.2009.03.011) | 修正隐式 periodic monitoring 问题的复杂度：验证本身涉及超周期/同余结构，结论高于普通 NP-completeness | 直接说明**输入表示会改变复杂度类**；支持 T1 必须突出显式命中表示 | **重大**：若省略表示差异，T1 会与既有结果冲突或显得错误 | `abstract_only` |
| PA-A06 | Yao, *The Peak Load Minimization Problem in Cyclic Production*；2001；Computers & OR 28(14) | [10.1016/S0305-0548(00)00055-1](https://doi.org/10.1016/S0305-0548(00)00055-1) | 周期生产 phase 排程最小化规划期峰值，提出 greedy + smoothing heuristic | 目标形式相近、应用不同；不直接给出本文显式二候选/两时隙定理 | 中：扩大“周期峰值”文献背景 | `abstract_only` |
| PA-A07 | Hochbaum, Rao, *The Replenishment Schedule to Minimize Peak Storage Problem*；2019；Operations Research 67(5) | [10.1287/opre.2018.1839](https://doi.org/10.1287/opre.2018.1839)；[author manuscript](https://hochbaum.ieor.berkeley.edu/html/pub/RSP-opre.2018.1839-online.pdf) | 离散周期补货 phase 最小化峰值存储；固定 joint cycle 弱 NP-hard，非固定时强 NP-hard，并给算法/近似 | 说明 phase-peak 类问题的强弱困难性依赖编码/周期条件 | 中高：T1 只能声称自身限制类的 weak numeric hardness | `full_text` |
| PA-A08 | Guiraud, Strozecki, *Scheduling Periodic Messages on a Shared Link without Buffering*；2024；Journal of Scheduling 27(5) | [10.1007/s10951-024-00813-0](https://doi.org/10.1007/s10951-024-00813-0) | 周期消息在共享链路上做 collision-free phase scheduling，讨论低负载多项式算法 | 直接通信场景但可行性目标不同，不是软峰值最小化 | 中：用于划清 collision-free scheduling 与 release shaping | `abstract_only` |
| PA-B01 | Minaeva, Akesson, Hanzálek, Dasari, *Time-Triggered Co-Scheduling of Computation and Communication with Jitter Requirements*；2018；IEEE TC 67(1) | [10.1109/TC.2017.2722443](https://doi.org/10.1109/TC.2017.2722443) | 联合任务/消息的 time-triggered 调度，精确模型处理小实例、启发式处理较大实例 | CAN–CPU 协同调度背景；目标为调度/抖动，不是本文 MainFunction 代理 | 高：禁止声称首先联合计算与通信 Offset | `full_text` |
| PA-B02 | Minaeva, Hanzálek, *Survey on Periodic Scheduling for Time-triggered Hard Real-time Systems*；2021；ACM CSUR 54(1) | [10.1145/3431232](https://doi.org/10.1145/3431232) | 系统整理 periodic scheduling 模型、复杂度与求解方法 | 周期 phase/offset 调度的领域背景和术语来源 | 中：要求准确定位而非制造空白 | `full_text` |
| PA-C01 | AUTOSAR, *Specification of Communication*；R25-11；Classic Platform Document ID 15 | [official PDF](https://www.autosar.org/fileadmin/standards/R25-11/CP/AUTOSAR_CP_SWS_COM.pdf) | 定义 `Com_MainFunctionTx`、`ComMainTxTimeBase` 等配置语义 | 软件侧对象的规范依据；不是优化或复杂度结果 | 高：规范语义必须引用，模型解释不得超出标准 | `full_text` |
| PA-C02 | Khenfri, Chaaban, Chetto, *A Novel Heuristic Algorithm for Mapping AUTOSAR Runnables to Tasks*；2015；PECCS | [10.5220/0005234202390246](https://doi.org/10.5220/0005234202390246)；[publisher PDF](https://www.scitepress.org/papers/2015/52342/52342.pdf) | 利用 activation Offset 等性质把不同周期 runnable 映射到任务，减少任务数并保持可调度性 | 与 T2 的 Offset/gcd/task grouping 很接近，但目标、成本和算法不同 | **重大**：禁止声称首先利用 Offset 进行 AUTOSAR 分组 | `full_text` |
| PA-C03 | Khenfri, Chaaban, Chetto, *Efficient Mapping of Runnables to Tasks for Embedded AUTOSAR Applications*；2020；JSA 110 | [10.1016/j.sysarc.2020.101800](https://doi.org/10.1016/j.sysarc.2020.101800) | runnable-to-task 映射；任务周期由 runnable periods/offsets 的 gcd 约束，比较多种 heuristic mapping | 与 T2/T3 的 gcd 结构最接近；未见当前 `(rho+|G|)/gcd` 成本、same-D 定理或直方图充分性 | **重大**：相关工作必须逐项对比，不可仅引 AUTOSAR COM 规范 | `publisher_preview` |
| PA-C04 | Ahmad, Pestana, Krisper, Baunach, *A Scalable Approach for Memory Optimization in AUTOSAR Schedule Tables*；2025；ACM SAC | [10.1145/3672608.3707710](https://doi.org/10.1145/3672608.3707710) | 周期、Offset 和 gcd 影响 schedule-table/task 周期与内存；提出可扩展优化 | 说明近期 AUTOSAR 工作持续利用 offset/gcd 结构；成本是内存而非本文 CPU proxy | 中高：削弱“gcd 软件结构未被研究”的表述 | `full_text` |
| PA-D01 | Björklund, Husfeldt, Koivisto, *Set Partitioning via Inclusion–Exclusion*；2009；SIAM J. Computing 39(2) | [10.1137/070683933](https://doi.org/10.1137/070683933) | 通用 set partitioning 及加权变体的指数算法，给出 `2^n`/`3^n` 量级算法背景 | T2 subset partition DP 的直接通用算法背景 | 高：`O(3^m)` 或 subset DP 本身不能声称首创 | `full_text` |
| PA-D02 | Michalak, Rahwan, Elkind, Wooldridge, Jennings, *A Hybrid Exact Algorithm for Complete Set Partitioning*；2016；Artificial Intelligence 230 | [10.1016/j.artint.2015.09.006](https://doi.org/10.1016/j.artint.2015.09.006)；[author PDF](https://www.cs.ox.ac.uk/people/michael.wooldridge/pubs/aij2016a.pdf) | complete set partitioning 的精确算法和组合搜索 | 说明无序集合划分精确求解是成熟方向 | 中：T2 新意必须落在成本结构和类型压缩 | `full_text` |
| PA-D03 | Mnich, Wiese, *Scheduling and Fixed-Parameter Tractability*；2015；Mathematical Programming 154 | [10.1007/s10107-014-0830-9](https://doi.org/10.1007/s10107-014-0830-9) | 讨论 scheduling 中按数值/类型等参数的 FPT 算法 | T2-b 的参数化复杂度背景 | 中：不能把“按类型数 FPT”作为无先例范式；可主张特定模型实例化 | `abstract_only` |
| PA-D04 | Margot, *Symmetry in Integer Linear Programming*；2010；*50 Years of Integer Programming* | [10.1007/978-3-540-68279-0_17](https://doi.org/10.1007/978-3-540-68279-0_17) | 讨论整数规划中对称对象和 symmetry handling | T2/T3 的 identity symmetry 属于成熟通用思想 | 中：直方图压缩需强调由当前成本导出，而非声称发现“对称性” | `abstract_only` |
| PA-E01 | Mavrotas, *Effective Implementation of the ε-Constraint Method in Multi-Objective Mathematical Programming Problems*；2009；Applied Mathematics and Computation 213(2) | [10.1016/j.amc.2009.03.037](https://doi.org/10.1016/j.amc.2009.03.037) | `epsilon`-constraint 的有效实现与 Pareto 方案生成 | T4 之后采用的方法背景 | 高：`epsilon`-constraint 不是本文方法创新 | `abstract_only` |
| PA-E02 | Deb, Gupta, *Understanding Knee Points in Bicriteria Problems and Their Implications as Preferred Solution Principles*；2011；Engineering Optimization 43(11) | [10.1080/0305215X.2010.548863](https://doi.org/10.1080/0305215X.2010.548863) | 双目标 knee point 的解释和偏好意义 | 几何膝点的直接背景 | 高：膝点只作后处理，不得称唯一最优或理论贡献 | `abstract_only` |

### 6.1 逐篇分类记录

下列两张表与上表通过 `reference_id` 联合构成附件要求的逐篇记录。“primary=yes”表示题录和结论来自出版者、规范组织或作者/机构正式页面；不等于已读全文，全文范围仍以上表 `access_scope` 为准。

| reference_id | source_type | primary_source_verified | problem | variables | objective | constraints |
|---|---|---|---|---|---|---|
| PA-A01 | conference | yes | CAN Offset 配置 | 每帧 Offset | 改善 WCRT/可调度表现 | 固定优先级 CAN、周期帧 |
| PA-A02 | conference | yes | 带 Offset 的 CAN RTA | 已知 Offset/相位关系 | 计算响应时间界 | 非抢占 CAN 仲裁 |
| PA-A03 | journal | yes | offset-free periodic scheduling | 周期任务初始 Offset | 获得可调度配置 | 严格周期/资源约束 |
| PA-A04 | journal | yes | periodic monitoring peak load | 每请求起始 phase | 最小化最大并发/负载 | 周期隐式编码、重复请求 |
| PA-A05 | journal note | yes | 纠正 PA-A04 复杂度 | 同 PA-A04 | 判定峰值可行性 | 隐式 hyperperiod 与 congruence |
| PA-A06 | journal | yes | cyclic production peak load | 周期生产相位/安排 | 最小化 basic-period 峰值 | 周期频率与生产时长 |
| PA-A07 | journal | yes | discrete replenishment peak storage | 各物品补货 phase | 最小化峰值库存容量 | 周期/联合周期，离散时间 |
| PA-A08 | journal | yes | shared-link periodic messages | 消息 phase | 无缓冲、无冲突可调度 | 固定周期/大小、共享链路 |
| PA-B01 | journal | yes | 计算与通信协同 time-triggered scheduling | 任务/消息开始时刻 | 满足时序并控制 jitter | 资源互斥、precedence、deadline |
| PA-B02 | survey | yes | periodic hard-real-time scheduling 分类 | 不适用 | 综述复杂度与算法 | 多种资源环境 |
| PA-C01 | standard | yes | AUTOSAR COM 配置语义 | COM 配置参数 | 规定一致行为 | Classic Platform 规范 |
| PA-C02 | conference | yes | AUTOSAR runnable-to-task mapping | runnable 分组与 Offset | 减少任务并保持可调度 | 单核、固定优先级、周期 runnable |
| PA-C03 | journal | yes | AUTOSAR runnable mapping | runnable 分组/任务周期 | 任务数、响应时间、可调度性 | period/offset/gcd 兼容关系 |
| PA-C04 | conference | yes | AUTOSAR schedule-table memory | task grouping/table schedule | 降低内存并保持可调度 | periods、offsets、gcd |
| PA-D01 | journal | yes | weighted set partitioning | 集合划分 | 优化分组权值和 | 任意子集权值 |
| PA-D02 | journal | yes | complete set partitioning | coalition/子集划分 | 最大化子集价值和 | 每元素恰属一组 |
| PA-D03 | journal | yes | scheduling FPT 范式 | 依具体调度问题 | exact/近似求解 | 参数为少量数值/类型等 |
| PA-D04 | book chapter | yes | ILP symmetry | 对称变量/轨道 | 减少对称搜索 | 整数线性约束 |
| PA-E01 | journal | yes | 多目标数学规划 | 目标预算与决策向量 | 生成有效解/Pareto 集 | `epsilon` 预算 |
| PA-E02 | journal | yes | 双目标 knee 识别 | 非支配解 | 识别偏好折中点 | 双目标前沿几何 |

| reference_id | complexity_result | algorithm | guarantee | relation_to_ours | affected_claim | novelty_threat | usable_citation | notes |
|---|---|---|---|---|---|---|---|---|
| PA-A01 | 未作为本审计复杂度证据 | CAN Offset heuristic | heuristic | close | T1 | major | yes | 相同领域变量，不同目标 |
| PA-A02 | 无本审计所需 hardness | Offset-aware RTA | analysis bound | background | T1 | minor | yes | 只支持时序分析背景 |
| PA-A03 | 题录明示 exact/near-optimal 方法 | 等价类与搜索 | exact/approx（按原文条件） | close | T1 | major | yes | 取得全文前不细化复杂度 |
| PA-A04 | 原文困难性被 PA-A05 修正 | scheduling heuristics | heuristic | close | T1 | blocking | yes | 数学目标最近；编码不同 |
| PA-A05 | 隐式模型为 `Sigma_2^p`-complete；验证 strong coNP-complete | 复杂度修正 | complexity classification | close | T1 | blocking | yes | 证明输入表示不可省略 |
| PA-A06 | 摘要称问题极难；不据此采用精确复杂度类 | greedy + smoothing | heuristic | close | T1/T4 | major | yes | 周期生产应用 |
| PA-A07 | 固定 joint cycle 弱 NP-hard；非固定强 NP-hard；含 pseudo-poly/FPTAS/PTAS | DP/approximation schemes | exact restricted/approx | close | T1 | major | yes | 强弱困难性依条件变化 |
| PA-A08 | 摘要/全文给特定低负载多项式结果 | 构造调度算法 | exact under conditions | close | T1 | minor | yes | collision-free，不是 peak minimization |
| PA-B01 | 使用精确模型与 scalable heuristic | ILP/SMT/heuristic | exact small/heuristic large | close | T1/T4 | major | yes | 联合计算通信并非空白 |
| PA-B02 | 汇总多项式/困难 periodic scheduling 类别 | survey + SMT examples | background | background | T1/T2 | minor | yes | 术语与领域定位 |
| PA-C01 | 不适用 | 规范性行为 | standard | background | T2/T3 | major | yes | 语义依据，不是算法 |
| PA-C02 | 未主张本文同构复杂度 | runnable mapping heuristic | heuristic | close | T2/T3 | major | yes | 已用 activation Offset 分组 |
| PA-C03 | 未见当前 same-D/FPT 结论 | 多种 mapping heuristics | heuristic | close | T2/T3 | blocking | yes | gcd/offset 最接近的软件先例 |
| PA-C04 | 未作为 hardness 证据 | scalable memory optimization | optimization/heuristic | close | T2/T3 | major | yes | 成本不同（内存） |
| PA-D01 | 给出 set partitioning 的 `2^n`/`3^n` 指数算法背景 | inclusion–exclusion/DP | exact | background | T2 | major | yes | generic DP 非新颖点 |
| PA-D02 | complete set partition exact 搜索 | ODP-IP hybrid | exact | background | T2 | major | yes | 无序划分成熟 |
| PA-D03 | 多个 scheduling FPT 结果 | 参数化算法 | FPT（按各模型） | background | T2 | major | yes | “按类型数”是一般范式 |
| PA-D04 | 不适用统一复杂度 | symmetry breaking | exact search acceleration | background | T2/T3 | minor | yes | 对称性是通用背景 |
| PA-E01 | 不适用 | augmented `epsilon`-constraint | Pareto generation（按模型） | background | T4 | major | yes | 方法本身非贡献 |
| PA-E02 | 不适用 | knee analysis | interpretive | background | T4 | major | yes | knee 不是唯一最优证书 |

## 7. 分区分析

### 7.1 A/B：周期 phase 与 CAN Offset

PA-A04 与 PA-A05 是 T1 的首要威胁。二者研究“为周期请求选择起始相位以最小化峰值负载”，与本文抽象目标高度接近；Short 还明确表明，如果周期以紧凑数值编码、验证需要处理隐式超周期，则复杂度并非普通 NP-completeness。T1 的可保留差异因此不是应用名“CAN”，而是**显式有限 hit list 的输入表示、受限二候选/二时隙结构和该表示下的证书验证**。

PA-A01/A02/A03/B01/B02 则否定更宽的领域空白叙事：CAN Offset、周期 Offset assignment、任务消息联合调度均已有大量工作。本文可以比较目标函数和软件代理，但不能把变量或协同思想本身当作首次。

### 7.2 C：AUTOSAR runnable 与 gcd/offset

PA-C02/C03 是 T2/T3 的关键 close prior art。它们已经使用 runnable 的 period、activation offset 和 task mapping，且 PA-C03 的题录/摘要明确出现 gcd 决定任务周期的结构。本文差异必须写成：

- 研究对象是本文定义的 MainFunction 分组代理，而不是一般 runnable schedulability/任务数；
- 组成本含固定调用相对成本 `rho` 与组内数量；
- same-D 结论是“至少存在一个”结构化最优解；
- 精确算法参数是不同 D 类型数；
- T3 的充分统计量和 exact reachable-level audit 是该特定成本的推论。

这些差异足以避免“直接重复”的裁决，但不能支撑“此前没有 Offset–软件周期耦合”这种宽泛句子。

### 7.3 D：集合划分、FPT 与对称性

PA-D01/D02 说明集合划分和 `3^n` 量级 exact algorithms 是 established algorithmic background；PA-D03/D04 说明以类型数参数化和利用可互换对象对称性也是成熟范式。因此 T2 的贡献不是 DP 模板，而是当前 gcd 成本下的交换性质使报文级最优解可无损压缩为类型级实例，再把通用精确枚举应用于 `m` 个类型。

### 7.4 E：多目标方法

PA-E01/E02 足以把 `epsilon`-constraint 和膝点归入 established background。T4 的价值是给当前模型一个严格、最小、完整枚举的冲突见证，从而排除“两个目标总能同时改善”的潜在误解；它不是新的 Pareto 理论或新的 `epsilon`-constraint 方法。

## 8. T1–T4 逐项新颖性裁决

### 8.1 T1 — `CLOSE_PRIOR_ART_FOUND`

本文命题边界以冻结审计的 [T1 问题定义与 NP-completeness 审计](theory_extension_audit.md#3-带权离散-offset-峰值分配判定问题) 为准。

**为何不是 `DIRECT_PRIOR_ART_FOUND`**：本次未找到同时采用显式有限候选 hit lists、任意整数权重、二候选/二时隙受限结构，并在该表示下给出同一 NP-completeness 定理的来源。PA-A04/A05 的 periodic monitoring 表示更紧凑，验证复杂度受隐式 hyperperiod/congruence 影响。

**为何威胁仍重大**：目标“选择周期 phase 最小化峰值”已经直接存在，且已有复杂度争论。若论文省略“explicit hit-list representation”，T1 会显得重复或与既有复杂度类冲突。

**允许措辞**：

> 对本文显式列出有限 Offset 候选及稳态命中列表的 EWDOPD 表示，我们给出一个二候选、二时隙受限特例的 NP-completeness 证明。该结果与隐式周期 monitoring 的已知复杂度结果在输入表示上不同。

### 8.2 T2 — `CLOSE_PRIOR_ART_FOUND`

本文命题边界以冻结审计的 [T2 same-D 与 FPT 结果](theory_extension_audit.md#5-周期调用分组问题的一般化定义) 为准。

**相近来源**：PA-C02/C03 已把 Offset/gcd 用于 AUTOSAR runnable grouping；PA-D01/D02 是 generic set partition；PA-D03/D04 是 FPT/symmetry 背景。

**未定位到的同构组合**：当前 `(rho+|G|)/gcd` 成本、same-D 不拆分的存在性定理、带重数类型压缩、规范锚点 DP 及参数 `m` 的 FPT 作为一个完整结果。

**允许措辞**：

> 针对本文 identity-symmetric 线性组成本，我们证明至少存在一个不拆分相同 D 类型的最优解，并据此得到关于不同 D 类型数 `m` 的 `O(3^m poly(|I|))` 精确算法。

不得写“首次使用 gcd 对 AUTOSAR runnable/MainFunction 分组”或“提出新的通用 set partition DP”。

### 8.3 T3 — `NO_ISOMORPHIC_RESULT_FOUND_IN_TARGETED_SEARCH`

本文命题边界以冻结审计的 [T3 Offset–D 因子分解](theory_extension_audit.md#8-offset-到-d-结构的因子分解) 为准。

检索发现 gcd/offset 任务周期关系、对象对称压缩和周期类型参数化背景，但没有定位到对本文 `P*` 代理值的 D 直方图充分统计量、reachable histogram exact enumeration 及 `P*` level 分类完全同构的结果。

**允许措辞**：

> 在本文成本模型和独立有限候选域下，`P*` 经 D 直方图因子化；据此可精确枚举可达直方图并分类软件目标水平。本次定向检索未发现该特定因子化与诊断组合的同构结果。

该措辞不得缩写为“首次发现 Offset 的 gcd 结构”。

### 8.4 T4 — `ESTABLISHED_BACKGROUND`

本文命题边界以冻结审计的 [T4 严格冲突构造](theory_extension_audit.md#9-通信均衡与软件代价的严格冲突构造) 为准。

多目标冲突的概念、Pareto 支配、`epsilon`-constraint 与 knee 后处理均已建立。两报文实例是当前模型内部的严格见证，可以作为 proposition/example；若把它列为独立广泛理论创新，会被认为把标准事实重新包装。

**允许措辞**：

> 一个完整符号枚举的两报文实例表明，当前 `Qss` 与 `P*` 不具有一般单调一致性，从而为采用既有 `epsilon`-constraint/Pareto 工具组织候选提供模型内动机。

## 9. 对论文相关工作与贡献列表的直接修改要求

### 9.1 必须加入的近邻

1. PA-A04/A05：周期 monitoring phase peak 与表示敏感的复杂度；
2. PA-A03/A01/A02：周期 Offset 与 CAN Offset/WCRT；
3. PA-C02/C03：AUTOSAR runnable grouping 的 Offset/gcd；
4. PA-D01/D03/D04：generic set partition、FPT、symmetry；
5. PA-E01/E02：标准多目标工具。

### 9.2 应删除或收窄的当前表达

当前 `paper/main.tex` 约 135 行的“尚未形成……统一建模与求解框架”应删除或改为可比对象陈述，例如：

> 与以响应时间/可调度性为目标的 CAN Offset 研究、以任务数/可调度性为目标的 AUTOSAR runnable 映射以及一般周期峰值调度相比，本文限定在显式有限 Offset 候选上，同时评价带权释放时隙与特定 identity-symmetric MainFunction 代理成本，并区分固定 Offset 的精确内层与有限外层候选覆盖。

### 9.3 安全贡献总表

| 项 | 可作为主要贡献？ | 安全定位 |
|---|---|---|
| CAN Offset 作为决策变量 | 否 | established background |
| 周期 phase 峰值最小化 | 否 | close/direct application background |
| T1 特定显式表示受限定理 | 是，需窄述 | model-specific complexity result |
| gcd/Offset 决定软件周期 | 否 | AUTOSAR 规范与 close prior art |
| T2 same-D 结构定理 | 是，需限定成本 | model-specific structural result |
| generic subset DP / `3^m` | 否 | established algorithmic background |
| T2 关于 `m` 的 FPT 实例化 | 可作为 T2 的一部分 | parameterized consequence of compression |
| T3 D 直方图充分性与 exact audit | 是，需检索限定 | model-specific factorization/diagnostic |
| Pareto/`epsilon`/knee | 否 | established background |
| T4 两报文见证 | 作为理论动机，不宜单列广泛创新 | model-specific counterexample |
| 九网段完整 D 枚举 | 是，作为实证/诊断 | exact structural evidence, not joint optimality |

### 9.4 可直接使用与禁止使用的新颖性句式

**可直接使用（仍需保留引用）**：

1. “本文针对所建立的显式带权离散 Offset 峰值分配模型，给出受限特例下的 NP-completeness/优化 NP-hardness 证明。”
2. “固定 Offset 后，本文利用当前 gcd 型组成本的结构性质，将报文级划分压缩为 D 类型级划分，并得到关于不同 D 类型数 `m` 的 FPT 精确求解方法。”
3. “本文证明当前身份对称软件代理成本仅依赖 D 直方图，并据此分析可达软件代价水平。”
4. “本文通过完整枚举的两报文构造说明通信均衡目标与软件代理成本在一般模型中并非天然同向。”
5. “在本次定向检索范围内，未发现与当前 gcd 成本、same-D 压缩和 D 直方图充分性完全同构的结果。”

**禁止作为论文结论使用**：

1. “本文首次/首创周期 Offset 峰值优化或其困难性证明。”
2. “以往没有研究 CAN Offset、AUTOSAR Offset/gcd 分组或计算—通信协同调度。”
3. “本文提出首个通用 `O(3^m)` 集合划分/FPT 算法。”
4. “NP-hardness 表明只能使用启发式或精确算法不可行。”
5. “未发现同构文献，因此证明本文结果前所未有。”
6. “`epsilon`-constraint、Pareto 支配或 knee-point 是本文原创方法。”

## 10. 被排除或降级的近似命中

以下材料曾出现在检索结果中，但没有进入 20 项核心证据或被降级：

| 类别 | 处理 | 原因 |
|---|---|---|
| 普通 load balancing / job scheduling | 排除 | 没有周期 phase/Offset 变量或 gcd 软件结构 |
| 无缓冲 collision-free periodic link 的更多论文 | 只保留 PA-A08 | 可行性/碰撞目标与软峰值目标不同，继续扩展不会改变裁决 |
| 仅讨论 CAN WCRT、jitter 的大量后续论文 | 由 PA-A01/A02/B01/B02 代表 | 它们证明领域成熟，但不是 T1/T2 同构来源 |
| AUTOSAR RTE/COM 的历史版本 | 以 PA-C01 当前官方规范代表 | 规范版本用于语义，不用于新颖性定理 |
| 2026 年在线先行的 automotive cause–effect chain 优化论文 | 降级为候选，不纳入核心表 | 虽含 gcd(period, offset) 线索，但正式卷期尚未来到且对 T2 裁决非必要；后续投稿前应复核最终版本 |
| ResearchGate、Semantic Scholar、聚合站摘要 | 排除为证据 | 仅用于发现，稳定性和版本权威性不足 |
| 专利、学位论文、非英文区域数据库 | 本轮未系统覆盖 | 构成第 11 节残余检索风险 |

## 11. 未解决的新颖性风险与后续检索

1. **T1 编码等价风险**：可能存在把显式 hit-list 称为 cyclic load balancing、periodic event scheduling 或 matrix balancing 的同构结果，而标题不含 Offset。投稿前应做一次数学式/引文追踪，重点查 PA-A04/A05 的引用与被引网络。
2. **T2 交换定理风险**：AUTOSAR 或 complete set partition 文献中可能在更一般可分组成本下已有“不拆分等类型对象”的 dominance lemma。应检索 `identical types unsplittable optimal partition gcd cost` 及 PA-C03 全文参考文献。
3. **T3 充分统计量风险**：直方图因子化可能作为匿名 symmetry reduction 工程技巧出现，未在标题/摘要中表述为 theorem。需要全文级检索 source code、supplement 与专利。
4. **非英语和工业文献**：本次主要覆盖英文同行评审与官方规范，没有系统审计德文汽车软件论文、企业白皮书、专利和封闭标准资料。
5. **最新文献窗口**：审计截止 2026-08-04；正式投稿、返修和答辩前均应做增量检索。
6. **摘要访问限制**：11 项只核对摘要/元数据，不能用“摘要未提及”证明全文不存在同构定理；如将 T1/T2/T3 写成高强度 novelty claim，应先取得并全文阅读 PA-A03/A04/A05/C03/D02/D03/D04。

若上述任何搜索找到完全同构结果，裁决必须升级为 `DIRECT_PRIOR_ART_FOUND`，相应项从“新理论贡献”降为“针对当前 CAN–MainFunction 模型的实例化、验证或工程集成”。

## 12. 可直接用于论文的相关工作组织

建议相关工作改为四段而非按通信/软件简单二分：

1. **周期 phase/Offset 与峰值/可调度性**：PA-A01–A08，突出目标和输入表示差异；
2. **计算—通信协同与 AUTOSAR 软件映射**：PA-B01/B02、PA-C01–C04，正面承认 Offset/gcd 先例；
3. **集合划分、对称性与参数化算法**：PA-D01–D04，把算法模板置于通用背景；
4. **多目标候选组织**：PA-E01/E02，把方法新颖性让位于特定模型与证据边界。

每段最后只写“本文具体不同点”，不写“已有研究尚未……/首次……”。

## 13. 审计结论

本次定向检索没有找到 T1–T3 与当前全部定义、输入编码和成本函数完全同构的单一来源，但找到了足以显著收窄贡献的近邻：T1 的周期 phase 峰值复杂度，T2/T3 的 AUTOSAR Offset/gcd runnable 映射，以及通用 set partition/FPT/symmetry。T4 所使用的多目标方法属于 established background。

因此，最稳健的论文定位不是“首次统一解决 CAN Offset 与软件周期”，而是：

> 在一个明确限定的 CAN 释放—MainFunction 代理模型中，给出表示敏感的困难性结果、成本特定的 same-D 压缩与参数化精确内层、D 直方图因子化诊断，以及严格冲突见证；再以九网段 exact 结构枚举和有限预算 observed front 分别验证结构空间与搜索行为。

对应的章节、页数、前提和禁止表述见 [`theory_to_paper_mapping.md`](theory_to_paper_mapping.md)。
