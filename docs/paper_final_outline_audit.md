# 最终论文目录与旧稿迁移审计

> 文档性质：最终论文结构、旧稿迁移和实验依赖的唯一规划依据，不含论文正文。  
> 审计基线：`main@80b9ae3`。状态只反映当前证据是否足以动笔，不代表章节重要性。

## 1. 审计原则与题目评估

### 1.1 四类状态的执行口径

- **【可直接写】**：模型、算法或证明边界已稳定；可以重写措辞，但无需等待新实验决定核心内容。
- **【需要重写】**：主题保留，旧稿的定义、范围、叙事或强度已过时；必须依据当前 source/tests/docs 重建。
- **【等最终九网段数据】**：实验方法可先确定，但数字、图表或总体结论必须等当前 HEAD、统一输入口径和完整 manifest 的九网结果。
- **【应从旧稿删除】**：旧内容错误、失去证据、偏离研究主线或属于开发/GUI 操作说明，不迁入正文。

“当前实现存在”不自动获得论文席位；“old-1/old-2 已写好”也不自动获得迁移资格。

### 1.2 暂定题目是否仍适合

暂定题目《一种离散时隙上的周期报文 Offset 均衡分配方法》仍能覆盖前半部分 CAN 问题，但不能直接表达后半部分的 MainFunction exact subproblem 与 CAN–CPU tradeoff。现阶段**不改最终标题**，后续可在摘要与副标题层面评估两种方案：

1. 保留现题，把 MainFunction/CPU 写成“Offset 工程代价与联合扩展”，强调统一主线；
2. 若九网段 joint 结果足够强，再评估是否在标题中加入“CAN–CPU 协同”。

在 joint 九网数据未到位前，不应为扩大题目而扩大结论。

### 1.3 最大结构调整及理由

1. 将 `old-1` 的 CAN-only 叙事与 `old-2` 的 CPU 叙事合并为一个因果链，而不是前后拼接两篇稿。
2. 把 Offset–MainFunction 耦合前置到系统模型末尾，先回答“为什么 CAN 最优的 Offset 不是免费变量”。
3. 用当前 \(Q_{\rm ss}\)、Peak guardrail 和三种 objective modes 重建优化模型，删除旧绝对偏差 \(D\)。
4. 将 exact inner solver 与 heuristic outer GCLS 明确分层，杜绝“联合方法 exact”的误读。
5. 把 observed Pareto、refinement、stability 和 knee 放入同一证据链；结果节按 research question 组织，而不是按开发期实验产生顺序堆放。

## 2. 建议最终目录与状态

以下目录中的每个章、节和三级小节均已标记状态。状态不同的内容被拆开，避免用一个标签掩盖“方法可写、结果待数据”。

- **1 引言【需要重写】**
  - **1.1 周期通信中的局部释放聚集问题【需要重写】**
  - **1.2 从 CAN 均衡到软件调度代价的研究问题【需要重写】**
  - **1.3 研究贡献与证据边界【需要重写】**
  - **1.4 相关研究方向与本文定位【需要重写】**
    - **1.4.1 CAN schedulability、offset assignment 与 load shaping【需要重写】**
    - **1.4.2 AUTOSAR COM timing 与周期任务分组【需要重写】**
    - **1.4.3 多目标 heuristic 与 ε-constraint【需要重写】**
  - **1.5 论文结构【可直接写】**
- **2 问题描述与系统模型【需要重写】**
  - **2.1 周期报文与释放模型【可直接写】**
    - **2.1.1 周期、Offset 与释放序列【可直接写】**
    - **2.1.2 Offset 不改变长期平均释放率【可直接写】**
  - **2.2 离散 Offset、slot 与评价窗口【可直接写】**
    - **2.2.1 候选集合与对齐约束【需要重写】**
    - **2.2.2 启动窗口、稳态窗口与超周期【可直接写】**
  - **2.3 输入边界与 eligible message【需要重写】**
    - **2.3.1 周期 TX、显式 sender selection 与网络归属【需要重写】**
    - **2.3.2 基于目标网段与 CAN ID 的 routing exclusion【需要重写】**
    - **2.3.3 CAN/CAN FD 模型兼容、主实验协议口径与 fail-closed 规则【需要重写】**
  - **2.4 CAN 释放负载评价【需要重写】**
    - **2.4.1 frame-time、payload 与 unit 权重【需要重写】**
    - **2.4.2 Peak、超限量与 \(Q_{\rm ss}\)【可直接写】**
    - **2.4.3 conservative occupancy 的诊断边界【需要重写】**
  - **2.5 Offset 与软件周期调度粒度的耦合【可直接写】**
- **3 周期报文 Offset 均衡优化模型【需要重写】**
  - **3.1 决策变量、fixed message 与约束【需要重写】**
  - **3.2 物理超限优先级与 Peak guardrail【需要重写】**
  - **3.3 稳态均衡目标 \(Q_{\rm ss}\)【可直接写】**
  - **3.4 Peak、Variance 与 Balanced 三种模式【需要重写】**
    - **3.4.1 Peak lexicographic objective【可直接写】**
    - **3.4.2 Variance lexicographic objective【可直接写】**
    - **3.4.3 Balanced reference 与 Peak budget【需要重写】**
- **4 GCLS 求解方法【需要重写】**
  - **4.1 候选预计算与 greedy construction【需要重写】**
  - **4.2 精确增量 1-opt【可直接写】**
    - **4.2.1 增量 \(Q\) 更新与 rollback【可直接写】**
    - **4.2.2 有限终止与单报文局部最优边界【可直接写】**
  - **4.3 conflict-directed pair search【需要重写】**
  - **4.4 restart 与候选池【需要重写】**
    - **4.4.1 自适应 restart 与 seed【需要重写】**
    - **4.4.2 Balanced candidate pool【需要重写】**
    - **4.4.3 可选 3-opt 的定位【需要重写】**
  - **4.5 复杂度、确定性、审计与 heuristic 边界【需要重写】**
- **5 Offset–MainFunction 调度耦合与 exact 子问题【需要重写】**
  - **5.1 公共整数时间栅格与 exact tick alignment 假设【可直接写】**
  - **5.2 单报文最大可行节拍 \(D_i=\gcd(T_i,O_i)\)【可直接写】**
  - **5.3 分组最大 TimeBase \(B_g\)【可直接写】**
  - **5.4 CPU cost proxy【需要重写】**
    - **5.4.1 理论成本形式与线性组成本假设【可直接写】**
    - **5.4.2 \(\rho\) 与 \(P_{\rm CPU}\)【可直接写】**
    - **5.4.3 proxy 的解释边界与 naive split bias【需要重写】**
  - **5.5 D-type compression【可直接写】**
  - **5.6 确定性 subset-DP【可直接写】**
    - **5.6.1 anchor recurrence 与 optimal substructure【可直接写】**
    - **5.6.2 exactness 和复杂度边界【可直接写】**
- **6 CAN–CPU 联合优化【需要重写】**
  - **6.1 long-period Offset=0 工程策略【需要重写】**
  - **6.2 exact inner evaluator 与 heuristic outer search【需要重写】**
  - **6.3 ε-constraint 联合模型【可直接写】**
    - **6.3.1 Peak guardrail 与 CPU budget【可直接写】**
    - **6.3.2 不采用线性加权和的原因【可直接写】**
  - **6.4 observed anchors、累计 archive 与 iterative refinement【需要重写】**
    - **6.4.1 initial anchors 与 observed endpoints【需要重写】**
    - **6.4.2 Peak reference/budget refinement【需要重写】**
    - **6.4.3 convergence、limit 与两类稳定性【需要重写】**
  - **6.5 observed Pareto front【可直接写】**
    - **6.5.1 二维 dominance 与 representative【可直接写】**
    - **6.5.2 observed 与 global 的边界【可直接写】**
  - **6.6 几何 knee 后处理【可直接写】**
    - **6.6.1 exact normalization 与 \(s=1-x-y\)【可直接写】**
    - **6.6.2 ideal-point fallback 与 0/1/2 点规则【可直接写】**
    - **6.6.3 推荐的非唯一性与敏感性边界【需要重写】**
- **7 实验设计与结果【需要重写】**
  - **7.1 数据、输入资格、环境与复现清单【需要重写】**
    - **7.1.1 九网段数据与 eligible/fixed 统计【等最终九网段数据】**
    - **7.1.2 参数、seed、预算与运行环境【需要重写】**
    - **7.1.3 指标、统计口径与质量门禁【需要重写】**
  - **7.2 研究问题与对照组【可直接写】**
  - **7.3 RQ1：CAN-only Peak/Qss 主结果【等最终九网段数据】**
    - **7.3.1 Original、Greedy、Peak 与 Balanced【等最终九网段数据】**
    - **7.3.2 Variance 的均衡—峰值权衡【等最终九网段数据】**
  - **7.4 RQ2：GCLS 稳定性与必要消融【等最终九网段数据】**
    - **7.4.1 restart objective/assignment stability【等最终九网段数据】**
    - **7.4.2 tolerance 与 candidate-pool 敏感性【等最终九网段数据】**
    - **7.4.3 weight mode 与 conservative timing【等最终九网段数据】**
  - **7.5 RQ3：小规模外部/精确对照【需要重写】**
    - **7.5.1 CP-SAT better-feasible 与状态解释【需要重写】**
    - **7.5.2 禁止从 FEASIBLE 推导全局最优【可直接写】**
  - **7.6 RQ4：MainFunction exact solver 验证【可直接写】**
    - **7.6.1 141 次 brute-force oracle【可直接写】**
    - **7.6.2 distinct D-type scaling【可直接写】**
  - **7.7 RQ5：九网段 CAN–CPU tradeoff【等最终九网段数据】**
    - **7.7.1 observed endpoints/front 与 Peak feasibility【等最终九网段数据】**
    - **7.7.2 refinement trajectory 与终止状态【等最终九网段数据】**
    - **7.7.3 knee/fallback 推荐汇总【等最终九网段数据】**
  - **7.8 RQ6：联合结果敏感性【等最终九网段数据】**
    - **7.8.1 seed 的 objective/assignment 稳定性【等最终九网段数据】**
    - **7.8.2 rho 情景敏感性【等最终九网段数据】**
    - **7.8.3 epsilon-grid、K 与 search-path 敏感性【等最终九网段数据】**
- **8 讨论【需要重写】**
  - **8.1 Offset 均衡的收益与不可改变项【可直接写】**
  - **8.2 exact inner 与 heuristic outer 的证据边界【可直接写】**
  - **8.3 CPU proxy、rho 与硬件标定缺口【需要重写】**
  - **8.4 输入口径、CAN timing 与外部有效性威胁【需要重写】**
  - **8.5 工程部署与 DBC writeback 的有限说明【需要重写】**
- **9 结论【等最终九网段数据】**
  - **9.1 已证理论与算法性质【可直接写】**
  - **9.2 九网段 observed 结果摘要【等最终九网段数据】**
  - **9.3 限制与后续标定【需要重写】**
- **附录 A 开发期诊断与补充消融【需要重写】**
  - **A.1 candidate pool 与 3-opt【需要重写】**
  - **A.2 完整 tolerance/restart 表【等最终九网段数据】**
  - **A.3 weight sensitivity 完整表【等最终九网段数据】**
- **附录 B 证明细节与伪代码【可直接写】**
  - **B.1 MainFunction 命题与 subset-DP 证明【可直接写】**
  - **B.2 GCLS 1-opt 终止性【可直接写】**

### 2.1 目录审计主表

| 最终章节 | 状态 | old-1 来源 | old-2 来源 | 其他来源 | 迁移策略 | 需要的公式/证明 | 需要的实验 | 风险 |
|---|---|---|---|---|---|---|---|---|
| 1 引言 | 需要重写 | §1 引言 | §1 问题定义与设计目标 | `docs/01_research_and_design.md`; `docs/can_cpu_joint_optimization_report.md`; `docs/can_cpu_joint_validation_report.md` | 只保留“局部聚集”动机，加入 Offset 具有 CPU 代价的因果转折 | C02–C04 的边界 | 最终主结果摘要 | Related Work 后续补文献，本轮不引用 |
| 2.1–2.2 释放与离散窗口 | 可直接写/局部重写 | §2.2；§3.1–3.3 | — | `src/canfd_offset_optimizer/timeline/slot_map.py` | 保留 release/window 基础，候选边界抽象化 | P1–P3 | 无 | cap 与有限窗口条件 |
| 2.3 输入边界 | 需要重写 | §2.1–2.3 | — | GUI docs；parser/loader/config；已确认最终需求 | 按已裁决规则重写：每 DBC 显式 sender；按“目标网段 + CAN ID”排除路由报文；模型兼容 CAN/CAN FD，主实验锁定单一协议 | eligible set 集合定义 | 统一 manifest 中的 eligible/fixed/excluded 清单 | 当前 core 尚未完全实现，必须先修复再重跑 |
| 2.4 CAN 评价 | 需要重写 | §2.3；§3.4；§4 | §5 | objective/frame_time；严格审查 | 删除绝对偏差 D，统一 Peak/Qss 与权重边界 | Qss–variance 等价 | 九网主结果、weight | conservative 非 bit-exact |
| 2.5 耦合导入 | 可直接写 | — | §1–2 | joint design | 从问题模型即引入，避免后半突兀 | 整除条件 | 无 | 必须声明工程假设 |
| 3 Offset 模型 | 需要重写 | §4 | §5 | objective/gcls | 按 current lexicographic keys 重建 | objective definitions | 模式对比 | Balanced reference heuristic |
| 4 GCLS | 需要重写 | §5、§7–8 | §7 部分框架 | GCLS/local_search；严格审查 | 保留总体骨架，替换 restart、candidate pool 与边界 | P4 | restart/CP-SAT/消融 | 不可全局最优 |
| 5 MainFunction exact | 可直接写/局部重写 | — | §2–4、§10 | exact solver report/source/tests | 作为论文理论核心重构，补正式证明 | P5–P12 | oracle/scaling | proxy 假设与 exact 范围 |
| 6 joint/Pareto/knee | 需要重写 | — | §6–9、§11 | joint source/analysis/validation | 用 archive+refinement 替代静态 21 点流程 | dominance/knee definitions | DK/GL/IC preliminary，最终九网 | 外层 heuristic；三网不足 |
| 7 实验 | 等最终九网段数据 | §6、§9–10 | 零散说明 | 所有 reports/outputs | 按 RQ 与 claim ID 组织；CAN-only 与 joint 共享一份最终九网 manifest | oracle 与统计定义 | 同一 manifest 下的 CAN-only 与 joint | 历史九网全部降级为开发期证据 |
| 8 讨论 | 需要重写 | §12 | §10 | 全部验证报告 | 集中讨论边界、敏感性、可部署性 | 无新定理 | 依赖最终敏感性汇总 | 避免把 GUI 写成方法 |
| 9 结论 | 等最终九网段数据 | §13 | §12 | final evidence | 仅汇总已证性质与 observed 结果 | 引用前述命题 | 最终九网数字 | 禁止“最优/普适” |
| 附录 | 需要重写 | §7–11 的实现/验证细节 | §9–10 细节 | diagnostics | 开发期诊断降级为补充材料 | 完整证明/伪代码 | 完整消融表 | 不挤占主叙事 |

## 3. old-1 逐节迁移审计

| 旧章节 | 旧内容核心 | 当前是否仍正确 | 最终去向 | 状态 | 原因 |
|---|---|---|---|---|---|
| §1 引言 | Offset 聚集、5 ms 局部峰值、CAN-only 动机 | 部分正确 | → 1.1，并与 CPU coupling 合并 | 【需要重写】 | 只有 CAN 收益，没有“Offset 非免费变量”的主线；部分语气过强 |
| §2 问题边界与基本假设 | 研究对象、输入和可行性 | 部分过时 | → 2.3、7.1 | 【需要重写】 | 最终规则已裁决，但旧稿和当前 core 均未完整反映显式 sender、routing exclusion 与统一 manifest |
| §2.1 研究边界 | 只优化周期 CAN FD、不改其他属性 | core 层面大体正确 | → 2.3 | 【需要重写】 | 需加入 sender/routing/fixed/long-period 的明确层次，不能照抄 |
| §2.2 符号与输入 | 固定 15–100 ms/5 ms 候选 | 作为一次配置正确，作为一般模型错误 | → 2.2.1、7.1.2 | 【需要重写：原表述错误】 | 统一为 \(O_{\min}+k\delta\le O_{\max}\)，max 不要求命中 step 且不强行补入；旧整除限制待实现统一 |
| §2.3 CAN FD 报文权重 | 帧时间/负载权重 | 过度简化 | → 2.4.1 | 【需要重写】 | 当前 frame-time 是 conservative estimate；payload/unit 只是敏感性 |
| §2.4 平均负载可行性检查 | 平均利用率超过阈值即判不可行、不搜索 | 当前实现不符 | → 删除；警告机制可在 7.1 简述 | 【应从旧稿删除】 | loader 只给 warning 并继续；75% 不是数学不可行阈值 |
| §3 离散时隙负载模型 | 超周期、窗口、load map | 核心仍正确 | → 2.1–2.4 | 【可直接写】 | 需补 cap/半开区间与权重边界 |
| §3.1 超周期与时隙 | LCM 与 slot | 正确但条件需写全 | → 2.2.2 | 【可直接写】 | cap 或整数倍窗口需披露 |
| §3.2 启动阶段与稳态阶段 | 两窗口分离 | 当前采用 | → 2.2.2 | 【可直接写】 | 保留定义，不外推无限稳态 |
| §3.3 时隙负载与释放计数 | load map | 当前采用 | → 2.4.2 | 【可直接写】 | 用 current half-open expansion 表述 |
| §3.4 5 ms 峰值约束 | 固定 5 ms 阈值 | 只是一组配置 | → 2.4.2/7.1.2 | 【需要重写】 | slot width 和阈值应参数化 |
| §4 优化目标 | Peak、绝对偏差、旧 lexicographic key | 主体过时 | → 3 | 【需要重写：原公式过时】 | current 使用 Qss 与 Peak/Variance/Balanced 三模式 |
| §4.1 峰值与超限量 | \(N_{\rm vio},V_{\rm vio},Z\) | 核心正确 | → 3.2 | 【需要重写】 | 加入启动/稳态顺序和物理解释 |
| §4.2 均匀度指标 | 绝对偏差 \(D\) | 已被 Qss 取代 | → 删除旧公式；由 3.3 重写 | 【应从旧稿删除】 | 继续保留会与实现、报告冲突 |
| §4.3 词典序目标 | \((N,V,Z,D,K)\) | 错误/过时 | → 3.4 | 【需要重写：原公式错误】 | 三模式 keys 均已变化 |
| §5 主算法：GCLS | greedy+local+restart | 骨架仍正确 | → 4 | 【需要重写】 | adaptive restart、candidate pool、可选 3-opt 与 current comparator 均需更新 |
| §5.1 总体结构 | 将流程称为全局优化/最终最优 | 流程可用，强度错误 | → 4 导言 | 【需要重写：过度声称】 | 改为 heuristic best-found |
| §5.2 候选时隙预计算 | 预计算受影响 slots | 当前仍有 | → 4.1 | 【可直接写】 | 只保留算法必要信息 |
| §5.3 贪心构造 | 逐报文选候选 | 当前仍有 | → 4.1 | 【需要重写】 | 写清 current sorting/tie-break |
| §5.4 单报文重定位局部搜索 | 1-opt | 当前加强且可证明局部性质 | → 4.2 | 【可直接写】 | 补 exact delta、rollback、有限终止 |
| §5.5 冲突导向双报文搜索 | bounded pair search | 当前仍有 | → 4.3 | 【需要重写】 | 不是完整 2-opt，不可写 pair-local-optimal |
| §5.6 随机重启 | 固定 20 次 | 已过时 | → 4.4.1 | 【需要重写：参数过时】 | 当前 20/10/20/80 adaptive；只打乱等周期等权组 |
| §6 对照算法 | original/random/greedy/CP-SAT | 部分保留 | → 7.2、7.5 或附录 | 【需要重写】 | random 是否保留取决于最终 RQ；CP-SAT 不是全量 exact baseline |
| §6.1 原始 Offset 配置 | baseline | 仍必要 | → 7.2 | 【可直接写】 | 需核验 original Offset 来源 |
| §6.2 随机分配 | random baseline | 解释价值弱 | → 附录或删除 | 【应从旧稿删除】 | 若不能回答独立 RQ，不占主文 |
| §6.3 纯贪心 | 区分 local-search 增益 | 仍必要 | → 7.2/7.3 | 【可直接写】 | 保留为算法消融 |
| §6.4 CP-SAT 精确对照 | 预期 exact/optimal | 过度声称 | → 7.5 | 【需要重写：原定位错误】 | DK/GL/IC 仅 FEASIBLE；只作 better-feasible 诊断 |
| §7 复杂度分析 | GCLS 粗复杂度 | 需更新 | → 4.5 | 【需要重写】 | 加入 candidate pool、pair、restart，分 worst-case 与配置预算 |
| §8 正确性与不变量 | 可行性、单步改善 | 部分可用 | → 4.2、4.5、附录 B | 【需要重写】 | 只证明有限/局部性质，不证明 solution optimality |
| §9 实验设计与验证方法 | 开发期验证计划 | 多数被真实报告取代 | → 7 重构 | 【需要重写】 | 按 claim/RQ 组织而不是按计划清单 |
| §9.1 对照组 | planned baselines | 部分可用 | → 7.2 | 【需要重写】 | 与最终实验矩阵对齐 |
| §9.2 主要评价指标 | Peak/绝对偏差等 | 过时 | → 7.1.3 | 【需要重写】 | 统一 Peak/Qss/CPU proxy/front stability |
| §9.3 验证层次 | unit/exhaustive/CP-SAT/Vector | 只有部分已完成 | → 7.5–7.6、8.4 | 【需要重写】 | 不得把计划写成已完成 |
| §9.3.1 单元级数学一致性 | unit validation | 已有丰富测试 | → 7.6/复现说明 | 【可直接写】 | 测试不是证明 |
| §9.3.2 穷举验证 | 计划 N≤5 的 Offset 穷举 | 未发现对应正式结果 | → 删除；保留 MainFunction oracle | 【应从旧稿删除】 | 不可虚构 CAN 外层穷举 |
| §9.3.3 CP-SAT 对照 | exact 对照计划 | 已做但无 optimal status | → 7.5 | 【需要重写】 | 报告真实 solver status |
| §9.3.4 真实项目对照 | Vector/CANoe 计划 | 无当前证据 | → 删除或 8.4 future work | 【应从旧稿删除】 | 未发现 CANoe/硬件验证产物 |
| §9.4 测试集设计 | random/真实/扩展规模计划 | 部分未执行 | → 7.1；其余删除 | 【需要重写】 | 只写有 manifest 的数据集 |
| §10 示例说明 | 人工小例 | 可能重复方法 | → 附录或删除 | 【应从旧稿删除】 | 主文空间优先给真实 RQ；除非用于解释 GCLS |
| §11 实现方法 | 模块/API/工程说明 | 论文主线价值低 | → 极短复现说明或删除 | 【应从旧稿删除】 | 开发文档不是研究方法 |
| §12 适用范围与结果解释 | CAN-only 边界 | 核心必要但已不完整 | → 8 | 【需要重写】 | 加入 CPU proxy、joint heuristic、已裁决输入规则、当前实现差距和敏感性 |
| §13 结论 | 旧 CAN-only 结论 | 已过时且有强述风险 | → 9 | 【应从旧稿删除】 | 不修补旧结论；待最终九网数据后全新撰写 |

## 4. old-2 逐节迁移审计

| 旧章节 | 旧内容核心 | 当前是否仍正确 | 最终去向 | 状态 | 原因 |
|---|---|---|---|---|---|
| §1 问题定义与设计目标 | Offset 影响 MainFunction 粒度 | 核心正确 | → 1.2、2.5 | 【需要重写】 | 需与 CAN 聚集问题融成一个研究问题 |
| §2 MainFunction 时间栅格的可表示性模型 | gcd 模型 | 模型内正确 | → 5.1–5.3 | 【可直接写】 | 必须显式声明 common origin/exact tick，不称标准规定 |
| §2.1 单条报文的精确可表示条件 | \(B\mid T_i,O_i\)，\(D_i\) | 正确 | → 5.1–5.2 | 【可直接写】 | 补 \(O_i=0\) 和正式证明 |
| §2.2 一个 MainFunction 分组的最优 TimeBase | group gcd | 正确 | → 5.3 | 【可直接写】 | “最优”限定为最大可行 TimeBase |
| §3 CPU 侧指标：从真实利用率到可计算代理量 | proxy 建模 | 主题正确 | → 5.4 | 【需要重写】 | 不能让读者误解为实测 CPU |
| §3.1 真实 CPU 利用率的理想形式 | \(\sum C_g/B_g\) | 作为模型形式可用 | → 5.4.1 | 【可直接写】 | 以假设语气写，不作测量事实 |
| §3.2 为什么简单的 CPU Proxy 不够合理 | naive split bias | 直觉可用、命题不够严 | → 5.4.3 | 【需要重写】 | 需条件化证明，避免所有拆分都不利的误述 |
| §3.3 固定调用开销 + 组内报文开销模型 | \(C_0+C_1N_g\)、rho | 正确的模型定义 | → 5.4.1–5.4.2 | 【可直接写】 | rho 未标定 |
| §4 固定 Offset 下的 MainFunction 精确子求解器 | compression+subset-DP | 当前核心理论 | → 5.5–5.6 | 【可直接写】 | 需把证明与 141 次测试分开 |
| §4.1 条件精确性的目标 | fixed Offset inner exact | 正确 | → 5.6.2、6.2 | 【可直接写】 | 明确不使 outer exact |
| §4.2 相同 D 类型的报文无需拆分 | same-D theorem | 有证明思路 | → 5.5、附录 B | 【可直接写】 | 正文给命题，附录补形式化证明 |
| §4.3 子集组成本 | group cost | 正确 | → 5.6.1 | 【可直接写】 | multiplicity 和 Fraction 单位写清 |
| §4.4 确定性的子集动态规划 | anchor DP | 正确 | → 5.6 | 【可直接写】 | 补 recurrence、tie-break 与 \(O(3^m)\) |
| §5 CAN 侧指标：复用现有 Balanced 评价体系 | 旧 Balanced 接口描述 | 部分过时 | → 3.4、6.2 | 【需要重写】 | 需与 current Peak reference/refinement 一致 |
| §6 联合双目标模型 | \(Q\)、\(P\)、Peak guardrail | 核心正确 | → 6.2–6.3 | 【需要重写】 | 写明 exact inner + heuristic outer |
| §7 ε-constraint | 21 budgets 的静态搜索 | 原理正确，流程过时 | → 6.3–6.4 | 【需要重写】 | K 已可配、存在 cumulative archive/refinement |
| §7.1 两个锚点 | 以 `argmin` 表示 CAN/CPU exact anchors | 表述错误 | → 6.4.1 | 【需要重写：原公式错误】 | 只能称 heuristic initial anchor/observed endpoint |
| §7.2 CPU 预算扫描 | 21 点扫描 | 部分正确 | → 6.3、6.4 | 【需要重写】 | endpoint 与 grid 会在 refinement 中更新；K sensitivity 显著 |
| §8 Pareto 过滤与默认折中点选择 | observed front+knee | Pareto 核心可用，knee 规则过时 | → 6.5–6.6 | 【需要重写】 | current exact Fraction、fallback、0/1/2点行为与旧稿不同 |
| §9 完整算法流程 | 一次性 anchors→21点→knee | 已被 refinement 取代 | → 6.4 | 【应从旧稿删除】 | 不修补旧流程图；按 current cumulative refinement 重画 |
| §10 数值、确定性与实现边界 | Fraction、determinism、exact scope、rho | 大部分可用 | → 4.5、5.6、8 | 【需要重写】 | rho “鲁棒”已被验证反驳 |
| §10.1 整数时间与精确比较 | integer/Fraction | 当前采用 | → 5.1、5.6 | 【可直接写】 | 区分模型离散化与浮点显示 |
| §10.2 确定性 | tie-break | 当前采用但规则扩展 | → 4.5、6.6 | 【需要重写】 | knee 已改 exact ordering；跨 seed 不是同一问题 |
| §10.3 精确性的范围 | inner exact、outer heuristic | 正确且关键 | → 6.2、8.2 | 【可直接写】 | 必须放主文而非脚注 |
| §10.4 \(\rho\) 的鲁棒性 | 预期 rho 不敏感 | 当前结果反驳 | → 7.8.2、8.3 | 【应从旧稿删除】 | 实测 rho 明显改变 group count/structure |
| §11 最终推荐输出 | 21点 front 与自动 knee | 规则与证据均过时 | → 6.6、7.7.3 | 【需要重写】 | K21 不稳定，knee 不是唯一工程最优 |
| §12 结论 | joint 方法已完成性结论 | 证据不足 | → 9 | 【应从旧稿删除】 | 仅三网 preliminary，三网 refinement 均触及 pass limit |

## 5. GUI 设计中需要反映到论文的问题边界

本节只提炼会改变研究对象的规则，不把 GUI 控件、页面流程或交互写进论文。下列产品语义已经裁决；当前 GUI 文档与 core source 的差异不再作为“需求冲突”，而作为最终九网重跑前必须关闭的**实现差距**。

| 规则 | GUI 文档说法 | 当前 core/source 核对 | 论文去向 | 结论与待办 |
|---|---|---|---|---|
| sender selection | mandatory；按选定本机 sender 筛 TX | `parse_dbc(path)` 无 sender 参数，取首个非 `Vector__XXX` sender | 系统模型、数据预处理 | **最终规则已确定**：每个 DBC 必须显式选择本机发送节点；修复 core，并在最终 manifest 逐网记录 sender |
| only periodic TX | 只优化周期 TX | parser 要求有效周期并筛发送报文 | 系统模型 | 可保留抽象规则，需定义周期属性来源 |
| routing exclusion | routing Excel 中目标网段报文排除 | current repo 无 routing parser/exclusion | 数据预处理、实验设置 | **最终规则已确定**：按“目标网段 + CAN ID”匹配并排除，路由报文不参与 Offset 优化；实现、测试后再重跑 |
| DBC / ARXML / Excel 分工 | DBC 定义报文；ARXML 补 timing；Excel 给 routing | core loader 为 DBC + ARXML directory + YAML，无 routing Excel | 实验设置 | 最终数据管线锁定后再写；GUI 操作不进正文 |
| CAN / CAN FD | 网络级选择两种协议 | parser 对周期非 CAN FD TX fail-closed | 系统模型、实验设置 | **最终规则已确定**：论文模型兼容两者；九网主实验保持统一协议口径，若沿用原九网则保持 CAN FD；Classic CAN 只作工程扩展 |
| nominal/data bitrate、BRS、DLC | 作为 frame timing 必需输入 | frame-time mode 缺关键字段会失败 | 系统模型、实验设置 | 应进入；明确 conservative estimate |
| Offset min/max/step | max 可不落在 step 上，不补 max | `src/canfd_offset_optimizer/config.py` 要求区间差整除 step | 系统模型 | **最终规则已确定**：\(\mathcal O_i=\{O_{\min}+k\delta\mid O_{\min}+k\delta\le O_{\max}\}\)；max 不要求命中 step，也不强行补入；旧限制待统一 |
| long-period Offset=0 | \(T_i>O_{\max}\) 固定 0 | joint domain 已实现；CAN-only 一般 GCLS 不应自动外推 | joint 方法、讨论 | 写成工程策略，不写 GUI 规则或标准结论 |
| fixed message 参与评价 | 固定但仍计入负载 | joint evaluator 计入 CAN/CPU | 系统模型、joint 方法 | 应进入 |
| DBC Offset 字段与 writeback | 仅认并写 `GenMsgStartDelayTime` | parser 当前还接受 `GenMsgDelayTime` 等 alias；current repo 未见 writer | 数据预处理、baseline 定义；工程实现短节 | **无 fallback**：parser 与 writer 都只能使用 `GenMsgStartDelayTime`；这是会污染 Original baseline 的阻断性 bug，最终九网重跑前必须修复 |
| missing timing fail-closed | timing 数据缺失不静默估算 | frame-time loader 当前符合 | 实验设置、威胁 | 可写为工程数据完整性规则 |
| conservative occupancy | 作为安全侧诊断 | frame-time 是保守估计，但不含完整仲裁分析 | 指标边界、讨论 | 不称 schedulability 或 bit-exact occupancy |
| 最终九网 manifest | GUI/数据流文档分别描述输入项 | 旧 CAN-only 与三网 joint 证据批次不统一 | 实验设置、复现性 | **统一一份 manifest**：同一九网、sender、routing exclusion、协议、权重、Offset 参数、commit、输入 hash；CAN-only 与 joint 共同使用 |
| GUI 页面、预览、导出按钮 | 工具行为 | 与研究问题无直接关系 | 不应进入论文 | **应从旧稿/正文删除**；最多一句说明原型工具 |

## 6. 最终实验计划矩阵

| 实验 | 回答的研究问题 | 对应 claim ID | 当前数据状态 | 最终正文/附录/删除 | 还缺什么 |
|---|---|---|---|---|---|
| Original/Greedy/Peak/Balanced 九网对比 | GCLS 是否降低局部 Peak/Qss，增益来自哪里 | C18、C20、C27–C29 | 旧九网全部降级为开发期证据 | 正文主结果 | 在统一 manifest 下重跑；显式 sender、routing exclusion、StartDelay-only baseline、全绿门禁、assignment stability |
| Variance vs Peak | 直接优化 Qss 的峰值代价是什么 | C13、C15 | 旧九网只作开发期证据 | 正文次结果 | 与 CAN-only/joint 共用同一最终 manifest，重算 Qss 改善与 Peak 代价 |
| restart saturation | 搜索预算是否足够、目标命中率如何 | C21、C31 | DK 30×80 开发期数据 | 附录；正文只摘要 | 九网统一预算；objective hit 与 assignment diversity；不要声称 80 饱和 |
| seed sensitivity（CAN-only） | deterministic run 与跨 seed 稳定性 | C22、C31 | 局部开发证据 | 附录 | 九网同配置多 seed 或合理抽样 |
| Balanced/Peak budget | Peak guardrail 内是否能换取 Qss | C16、C29–C30 | 旧 5%/tolerance 结果均为开发期证据 | 正文摘要+附录曲线 | 统一 manifest 下重跑 tolerance；记录 reference 与 pool 配置 |
| tolerance scan | 预算—均衡 tradeoff | C30 | 旧 0–20% 九网诊断为开发期证据 | 附录 | 当前 HEAD 与统一 manifest/candidate pool；明确“首次观察” |
| weight mode | 结论对 frame_time/payload/unit 是否敏感 | C10–C11 | 旧 dual-weight 目录为开发期证据 | 附录；主文报告主权重 | 统一 manifest 下重跑；按网络汇总方向一致性 |
| conservative occupancy | frame-time estimate 的安全侧解释 | C10、C17 | 设计/诊断证据 | 讨论或附录 | 模型误差说明；如无外部 trace，不做精确性结论 |
| CP-SAT | heuristic 与 better-feasible 解的差距 | C25–C26 | DK/GL/IC 均 FEASIBLE | 正文限制或附录 | 状态、time limit、budget、gap；不能称 exact baseline |
| CAN 外层 exhaustive small scale | 是否有小实例全局证书 | C25 | 未发现正式结果 | 删除旧计划 | 若未来不补，不写 |
| MainFunction brute-force oracle | exact DP 实现是否与枚举一致 | C39–C42 | 141/141 完成 | 正文验证 | 固定测试生成规则/版本即可 |
| MainFunction scalability | distinct D-type 增长下耗时 | C41 | m=4–6 与 synthetic m12/13 已有 | 正文或附录 | 报告硬件/环境、重复统计；不外推大规模 |
| joint CAN/CPU tradeoff | 是否存在不同 Qss/P_CPU 折中 | C44–C51、C58 | 仅 DK/GL/IC preliminary | 正文主结果 | 与 CAN-only 相同 manifest 的九网 archives/fronts/endpoints/feasibility |
| iterative refinement | archive/ref 更新是否发现新点、何时停止 | C47–C49 | 三网均触及 pass limit | 正文方法；结果待九网 | 九网 pass trajectory、converged/limit 分开 |
| joint seed stability | front objective 与 assignment 是否稳定 | C49、C56 | 三网：DK稳、GL objective变、IC assignment变 | 正文限制/附录 | 九网或预注册代表性抽样；hash 与 Hausdorff |
| rho sensitivity | proxy 假设如何改变 grouping/front | C36–C37、C57 | 三网显示显著变化 | 正文讨论+附录 | 九网情景汇总；有条件时补硬件标定 |
| epsilon-grid/K sensitivity | observed front/knee 是否依赖 K | C55 | K21 vs41 三网均非零 H | 正文限制 | 九网至少验证主配置选择；记录预算序列 |
| search-path sensitivity | refinement/顺序是否影响 archive | C47–C49 | 部分 source/test 与三网迹象 | 附录 | 明确路径变体与等预算对照 |
| knee | 自动推荐是否有内部几何折中 | C52–C56 | 算法测试完备，结果仅三网 | 正文方法；结果待九网 | 每网 front size、method、score、K/seed robustness |
| Vector/CANoe 或硬件 trace | 外部物理效果 | 无当前 claim | 无证据 | 删除旧稿“已验证”暗示；可列 future work | 若未来执行需独立实验设计 |
| 3-opt | 是否值得默认启用 | C24 | IC 有改善、DK/GL 无改善，默认关闭 | 附录或删除 | 无需扩大为主文；只在篇幅允许时报告 |

## 7. 最终九网段数据到位后需要填充的内容

### 7.1 数据与可复现性锁定

- [ ] 记录最终 commit、dirty status、Python/solver 版本、运行命令和配置文件 hash。
- [ ] 生成**唯一一份最终九网 manifest**，锁定九个网络名称、DBC/ARXML/routing 输入 hash；CAN-only 与 CAN/CPU joint 必须共同引用它。
- [ ] 每个 DBC 显式记录 selected local sender；禁止继续使用“首个 sender”隐式规则。
- [ ] 按“目标网段 + CAN ID”执行 routing exclusion，并列周期 TX 总数、eligible decision count、fixed count、excluded count 及逐类原因。
- [ ] 锁定九网主实验的单一协议口径；若仍为原 CAN FD 九网则保持 CAN FD，Classic CAN 只列工程扩展，不临时并入主样本。
- [ ] 验证候选集合严格采用 \(O_{\min}+k\delta\le O_{\max}\)，max 不要求命中 step，也不额外补入。
- [ ] parser 与 writer 均只使用 `GenMsgStartDelayTime`；增加针对 `GenMsgDelayTime` 不得 fallback 的回归检查，修复后再生成 Original baseline。
- [ ] 列 nominal/data bitrate、BRS、DLC 完整性与 frame-time fail-closed 结果。
- [ ] 记录 \(O_{\min},O_{\max}\)、step、slot width、\(H\)/cap、物理阈值、weight mode。
- [ ] 最终质量门禁全绿；旧九网结果全部保留为开发期证据，不能沿用其 78 passed/2 failed/48 errors 自相矛盾状态或数值填正文。

### 7.2 CAN-only 九网主结果

- [ ] 每网 Original/Greedy/Peak/Variance/Balanced 的 \(N_{\rm vio},V_{\rm vio},Z_{\rm ss},Q_{\rm ss},Z_{\rm st},Q_{\rm st}\)。
- [ ] Original→Peak 与 Greedy→GCLS 的绝对/相对改善；汇总改善网络数、中位数和范围。
- [ ] Balanced 的 Peak reference、budget、candidate pool、是否找到低 Qss 解；未找到时只报告“未观察到”。
- [ ] Variance 的 Qss 收益与 Peak 代价，不能只报有利维度。
- [ ] 各模式运行时间、restart attempts、best objective hit-rate 和 assignment hash 数。
- [ ] weight-mode 敏感性方向与主 `frame_time_us` 结论是否一致。
- [ ] tolerance 扫描中首次观察到改善的位置和至扫描上限未改善的网络，禁止称数学阈值。

### 7.3 九网段 CAN–CPU 联合结果

- [ ] 每网 decision/fixed/long-period count 与 distinct D-type 数 \(m\)。
- [ ] rho、K、seed、attempts、max refinement passes 和 exact budget 序列。
- [ ] initial CAN/CPU anchors 与最终 observed CAN/CPU endpoints；标出被支配/替换关系。
- [ ] 每个 refinement pass 的 archive size、feasible count、observed front count、Peak reference/budget 变化。
- [ ] 每网终止原因：exact adjacent-signature convergence 或 pass limit；不能合并称“收敛”。
- [ ] 最终 observed Pareto 表：assignment hash、\(Q_{\rm ss}\)、\(P_{\rm CPU}\)、Peak、MainFunction count。
- [ ] Peak feasibility/violation 统计；Peak 只作 guardrail，不作为第三 Pareto 维。
- [ ] knee method（geometric/fallback/unique/no-interior/empty）、score、index、两个归一化坐标与选择 hash。
- [ ] 至少对主配置给出 K/grid sensitivity；若 K21 不稳定，说明最终 K 的选择依据。
- [ ] seed objective-front Hausdorff 与 assignment-hash diversity 分开汇总。
- [ ] rho 情景下 group count、TimeBase 结构、front 与 knee 变化；没有硬件标定时不推荐单一“真实”rho。

### 7.4 图表和结论填充

- [ ] 九网 CAN-only 总表与每网 Peak/Qss 改善图。
- [ ] 九网 observed Qss–CPU proxy fronts，图中标 endpoints 与 knee/fallback。
- [ ] refinement trajectory/新增 archive 点图或表。
- [ ] K、seed、rho 敏感性汇总图，正文只放回答 RQ 的最小集合，其余移附录。
- [ ] 结论仅填写“多少网络观察到何种改善/权衡”，并同时写未改善网络与限制。
- [ ] 全文逐项回查 `docs/paper_claim_evidence_matrix.md`：所有数字对应 claim ID、路径、commit 和可写强度。

## 8. 明确不迁入正文的旧内容

1. `old-1` 的绝对偏差 \(D\) 与旧 lexicographic objective。
2. 以 15–100 ms、5 ms、75% 为普遍模型/不可行判据的表述。
3. 未实际完成的 CAN 外层穷举、Vector/CANoe、随机扩展数据计划。
4. `old-1` 的详细实现/API 说明和缺乏独立 RQ 的人工示例。
5. `old-2` 的静态“两个 exact anchors + 固定 21 点 + 一次 knee”流程。
6. `old-2` 的“rho 鲁棒”结论。
7. 任何把 CP-SAT `FEASIBLE`、GCLS、observed front 或 knee 写成全局/唯一最优的句子。
8. GUI 页面、按钮、预览、导出流程；只有已裁决的问题边界规则进入 2.3/7.1，且最终实验必须证明对应实现差距已关闭。

## 9. 最终九网段到位后的提纲状态更新（2026-07-28）

> 仅更新状态与证据路径；前文历史审计意见继续保留。

### 9.1 已解除的正文阻塞项

- 最终 eligible set 已由唯一 manifest 锁定：九个 DBC 均显式选择 `FLZCU`，routing exclusion 已在 joint decision/fixed 分割前执行。
- Original baseline 已按 StartDelay-only 语义重算，eligible message 的 StartDelay unknown 均为 0。
- Offset 候选上界语义已经统一为截断网格；九网段主实验协议统一为 CAN FD。
- CAN-only 与 joint 使用相同 manifest 和 eligible set，输入 hash、配置、环境和逐网计数均可追溯。
- 最终数据质量门禁为 `paper_ready=true`，不再处于“等待最终九网段数据”状态。

### 9.2 可用于各章的最终证据

| 正文章节 | 最终证据 | 当前状态 |
|---|---|---|
| 2.3 研究对象与预处理 | `docs/final_nine_network_manifest.yaml`、preflight CSV/JSON | 可写 |
| 3–4 CAN 指标与 GCLS | `summary/can_only_summary.csv`、逐网 `can_only.json` | 可写，仍称 heuristic observed result |
| 5 MainFunction exact inner | 完整 joint JSON 的 groups、TimeBase 与 exact Fraction；现有 oracle tests | 可写，exact 仅限定 fixed-Offset inner |
| 6 联合优化与 observed Pareto | `summary/joint_summary.csv`、`pareto_points.csv`、逐网完整 joint JSON | 可写，不称全局 Pareto |
| 7 实验与讨论 | `docs/final_nine_network_paper_data_report.md` | 可写 |
| 限制与有效性威胁 | refinement stability、rho 未标定、conservative timing | 必须保留 |

### 9.3 必须如实写入的最终限制

- CH、DA、EP、LC、PT、SU 达到 objective stability；只有 CH、EP、LC、PT、SU 同时达到 assignment stability。
- DK、GL、IC 在三次 refinement 内未达到 objective/assignment stability；DA 的 objective 稳定但 assignment 未稳定。
- EP、LC、SU 的 observed front 为单点；PT 没有正的内部 chord score，按规则使用 ideal-point fallback。
- `rho=1` 仅是未标定默认场景，不代表真实 ECU；K=41 是更高验证分辨率，不宣称数学收敛。
- routing-excluded 实际计数九网均为 0；这是精确匹配后的事实，而不是省略 routing preprocessing。

### 9.4 仍不进入本轮正文的内容

- 不开始撰写论文正文，只完成证据锁与提纲状态更新。
- 旧九网段、旧 K=21 joint 与 DK/GL/IC 敏感性结果继续仅作 preliminary/sensitivity evidence。
- 不把 GUI 操作流程、未执行的硬件/CANoe 验证或 CAN outer exhaustive 写成已完成工作。