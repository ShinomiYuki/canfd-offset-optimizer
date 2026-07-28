# 论文论断—公式—证明—实验依据总表

> 文档性质：论文写作前的证据账本，不是论文正文。  
> 审计基线：`main`，HEAD `80b9ae3`（2026-07-28 只读核对）。  
> 权威顺序：当前实现与测试 > 最新验证报告 > 最新设计文档 > 旧报告 > `old-1` / `old-2`。

## 1. 使用说明

1. 本表把内容分为数学事实、模型假设、模型内命题、定理、算法性质、工程策略、heuristic 经验性质、实验观察、参数敏感性结论和实现事实；这些类别不能相互替代。
2. “有代码实现”只证明当前程序采用了某规则，不证明该规则是标准要求、物理定律或全局最优方法。
3. “测试通过”可核验实现与已知 oracle/性质一致，不替代定理证明；反之，数学证明也不替代真实网段外部有效性实验。
4. GCLS 外层搜索是 heuristic。除非 CP-SAT 返回 `OPTIMAL` 或完成可枚举空间的穷举，不使用“全局最优”。
5. 联合优化输出称为 **observed/searched Pareto front**；Peak 是 guardrail，不是 Pareto 第三维。
6. “目标值稳定”和“Offset 分配稳定”分别报告：相同 `(Q_ss,P_CPU,Peak)` 不代表 assignment/hash 相同。
7. `output/diagnostics/final_nine_network_baseline/` 已有一次九网段 CAN-only 结果，但它产生于较早提交，且配套报告记录的全量测试门禁并未全绿。该批结果**统一降级为开发期证据**，不作为最终论文数据或主结论依据。
8. 后续正文引用本表时应同时检查“适用前提”“可写强度”和“风险/限制”，不可只摘取“论文论断”列。

## 2. 核心符号表

| 符号 | 最终统一含义 | 单位/取值 | 冲突与统一建议 |
|---|---|---|---|
| \(T_i\) | 周期报文 \(i\) 的周期 | 整数时间 tick，当前工程数据常用 ms | MainFunction 推导必须声明公共整数时间栅格；不可默认为 AUTOSAR 普遍约束 |
| \(O_i\) | 报文 \(i\) 的 Offset/初始释放相位 | 候选集合 \(\mathcal O_i\) 中的整数 tick | 旧稿常把范围固定为 15–100 ms；最终应写成配置给定的候选集合 |
| \(r_{i,k}\) | 第 \(k\) 次释放时刻 | \(r_{i,k}=O_i+kT_i\) | 保留 |
| \(H\) | 稳态分析超周期 | 通常为相关周期的 LCM，或其受控整数倍 | 必须交代 cap/窗口构造；不可把有限窗口结论无条件推广 |
| \(\mathcal O_i\) | 报文 \(i\) 的候选 Offset 集合 | \(\{O_{\min}+k\delta\mid k\in\mathbb Z_{\ge0},\,O_{\min}+k\delta\le O_{\max}\}\)；fixed message 为单元素集合 | 最终产品语义已确定：\(O_{\max}\) 不要求落在步长上，也不强行补入；当前 `config.py` 的整除限制是待统一实现差距 |
| \(\Delta\) | 离散 slot 宽度 | 配置量 | 不与 Offset step 自动混同，除非实验配置明确相等 |
| \(w_i\) | 报文释放权重 | `frame_time_us`、`payload_bytes` 或 `unit` | 主实验建议使用 `frame_time_us`；后两者是近似/敏感性模式 |
| \(L_t\) | slot \(t\) 的聚合释放负载 | 与 \(w_i\) 同量纲 | 用半开区间释放计数构造 |
| \(Z_{\rm ss}\), \(Z_{\rm st}\) | 稳态/启动窗口 Peak | 与 \(w_i\) 同量纲 | “Peak”不表示平均利用率 |
| \(Q_{\rm ss}\), \(Q_{\rm st}\) | 稳态/启动窗口负载平方和 | \(Q=\sum_t L_t^2\) | 取代 `old-1` 的绝对偏差 \(D\)；正文主目标优先写 \(Q_{\rm ss}\) |
| \(N_{\rm vio},V_{\rm vio}\) | 物理阈值超限 slot 数与超限量 | 非负整数/负载量 | 是 lexicographic 前置 guardrail；阈值语义依赖权重 |
| \(D_i\) | 单报文在公共整数原点、精确 tick 对齐下允许的最大基本节拍 | \(D_i=\gcd(T_i,O_i)\) | \(O_i=0\) 时 \(\gcd(T_i,0)=T_i\) |
| \(B_g\) | MainFunction 组 \(g\) 的最大共同 TimeBase | \(B_g=\gcd_{i\in g}D_i\) | 仅在本文调度模型内严格成立 |
| \(N_g\) | 组 \(g\) 中报文数 | 正整数 | 与 D-type 的 multiplicity 区分 |
| \(\rho\) | 固定调度开销与单报文处理开销之比 | \(\rho=C_0/C_1>0\) | 默认 1 是未标定工程参数，不是真实 ECU 参数 |
| \(P_{\rm CPU}\) | CPU cost proxy | \(\sum_g(\rho+N_g)/B_g\) | 不称 CPU utilization/占用率/百分比 |
| \(\epsilon\) | ε-constraint 中的 CPU proxy 上界 | 与 \(P_{\rm CPU}\) 同量纲 | 由 observed endpoints 生成的网格只覆盖已搜索范围 |
| \(K\) | ε 网格点数 | 正整数 | 旧稿固定 21；当前可配置，且 K 敏感性已被观察到 |

## 3. 总体证据矩阵

### 3.1 周期释放、输入边界与 CAN 评价

| ID | 论文论断 | 论断类型 | 适用前提/假设 | 核心公式/定义 | 数学证明状态 | 实验依据 | 当前证据来源 | 可写强度 | 风险/限制 | 建议出现章节 |
|---|---|---|---|---|---|---|---|---|---|---|
| C01 | 周期报文释放时刻由周期和 Offset 决定 | 模型假设 | 周期稳定、以共同离散时间原点建模 | \(r_{i,k}=O_i+kT_i\) | 定义，无需证明 | 单元测试覆盖 slot 展开 | `docs/01_research_and_design.md`; `src/canfd_offset_optimizer/timeline/slot_map.py` | 在本文模型假设下严格陈述 | 不涵盖抖动、事件报文与优先级仲裁响应时间 | 2.1 |
| C02 | 改变 Offset 只平移释放相位，不改变周期 | 模型内命题 | \(T_i\) 和报文集合固定 | \(r_{i,k+1}-r_{i,k}=T_i\) | 可严格证明 | 无需主实验 | 同 C01 | 在本文模型假设下严格陈述 | 不等于实际总线发送完成时刻不变 | 2.1 |
| C03 | Offset 不改变长期平均释放率或平均工作量 | 模型内命题 | 无限时域/完整周期窗口；\(w_i\) 固定 | 单报文平均贡献 \(w_i/T_i\) | 已有完整证明思路；需补正式证明 | 不依赖九网实验；旧结果只作开发期直观核对 | `docs/01_research_and_design.md`; `src/canfd_offset_optimizer/timeline/slot_map.py` | 在本文模型假设下严格陈述 | 有限启动窗口的均值可能受边界影响 | 2.1、8 |
| C04 | Offset 优化不能降低周期集合的长期平均总线负载，只能重塑局部时间分布 | 模型内命题 | 同 C03；不改变 ID/DLC/周期/bitrate | \(\sum_i w_i/T_i\) 与 \(O_i\) 无关 | 需由 C03 推论正式写出 | 不依赖九网实验；旧 CAN-only 结果只作开发期直观核对 | `docs/final_nine_network_report.md`; C03 来源 | 在本文模型假设下严格陈述 | “负载”必须限定平均释放工作量，不能与实际仲裁利用率混称 | 1、2.4、8 |
| C05 | 启动窗口与稳态窗口分开评价 | 工程策略 | 当前窗口定义与超周期构造有效 | 启动 \([0,O_{\max})\)，稳态 \([O_{\max},O_{\max}+H)\) | 定义，无需证明 | 所有 GCLS 报告均输出启动/稳态指标 | `docs/01_research_and_design.md`; `src/canfd_offset_optimizer/timeline/slot_map.py` | 可作为算法设计陈述 | \(H\) 被 cap 时必须披露，不可称完整超周期 | 2.2 |
| C06 | eligible set 由显式本机 sender、周期 TX 条件和 routing exclusion 共同确定 | 模型假设/工程策略 | 每个 DBC 必须选择一个本机发送节点；路由表按“目标网段 + CAN ID”匹配 | \(\mathcal E=\{i\mid i\text{ 为 selected sender 的周期 TX}\}\setminus\{i\mid(\text{target network},\text{CAN ID}_i)\in\mathcal R\}\) | 不应证明/属于正式工程规则 | 旧九网不满足最终 manifest 要求，只作开发期证据；最终九网须重跑 | `docs/03_gui_backend_contract.md`; 用户确认的最终处理规则；当前 parser/loader 只用于记录实现差距 | 可作为算法设计陈述；实验数字待最终九网 | sender manifest 与 routing exclusion 必须进入最终输入 manifest；路由报文不参与 Offset 优化 | 2.3、7.1 |
| C07 | 当前 core 的“首个 sender”与无 routing exclusion 行为不符合最终需求，必须在最终九网重跑前统一 | 实现事实/实现差距 | 以 HEAD `80b9ae3` 核对当前实现，以已确认需求作为目标语义 | 当前 parser/loader 分支规则对比 C06 | 定义，无需证明 | 无论文实验；属于重跑前质量门槛 | `src/canfd_offset_optimizer/parsers/dbc_parser.py`; `src/canfd_offset_optimizer/parsers/project_loader.py` | 当前禁止写成已实现能力 | 论文可以写正式问题边界，但实验必须等代码与 manifest 证明该规则实际生效 | 审计说明、7.1 |
| C08 | 优化决策只改变 Offset；最终 DBC 读写只认 `GenMsgStartDelayTime`，不得以 `GenMsgDelayTime` fallback | 工程策略/实现要求 | ID、DLC、period、sender、bitrate/BRS 不变；parser/writer 在重跑前修正 | 决策变量仅 \(O_i\)；Original baseline 只从 `GenMsgStartDelayTime` 读取 | 定义，无需证明 | 旧九网 Original baseline 存在被 alias fallback 污染的风险，故已降级 | `src/canfd_offset_optimizer/models.py`; `src/canfd_offset_optimizer/parsers/dbc_parser.py`; 用户确认的最终处理规则 | 可作为算法设计陈述；实现能力待修复验证 | parser 与 writer 都必须只使用 StartDelay；修复前不得生成最终 baseline | 2.3、7.1、工程实现短节 |
| C09 | 候选 Offset 是配置给定的截断离散栅格，上界无需整除 step | 模型假设/工程策略 | \(O_{\min}\le O_{\max}\)、\(\delta>0\) | \(\mathcal O=\{O_{\min}+k\delta\mid k\ge0,\ O_{\min}+k\delta\le O_{\max}\}\)；不额外补 \(O_{\max}\) | 定义，无需证明 | 旧实验的 15–100 ms、5 ms 只是该定义的一个整除特例 | `src/canfd_offset_optimizer/config.py`（当前实现差距）；`docs/03_gui_backend_contract.md`; 用户确认的最终处理规则 | 在本文模型假设下严格陈述 | `config.py` 的旧整除限制需在最终九网前统一；正文保持抽象集合，实验节报告具体值 | 2.2、7.1 |
| C10 | 论文释放负载模型兼容 Classic CAN 与 CAN FD；最终九网主实验保持单一已锁定协议口径，若仍为原九网则采用 CAN FD | 模型假设/工程策略 | 每网协议及相应 timing 输入在 manifest 中明确；主实验不临时扩大样本范围 | \(w_i=\widehat t_{\rm frame,i}^{\,\text{protocol}}\) | 不应证明/属于工程模型 | 旧九网 CAN FD 结果仅作开发期证据；Classic CAN 暂无主实验依据 | `src/canfd_offset_optimizer/timing/frame_time.py`; `docs/03_gui_backend_contract.md`; 用户确认的最终处理规则 | 模型兼容性可作为算法设计陈述；实验范围待最终 manifest | Classic CAN 只作工程扩展；当前 source 的协议支持仍需统一；frame time 是 conservative estimate 而非 bit-exact | 2.4、7.1、8 |
| C11 | `payload_bytes` 与 `unit` 是近似敏感性权重，并强制使用 Peak 模式 | 工程策略 | 仅用于诊断/敏感性 | \(w_i={\rm DLC}_i\) 或 1 | 定义，无需证明 | 旧九网 dual-weight 目录仅作开发期证据 | `src/canfd_offset_optimizer/parsers/project_loader.py`; `output/comparison/dual_weight/`; `docs/严格代码审查与验收报告_2026-07-16.md` | 可作为算法设计陈述；实验结论待重跑 | 不应与物理时间占用结果并列主结论 | 7.4/附录 |
| C12 | \(Z_{\rm ss}\) 与 \(Z_{\rm st}\) 衡量局部 slot 峰值，而非平均总线利用率 | 数学事实 | slot-map 和权重已定义 | \(Z=\max_t L_t\) | 可严格证明（定义推论） | 不依赖九网结果；旧 Peak 对比只作开发期证据 | `src/canfd_offset_optimizer/optimization/objective.py`; `docs/final_nine_network_report.md` | 严格陈述 | 物理解释依赖 slot 宽度和权重模式 | 2.4、3.2 |
| C13 | \(Q_{\rm ss}=\sum_tL_t^2\) 衡量稳态分布均衡性；总工作量固定时最小化平方和等价于最小化方差 | 模型内命题 | 同一稳态窗口、slot 数和总负载固定 | \(\operatorname{Var}(L)=Q/n-(\sum L/n)^2\) | 可严格证明；需在正文补一行推导 | Variance 模式在 DK/GL/IC/LC 降低 Qss | `docs/01_research_and_design.md`; `src/canfd_offset_optimizer/optimization/objective.py`; `docs/FINAL_REPORT.md` | 在本文模型假设下严格陈述 | 跨网络/不同窗口的 Qss 不可直接比较 | 2.4、3.3 |
| C14 | Peak 模式当前 lexicographic key 为 \((N_{\rm vio},V_{\rm vio},Z_{\rm ss},Q_{\rm ss},Z_{\rm st},Q_{\rm st},K_{\max})\) | 实现事实 | 当前 objective 定义 | 如左 | 定义，无需证明 | objective-mode 实验 | `src/canfd_offset_optimizer/optimization/objective.py`; `docs/01_research_and_design.md` | 可作为算法设计陈述 | `old-1` 的绝对偏差 \(D\) 与顺序已过时 | 3.4 |
| C15 | Variance 模式把 \(Q_{\rm ss}\) 置于 \(Z_{\rm ss}\) 前 | 实现事实 | 当前 objective 定义 | \((N_{\rm vio},V_{\rm vio},Q_{\rm ss},Z_{\rm ss},Z_{\rm st},Q_{\rm st},K_{\max})\) | 定义，无需证明 | DK/GL/IC/LC 观察到 Qss 改善且 Peak 可能升高 | 同 C14；`docs/FINAL_REPORT.md` | 可作为实验观察陈述 | 不能称全面优于 Peak | 3.4、7.3 |
| C16 | Balanced 在 Peak reference 的预算内优化 Qss，并保留违规与 reference 不退化 guardrail | 算法性质 | Peak reference、相对/绝对预算和候选池已定义 | relative 时 \(Z_{\rm budget}=\lceil Z_{\rm ref}(1+\tau)\rceil\)；key 为 \((N_{\rm vio},V_{\rm vio},\text{budget excess},Q_{\rm ss},Z_{\rm ss},Z_{\rm st},Q_{\rm st},K_{\max})\)，最终还要求违规不劣于 reference 且 \(Q_{\rm ss}\le Q_{\rm ref}\) | 定义与代码可核验 | 旧九网 5% 结果仅作开发期证据 | `src/canfd_offset_optimizer/models.py`; `src/canfd_offset_optimizer/optimization/objective.py`; `src/canfd_offset_optimizer/optimization/gcls.py`; `docs/FINAL_REPORT.md` | 可作为算法设计陈述；实验结论待重跑 | 开发期 search 未找到改善不等于预算内不存在改善；reference 是 heuristic observed | 3.4、7.3 |
| C17 | conservative occupancy 只适合作为优化后诊断/安全解释，不应伪装成精确仲裁或 schedulability 分析 | 工程策略 | 使用保守 frame-time 模型 | 诊断量由 frame-time estimate 派生 | 不应证明/属于工程假设 | weight/conservative timing 诊断 | `docs/严格代码审查与验收报告_2026-07-16.md`; `src/canfd_offset_optimizer/timing/frame_time.py` | 只能弱陈述 | 无 CAN 仲裁、响应时间和误码重传模型 | 2.4、8 |

### 3.2 GCLS 与既有 CAN-only 实验

| ID | 论文论断 | 论断类型 | 适用前提/假设 | 核心公式/定义 | 数学证明状态 | 实验依据 | 当前证据来源 | 可写强度 | 风险/限制 | 建议出现章节 |
|---|---|---|---|---|---|---|---|---|---|---|
| C18 | GCLS 先进行确定性 greedy construction，再作局部搜索 | 算法性质 | 固定输入排序和 tie-break | 每次选择当前 objective key 最小的候选 | 可由伪代码说明 | 九网段 Original/Greedy/GCLS 分解 | `src/canfd_offset_optimizer/optimization/gcls.py`; `docs/01_research_and_design.md` | 可作为算法设计陈述 | greedy 不是最优性证明 | 4.1 |
| C19 | 1-opt 以精确增量更新并在不改善时回滚，结束时对其实际扫描邻域达到单报文搬移局部最优 | 算法性质 | 有限候选集合；严格改善接受；扫描完成 | \(\Delta Q\) 由受影响 slots 精确计算 | 已有完整证明思路；需补终止与局部最优命题 | 单元测试及严格审查 | `src/canfd_offset_optimizer/optimization/local_search.py`; `docs/严格代码审查与验收报告_2026-07-16.md` | 在本文算法定义下严格陈述 | 仅对实现的 1-opt 邻域与 comparator；后续 pair/三元不获全局保证 | 4.2、4.5 |
| C20 | conflict-directed pair search 只枚举受冲突启发的有限候选对，并要求两报文都移动 | heuristic 经验性质 | 当前冲突候选生成规则 | 接受严格改善 pair move，随后再 1-opt | 不能严格证明效果，只能实验支持 | 旧九网的 5/9 改善仅作开发期证据 | `src/canfd_offset_optimizer/optimization/local_search.py`; `docs/final_nine_network_report.md` | 算法设计可写；效果结论待最终九网 | 不是完整 2-opt 枚举，也不保证 2-opt 局部最优 | 4.3 |
| C21 | restart 首次确定性、后续仅打乱等周期且等权组，当前默认采用 20/10/20/80 自适应尝试策略 | 算法性质 | 固定 seed 与 restart policy | 分段尝试上限与停滞升级 | 定义，无需证明 | DK 30×80 restart stability；当前单测核对 exact attempt count 和 resume | `src/canfd_offset_optimizer/optimization/gcls.py`; `tests/unit/test_restart_audit.py`; `docs/严格代码审查与验收报告_2026-07-16.md` | 可作为算法设计陈述 | `old-1` 固定 \(K=20\) 过时；80 次未证明饱和 | 4.4 |
| C22 | 固定输入、配置与 seed 时搜索和审计记录可复现 | 算法性质 | 不比较 wall-clock；依赖版本/环境锁定 | assignment/objective/hash 与 JSONL 记录 | 测试支持实现性质 | restart audit tests | `tests/unit/test_restart_audit.py`; `src/canfd_offset_optimizer/optimization/gcls.py` | 可作为算法设计陈述 | 跨版本、求解器版本或浮点外部依赖不作无条件保证 | 4.5、7.1 |
| C23 | candidate pool 通过多个 Peak 候选为 Balanced 提供相位多样性 | 工程策略 | pool size 可配置，候选受 guardrail 约束 | farthest-first phase diversity | 不能严格证明效果，只能实验支持 | DK pool=4 使 Qss 17,384,489→17,079,489；GL/IC 无改善 | `tests/unit/test_restart_audit.py`; `docs/严格代码审查与验收报告_2026-07-16.md`; `output/diagnostics/*/candidate_pool_study/` | 可作为实验观察陈述 | 仅三网开发期诊断，效果不普遍 | 4.4 或附录 |
| C24 | 3-opt 已实现但默认关闭，只宜作为消融而非主体算法必要步骤 | 实现事实 | `enable_triple_search=false` | bounded triple candidate search | 定义，无需证明 | IC Qss 44,001,873→42,940,673；DK/GL 无改善 | `src/canfd_offset_optimizer/config.py`; `docs/严格代码审查与验收报告_2026-07-16.md`; `output/diagnostics/*/triple_ablation_optimized/` | 只能弱陈述 | 仍未达到 CP-SAT feasible 解；计算成本与收益不稳定 | 附录/删除主体 |
| C25 | GCLS 是 heuristic，不保证全局最优 | heuristic 经验性质 | 外层未穷举、无 admissible bound | — | 不能严格证明“最优”；可严格说明无最优性证书 | CP-SAT 在 DK/GL/IC 找到更低 feasible Qss | `src/canfd_offset_optimizer/optimization/gcls.py`; `docs/严格代码审查与验收报告_2026-07-16.md`; `output/diagnostics/*/cpsat/` | 严格陈述其限制 | 不能反向断言 CP-SAT feasible 解为全局最优 | 4.5、8 |
| C26 | 当前 CP-SAT 结果只提供 better-feasible 诊断，不提供 DK/GL/IC 全局最优证书 | 实验观察 | CP-SAT 状态均为 `FEASIBLE` 而非 `OPTIMAL` | 预算下最小化 Qss | 不能严格证明，只能实验支持 | DK/GL/IC CP-SAT diagnostics | `docs/严格代码审查与验收报告_2026-07-16.md`; `src/canfd_offset_optimizer/diagnostics/cpsat_verify.py`; `output/diagnostics/*/cpsat/` | 可作为实验观察陈述 | 不可写 optimality gap 为零 | 7.5/附录 |
| C27 | 开发期九网段 CAN-only 基线中，Peak 相对 Original 在 DA/DK/GL/IC/LC/PT 改善，在 CH/EP/SU 未改善 | 实验观察 | 2026-07-27 旧数据与当时脚本；不满足最终 manifest 口径 | 改善率见旧报告/CSV | 不能严格证明，只能实验支持 | 开发期观察：6/9 改善；28.85%、38.07%、38.07%、33.41%、23.50%、33.54% | `docs/final_nine_network_report.md`; `output/diagnostics/final_nine_network_baseline/results/` | 只能作为开发期证据，禁止进入最终主结论 | 较早 commit、门禁不干净、sender/routing/StartDelay 口径未锁定；必须统一 manifest 后重跑 | 开发期审计/附录候选，不填 7.3 |
| C28 | 开发期九网段中 GCLS 相对 Greedy 的 Peak 改善出现在 DA/DK/GL/IC/LC（5/9） | 实验观察 | 同 C27 | \(Z_{\rm greedy}-Z_{\rm GCLS}\) | 不能严格证明，只能实验支持 | 旧 CAN-only baseline | 同 C27 | 只能作为开发期证据，禁止进入最终主结论 | 不能把 CH/EP/SU 的“未改善”写成已达最优；最终统一 manifest 后重跑 | 开发期审计/附录候选 |
| C29 | 开发期九网段在 5% budget 下 Balanced 与 Peak 的汇总指标完全相同 | 实验观察 | 当时 Balanced 实现、seed/restart/pool 和旧输入口径 | objective 指标相等 | 不能严格证明，只能实验支持 | 开发期观察：9/9 相同 | `docs/FINAL_REPORT.md`; raw/summary CSV | 只能作为开发期证据，禁止进入最终主结论 | assignment 仍应单独比对；最终统一 manifest 重跑前不能推论 Balanced 一般无效 | 开发期审计/附录候选 |
| C30 | tolerance scan 只证明首次观察到改善的预算位置，不证明阈值或饱和 | 参数敏感性结论 | 开发期扫描范围至 20% | 旧结果中 DK 首次 10%，IC 首次 15% | 不能严格证明，只能实验支持 | 旧九网 tolerance scan 仅作开发期证据 | `docs/严格代码审查与验收报告_2026-07-16.md`; `output/diagnostics/*/tolerance_scan/` | 只能作为开发期证据；最终结论待重跑 | 其余网络“至 20% 未改善”不是不存在改善 | 附录 |
| C31 | restart 稳定性必须同时报告 objective hit-rate 与 assignment diversity | 参数敏感性结论 | 多 seed/重复批次、相同配置 | hit-rate；hash/Offset 差异 | 不能严格证明，只能实验支持 | DK 30×80：best objective 13/30；Balanced 1/30；跨批 reference 变化 | `docs/严格代码审查与验收报告_2026-07-16.md`; `output/diagnostics/DK/restart_stability/` | 可作为实验观察陈述 | “稳定”不得只看一个 objective 元组 | 7.4/附录 |

### 3.3 Offset–MainFunction 模型与 exact 子问题

| ID | 论文论断 | 论断类型 | 适用前提/假设 | 核心公式/定义 | 数学证明状态 | 实验依据 | 当前证据来源 | 可写强度 | 风险/限制 | 建议出现章节 |
|---|---|---|---|---|---|---|---|---|---|---|
| C32 | 精确周期回调可执行报文 \(i\) 的条件是 \(B\mid T_i\) 且 \(B\mid O_i\) | 模型假设 | 公共 scheduling origin、整数 tick、exact tick alignment、无抖动 | 整除条件 | 不应证明/属于工程模型假设 | 无需实验 | `docs/can_cpu_joint_design.md`; `docs/main_function_exact_solver_report.md` | 在本文模型假设下严格陈述 | 不是 AUTOSAR 规范强制规则 | 2.5、5.1 |
| C33 | 在上述模型下单报文最大可行节拍为 \(D_i=\gcd(T_i,O_i)\) | 模型内命题 | 同 C32 | \(B\mid T_i,O_i\Rightarrow B\le\gcd(T_i,O_i)\) | 已有完整证明思路；需补正式命题 | exact solver tests 间接核验 | `src/canfd_offset_optimizer/optimization/main_function.py`; `docs/main_function_exact_solver_report.md` | 在本文模型假设下严格陈述 | \(O_i=0\) 边界需显式定义 | 5.2 |
| C34 | 固定报文组 \(g\) 的最大共同 TimeBase 为 \(B_g=\gcd_{i\in g}D_i\) | 模型内命题 | 同 C32；组内共用一个周期任务 | 公约数最大性 | 已有完整证明思路；需补正式命题 | 单元测试/小规模 oracle | 同 C33 | 在本文模型假设下严格陈述 | 仅说明可行节拍，不说明运行时调度开销真实值 | 5.3 |
| C35 | 理论 CPU 调度开销形式可写为 \(U_{\rm CPU}=\sum_g C_g/B_g\) | 模型假设 | 每组每次回调成本 \(C_g\)，忽略其他 ECU 负载 | 如左 | 不应证明/属于工程假设 | 无真实 ECU 标定 | `docs/can_cpu_joint_design.md`; `docs/main_function_exact_solver_report.md` | 只能弱陈述 | 不得称实际 CPU utilization | 5.4、8 |
| C36 | 用 \(C_g\approx C_0+C_1N_g\) 且 \(\rho=C_0/C_1\) 可得比例意义上的 \(P_{\rm CPU}=\sum_g(\rho+N_g)/B_g\) | 模型假设 | 线性组固定开销+逐报文开销模型；\(C_1>0\) | 如左 | 代数变换可严格证明；模型本身不可证明 | rho sensitivity，无硬件测量 | `src/canfd_offset_optimizer/optimization/main_function.py`; `docs/can_cpu_joint_design.md` | 在本文模型假设下严格陈述 | 只能比较 proxy；不同 rho 代表不同开销假设 | 5.4 |
| C37 | naive \(\sum_gN_g/B_g\) 会低估过度拆组代价，加入 \(\rho/B_g\) 抑制无代价拆分 | 模型内命题 | \(\rho>0\)，比较拆分前后 fixed overhead | 拆组增加至少一个固定项，但可能改变 \(B_g\) | 需要补正式命题并限定条件 | rho 变化使组数明显改变 | `docs/can_cpu_joint_design.md`; `docs/can_cpu_joint_validation_report.md` | 只能弱陈述，证明后可加强 | 不能无条件声称任何拆分都更差，因为 \(B_g\) 可能增大 | 5.4 |
| C38 | 固定 Offset 后，MainFunction partition 子问题由 \(D_i\) 多重集合决定 | 模型内命题 | cost 仅依赖组内 \(D_i\)、组大小和 rho | group cost \((\rho+N_g)/\gcd(D_i)\) | 需要补正式证明 | brute-force oracle 支持 | `src/canfd_offset_optimizer/optimization/main_function.py`; `docs/main_function_exact_solver_report.md` | 在本文模型假设下严格陈述 | 若未来 cost 引入报文异质开销则不成立 | 5.5 |
| C39 | 存在一个最优 partition 不拆分相同 \(D\) 类型（D-type compression） | 定理 | 当前 group cost；相同 D 报文完全可交换 | multiplicity 压缩 | 已有证明思路；需要补形式化交换/合并证明 | 141 次 brute-force 比对一致 | 同 C38；`tests/unit/test_main_function.py` | 在本文模型假设下严格陈述（补证明后） | 测试不是证明；需覆盖 rho 和 multiplicity 条件 | 5.5 |
| C40 | subset-DP 用 anchor 限定当前子集以避免重复 partition，并具有 optimal substructure | 算法性质 | D-type 压缩后的有限集合；精确 Fraction cost | \(F(S)=\min_{A\subseteq S,a(S)\in A}\{c(A)+F(S\setminus A)\}\) | 已有完整证明思路；需补 recurrence 与不重不漏证明 | 141 次小规模 oracle | `src/canfd_offset_optimizer/optimization/main_function.py`; `docs/main_function_exact_solver_report.md` | 在本文模型假设下严格陈述 | tie-break 不改变最小 cost，但需单独说明 canonical 输出 | 5.6 |
| C41 | 当前 MainFunction solver 对所定义 proxy 子问题是 exact，时间复杂度 \(O(3^m)\)、空间复杂度 \(O(2^m)\) | 定理/算法性质 | \(m\) 为 distinct D-type 数；无限资源下完成 DP | subset 枚举计数 | 需要补正式归纳证明与复杂度推导 | \(m=4\ldots6\) 九网 <1 ms；合成 \(m=12\) 约451 ms、\(m=13\) 约1379 ms | `docs/main_function_exact_solver_report.md`; `src/canfd_offset_optimizer/optimization/main_function.py` | 在本文模型假设下严格陈述 | exact 只针对 inner partition，不使外层 Offset 搜索 exact；scaling 数字依硬件环境 | 5.6、7.6 |
| C42 | 141 次 brute-force 比对是实现正确性的交叉验证，不是 exactness 定理证明 | 实验观察 | \(n=1\ldots7\)，每个 rho 档 47 个样本，rho 为 1/2、1、3 | exact cost 相等 | 不能替代理论证明 | 141/141 一致 | `docs/main_function_exact_solver_report.md`; `tests/unit/test_main_function.py` | 可作为实验观察陈述 | 样本空间有限 | 7.6 |
| C43 | \(T_i>O_{\max}\Rightarrow O_i=0\) 是项目 long-period 工程策略；fixed message 仍进入 CAN 与 CPU 评价 | 工程策略 | 当前 joint domain 构造 | 长周期候选集合 \(\{0\}\) | 不应证明/属于工程策略 | DK/GL/IC joint validation 使用该规则 | `src/canfd_offset_optimizer/optimization/joint.py`; `docs/can_cpu_joint_design.md` | 可作为算法设计陈述 | 非 AUTOSAR 要求、非数学必然；CAN-only core 与 joint policy 的适用范围要区分 | 2.3、6.1、8 |

### 3.4 CAN–CPU 联合优化、refinement、Pareto 与 knee

| ID | 论文论断 | 论断类型 | 适用前提/假设 | 核心公式/定义 | 数学证明状态 | 实验依据 | 当前证据来源 | 可写强度 | 风险/限制 | 建议出现章节 |
|---|---|---|---|---|---|---|---|---|---|---|
| C44 | 联合问题采用 ε-constraint：在 Peak guardrail 和 \(P_{\rm CPU}\le\epsilon\) 下最小化 \(Q_{\rm ss}\) | 模型假设 | exact inner evaluator；heuristic outer search | \(\min Q_{\rm ss}\), s.t. \(Z\le Z_{\rm budget},P\le\epsilon\) | 定义，无需证明 | DK/GL/IC joint experiments | `src/canfd_offset_optimizer/optimization/joint.py`; `docs/can_cpu_joint_optimization_report.md` | 可作为算法设计陈述 | 外层仍 heuristic；可行点集只是已搜索点 | 6.2–6.3 |
| C45 | 采用 ε-constraint 而非 \(\alpha Q+\beta P\)，是为了保留各指标量纲并显式控制 CPU 上界 | 工程策略 | epsilon 可解释、endpoints 可生成网格 | 逐 \(\epsilon\) 约束 | 不应证明/属于方法选择 | 当前联合实验能输出多预算点 | `docs/can_cpu_joint_design.md`; `src/canfd_offset_optimizer/optimization/joint.py` | 可作为算法设计陈述 | 不证明 ε-grid 覆盖所有非凸 Pareto 点 | 6.3 |
| C46 | 初始 CAN/CPU anchors 是 heuristic observed anchors，后续 epsilon 候选可以支配它们 | heuristic 经验性质 | 外层 GCLS/search 未穷举 | observed CAN/CPU endpoint | 不能严格证明，只能实验支持 | 早期 GL/IC anchor 被后续候选支配 | `docs/can_cpu_joint_optimization_report.md`; `docs/can_cpu_joint_validation_report.md` | 可作为实验观察陈述 | `old-2` 的 `argmin` 写法错误 | 6.4 |
| C47 | cumulative archive 跨初始点、epsilon search 和 refinement pass 保存 observed assignments，并据此更新 endpoints | 算法性质 | assignment hash 去重、精确 objective 排序 | archive union + representative selection | 可由算法定义核验 | DK/GL/IC validation | `src/canfd_offset_optimizer/optimization/joint.py`; `tests/unit/test_joint.py` | 可作为算法设计陈述 | archive 完整性仅相对于已执行搜索，不等于全空间 | 6.4 |
| C48 | refinement 同时允许 Peak reference、epsilon budgets 和 endpoints 随 archive 更新 | 算法性质 | 最大 pass、精确 budget 与 signature 规则 | 相邻 pass signature 比较 | 定义与测试可核验 | baseline 3 passes：DK 31、GL 33、IC 16 observed points | `src/canfd_offset_optimizer/optimization/joint.py`; `docs/can_cpu_joint_validation_report.md` | 可作为算法设计陈述 | 三网络均触及 pass limit，不能称完全收敛 | 6.4、7.7 |
| C49 | refinement convergence 与 limit 必须区分；objective stability 与 assignment stability 也必须分开 | 参数敏感性结论 | 比较 endpoint/front objective 和 hashes | signature 含 Peak key/hash、预算、endpoint、Pareto objectives/hashes | 定义与实验均有依据 | 三网络触及 pass limit；IC seed2 同 objective 不同 assignment；IC attempts=10 hit limit | `src/canfd_offset_optimizer/optimization/joint.py`; `docs/can_cpu_joint_validation_report.md` | 可作为实验观察陈述 | 不得以目标值不变宣称分配唯一或搜索收敛 | 6.4、7.8、8 |
| C50 | Pareto dominance 只在较低 \(Q_{\rm ss}\) 与较低 \(P_{\rm CPU}\) 两维定义，至少一维严格改善；Peak 仅为 guardrail | 数学事实/模型定义 | 所有候选先满足 Peak budget | \(a\prec b\iff Q_a\le Q_b,P_a\le P_b\) 且至少一项严格 | 定义，无需证明 | front filtering tests | `src/canfd_offset_optimizer/optimization/joint.py`; `tests/unit/test_joint.py` | 严格陈述 | 不把 MainFunction count 或 Peak 加入几何维度 | 6.5 |
| C51 | 当前输出是 refined observed Pareto front，不是 global Pareto frontier | heuristic 经验性质 | 外层搜索有限、inner exact | 对 archive 做 non-dominated filter | 可严格说明其集合性质；不可证明全局完备 | seed/K/rho/refinement sensitivity 均显示 front 可变 | `docs/can_cpu_joint_validation_report.md`; `src/canfd_offset_optimizer/optimization/joint.py` | 严格陈述其限制 | “exact inner”不能外推成“joint exact” | 6.5、8 |
| C52 | knee 在最终 observed front 上按精确归一化坐标计算 \(s=1-x-y\)，选择最大正 chord score 的内部点 | 算法性质 | front 至少 3 点，Q/P spans 有定义 | \(x=(Q-Q_{\min})/(Q_{\max}-Q_{\min})\)，\(y=(P-P_{\min})/(P_{\max}-P_{\min})\) | 定义与 Fraction 排序可核验 | knee unit tests；DK/GL/IC validation | `src/canfd_offset_optimizer/optimization/joint_analysis.py`; `tests/unit/test_joint_analysis.py` | 可作为算法设计陈述 | 归一化依赖当前 observed endpoints；knee 随 front 变化 | 6.6 |
| C53 | 无正 geometric knee 时选内部 ideal-point fallback；1 点返回唯一 observed 解；2 点明确不推荐内部 knee；空 front 不推荐 | 算法性质 | 当前后处理规则 | ideal distance \(x^2+y^2\)；严格 tie-break | 定义与测试可核验 | dedicated unit tests | 同 C52 | 可作为算法设计陈述 | “unique solution”指 observed front 唯一点，不是全局唯一；fallback 不是 knee | 6.6 |
| C54 | knee 只是后处理，不参与 GCLS objective、约束、候选筛选或 refinement | 实现事实 | 当前模块边界 | `joint_analysis.py` 只读取最终 front | 定义，无需证明 | unit tests | `src/canfd_offset_optimizer/optimization/joint_analysis.py` | 可作为算法设计陈述 | 不得暗示 knee 引导搜索得到前沿 | 6.6 |
| C55 | \(K=21\) 的 observed front 还不具备 validation-grade 稳定性 | 参数敏感性结论 | DK/GL/IC K=21 vs 41、同一验证配置 | normalized Hausdorff distance | 不能严格证明，只能实验支持 | DK 0.186824、GL 0.089373、IC 0.131505；knees 均移动 | `docs/can_cpu_joint_validation_report.md`; `src/canfd_offset_optimizer/optimization/joint_analysis.py` | 可作为实验观察陈述 | 只覆盖三网络；距离受共同归一化定义影响 | 7.8、8 |
| C56 | seed 对 objective front 和 assignment 的影响不同 | 参数敏感性结论 | seed 0/1/2 对比 | Hausdorff + assignment hash | 不能严格证明，只能实验支持 | DK H=0；GL seed1/2 H=0.049434 且 knee 变；IC objective H=0 但 seed2 assignment 变 | `docs/can_cpu_joint_validation_report.md` | 可作为实验观察陈述 | 三网络 preliminary；需九网段扩展 | 7.8、8 |
| C57 | rho 显著改变 MainFunction 分组数与结构，因而默认 \(\rho=1\) 不能被解释为真实 ECU 参数 | 参数敏感性结论 | 已测试 rho grid、proxy 模型不变 | \(\rho=C_0/C_1\) | 不能严格证明外部真实性；内部趋势可分析 | DK/GL/IC rho validation，高 rho 下组数减少 | `docs/can_cpu_joint_validation_report.md` | 可作为实验观察陈述 | 缺硬件 \(C_0,C_1\) 标定；最终工程推荐必须条件化 | 5.4、7.8、8 |
| C58 | 当前 joint 证据只覆盖 DK/GL/IC，不能支撑九网段联合效果、总体 front 统计或总体 knee 结论 | 实验观察/证据缺口 | 现有 validation 范围 | — | 不能严格证明，只能描述证据范围 | 3 网络 preliminary | `docs/can_cpu_joint_optimization_report.md`; `docs/can_cpu_joint_validation_report.md`; `output/diagnostics/can_cpu_joint_validation/` | 当前禁止写入最终结论 | 最关键实验缺口 | 7.7–7.8、9 |
| C59 | 当前测试状态可证明的仅是最新 joint validation 报告记录的 176 passed、ruff/mypy 通过 | 实现事实 | 对应报告的 commit/environment | quality gate record | 定义，无需证明 | 最新报告 | `docs/can_cpu_joint_validation_report.md` | 只能弱陈述 | 不替代最终数据复跑；旧 `FINAL_REPORT.md` 的 78 passed/2 failed/48 errors 与“门禁通过”自相矛盾 | 实验可复现性说明 |

## 4. 当前论文禁止直接写出的结论

| 禁止句式 | 为什么不能这样写 | 推荐安全改写 |
|---|---|---|
| Offset 优化降低了平均总线负载。 | \(O_i\) 不改变 \(T_i,w_i\)，长期平均贡献不变。 | Offset 重分配周期释放相位，降低或平滑局部离散时间窗内的聚集。 |
| GCLS 得到全局最优 Offset。 | GCLS 是有限 restart 的 heuristic，无全局下界或完备枚举。 | GCLS 在给定预算与配置下得到 observed/best-found 解。 |
| Balanced 得到最优负载分配。 | Peak reference 与外层搜索均为 heuristic；当前 9 网结果甚至与 Peak 相同。 | Balanced 在 observed Peak budget 内搜索较低 Qss 的可行分配。 |
| CH/EP/SU 未改善说明原方案最优或接近最优。 | 未改善只说明当前搜索未找到更好解。 | 在本次配置与搜索预算下未观察到 Peak 改善。 |
| CP-SAT 证明了 DK/GL/IC 的全局最优值。 | 状态为 `FEASIBLE`，不是 `OPTIMAL`。 | CP-SAT 找到了比 GCLS 更低 Qss 的可行诊断解，但未给出最优证书。 |
| 本文得到全局 Pareto 前沿。 | 外层 Offset 空间未穷举。 | 本文对累计搜索 archive 提取 observed Pareto front。 |
| exact MainFunction solver 使联合优化成为 exact。 | 仅固定 Offset 的 inner partition 是 exact。 | 联合方法采用 exact inner evaluator 与 heuristic outer search。 |
| CPU Proxy 就是 ECU CPU 占用率/百分比。 | 未标定 \(C_0,C_1\)，也未建模完整 ECU 任务。 | \(P_{\rm CPU}\) 是本文假设下的相对调度成本 proxy。 |
| AUTOSAR 规定 TimeBase 必须等于 gcd。 | gcd 来自公共整数原点与 exact tick alignment 的本文工程模型。 | 在本文调度模型下，最大可行节拍由 gcd 给出。 |
| \(T_i>O_{\max}\) 的报文必须 Offset=0。 | 这是为控制联合空间采用的工程策略。 | 本实现将长周期报文固定为 Offset=0，并在讨论中评估其影响。 |
| \(\rho=1\) 是真实 ECU 的合理参数。 | 未做硬件标定，且 rho sensitivity 显著。 | \(\rho=1\) 是默认未标定场景；结论需随 rho 条件化。 |
| K=21 已足以稳定复现 Pareto 和 knee。 | K=21/41 的 Hausdorff 距离非零且 knee 移动。 | K 敏感性表明当前网格仍影响 observed front 和推荐。 |
| knee 是唯一工程最优方案。 | 它依赖 observed front、归一化和几何规则。 | knee 是当前 observed front 上的解释性几何折中推荐。 |
| objective 相同证明 Offset 分配稳定/唯一。 | IC 已出现同 objective 不同 assignment。 | 分别报告 objective-front 距离和 assignment hash 多样性。 |
| conservative occupancy 是精确 CAN FD 帧时或 schedulability 结果。 | 当前是保守估计且不含仲裁/阻塞/重传。 | 将其作为统一权重或后验保守诊断，并明确模型边界。 |
| 当前版本已经完整实现 sender selection、routing exclusion 和规范 DBC 写回。 | 最终需求已经确定，但 HEAD `80b9ae3` 的 core 尚未全部符合；“需求已裁决”不等于“实现已完成”。 | 论文可按正式规则定义 eligible set；最终实验必须在实现修复、测试和统一 manifest 后执行。 |
| 九网段联合实验已验证方法普适有效。 | 当前九网段只有 CAN-only baseline，joint 仅 DK/GL/IC。 | 现有三网 preliminary 结果显示可搜索到 tradeoff；总体结论等待九网段联合数据。 |
| 所有质量门禁在最终九网段运行时均通过。 | `FINAL_REPORT.md` 同时记录 78 passed、2 failed、48 errors 和“通过”，自相矛盾。 | 分开报告该次数据生成状态与最新 176-test validation 状态，并在最终复跑中重新锁定。 |

## 5. 正式论文需要补出的证明

- [ ] **Proposition P1：Offset 不改变长期平均释放率。** 已有直接计数/极限证明思路；正式写明无限时域或整数个周期窗口条件，并处理有限边界误差。
- [ ] **Corollary P2：Offset 不改变周期集合长期平均工作量。** 由 P1 对固定 \(w_i\) 求和；明确不是实际仲裁利用率证明。
- [ ] **Proposition P3：固定总负载时最小化 \(Q_{\rm ss}\) 等价于最小化 slot-load 方差。** 一行代数足够，但需声明窗口长度和总和固定。
- [ ] **Proposition P4：1-opt 的有限终止与局部最优。** 用有限状态空间、严格 lexicographic 改善证明；局部最优范围限定为实际枚举的单报文 relocation 邻域。
- [ ] **Proposition P5：单报文最大精确调度节拍 \(D_i=\gcd(T_i,O_i)\)。** 证明“可行”和“最大”两部分，显式处理 \(O_i=0\)。
- [ ] **Proposition P6：固定 group 的最大 TimeBase \(B_g=\gcd_{i\in g}D_i\)。** 由共同整除条件推出。
- [ ] **Proposition P7：naive \(\sum N_g/B_g\) 的拆分偏置。** 目前只能给条件化命题；需精确界定何时“无固定开销会偏向拆分”，避免声称所有拆分都降低成本。
- [ ] **Proposition P8：D-type sufficient statistic。** 证明在当前 cost 下同一 \(D\) 的报文可交换且 multiplicity 足够描述子问题。
- [ ] **Lemma P9：same-D compression。** 需要正式交换/合并论证，证明至少存在一个不拆分同 D-type 的最优 partition；141 次 oracle 仅作佐证。
- [ ] **Lemma P10：anchor subset 枚举不重不漏。** 每个 partition 中包含 canonical anchor 的 block 唯一。
- [ ] **Theorem P11：subset-DP exactness。** 对 D-type 子集大小归纳，证明 optimal substructure、recurrence 完备性和 base case。
- [ ] **Proposition P12：subset-DP 复杂度。** 给出所有状态的 anchor-subset 总枚举量为 \(O(3^m)\)，存储 \(O(2^m)\)；区分 distinct types \(m\) 与报文数 \(n\)。
- [ ] **Lemma P13：Pareto filter 的正确性。** 可简短证明输出正好是 archive 内二维 non-dominated representatives；不要外推到全空间。
- [ ] **Definition audit P14：geometric knee。** 不需要“最优性证明”；只需证明 exact Fraction tie-break 的确定性，并说明 0/1/2 点和 fallback 的定义。

## 6. 已裁决的处理规则、实现差距与最终数据门槛

### 6.1 已裁决的处理规则

| 事项 | 当前 source 事实 | 最终确定规则 | 重跑前动作与论文处置 |
|---|---|---|---|
| sender selection | parser 接口无 selected sender，当前取首个具体 sender | 每个 DBC 必须显式选择本机发送节点 | 修正 parser/loader 并为九网逐一建立 sender manifest；论文系统模型直接采用显式 sender 规则 |
| routing exclusion | core 无 routing Excel parser/排除逻辑 | 按“目标网段 + CAN ID”匹配路由表并排除；路由报文不参与 Offset 优化 | 实现并测试排除逻辑；manifest 记录规则、输入 hash、排除数量与原因 |
| Classic CAN / CAN FD | current parser 对周期非 CAN FD TX 抛 `UnsupportedMessageError` | 论文模型兼容两者；最终九网主实验保持统一口径，若仍用原九网则保持 CAN FD；Classic CAN 只作工程扩展 | 不为展示工具能力临时扩大主实验；manifest 逐网锁定协议和 timing |
| Offset 上界 | `config.py` 要求区间差可被 step 整除 | 候选为 \(O_{\min}+k\delta\le O_{\max}\)；max 无需命中 step，也不强行补 max | 后续统一旧整除限制；论文正文只写抽象 \(\mathcal O_i\)，实验节给具体参数 |
| StartDelay 字段 | parser 接受 `GenMsgStartDelayTime`、`GenMsgDelayTime` 等 aliases；repo 未见 writer | Offset 只认 `GenMsgStartDelayTime`；parser 不得 fallback，writer 也只能写该字段 | 作为阻断最终九网重跑的 bug 修复；修复前的 Original baseline 不具备最终证据资格 |
| 旧九网段结果 | 对应旧 commit，且质量门禁记录不干净 | 全部降级为开发期证据，不作为最终论文数据 | 可保留作诊断线索，不能填主结果、摘要或结论 |
| 最终九网段 | CAN-only 旧九网与 DK/GL/IC joint validation 分属不同证据批次 | 建立一份统一 manifest；CAN-only 与 CAN/CPU joint 均使用同一九网、sender、routing exclusion、权重、Offset 参数、commit 和输入 hash | 只在该 manifest 下产生最终正文数字；两条实验链共享输入资格与 provenance |

### 6.2 进入最终论文结论前必须补齐

1. 一份统一的最终九网 manifest：同一九网、显式 sender、按“目标网段 + CAN ID”的 routing exclusion、统一协议口径、权重、Offset 参数、commit 和全部输入 hash。
2. 基于该 manifest 的 CAN-only 结果，以及同源的 joint archive、observed endpoints、front count、refinement status 和 knee/fallback。
3. 至少能解释 K/seed 对九网主结论的影响；不能只选择 DK/GL/IC 的有利结果。
4. rho 作为情景参数的九网汇总；若无硬件标定，结论全部写成 sensitivity。
5. 明确 `frame_time_us` 输入的 nominal/data bitrate、BRS、DLC 缺失处理；主实验锁定单一协议口径，Classic CAN 仅作为模型兼容和工程扩展。
6. 对同目标不同 assignment 的比例、hash 多样性和 objective-front 稳定性分别汇报。
7. parser/writer 只使用 `GenMsgStartDelayTime`，并通过 Original baseline 针对性回归测试；最终质量门禁不得沿用旧报告中自相矛盾的“通过”判定。

## 9. 最终九网段数据状态更新（2026-07-28）

> 本节是对前文“待统一”“待最终九网段数据”等状态的最终更新，不删除历史冲突记录。

### 9.1 已解决的输入与证据缺口

- **C06/C07（eligible set）已解决**：最终入口强制逐网显式指定 `selected_sender=FLZCU`，按规范化目标网段、数值 CAN ID 与 extended flag 精确执行 routing exclusion；证据为 `docs/final_nine_network_manifest.yaml`、`src/canfd_offset_optimizer/final_experiment.py` 和 `output/final_paper_nine_network/preflight/`。
- **C08（Original Offset）已解决**：parser 只接受 `GenMsgStartDelayTime` 显式值或其 `BA_DEF_DEF_` 默认值，不再 fallback 到 `GenMsgDelayTime`；九网段 eligible message 的 unknown 计数均为 0，Original 已全部重算。当前仓库没有 DBC writer，因此本轮没有额外发明 writeback 路径。
- **C09（候选上界）已解决**：实现与测试均采用 $O_{min}+k delta <= O_{max}$，不要求整除且不强行补入 max。
- **C10（协议范围）已锁定**：最终九网段主实验统一为 CAN FD，Classic CAN 仅保留为工程扩展表述。
- **旧九网段证据状态不变**：`output/diagnostics/final_nine_network_baseline/` 仍只作开发期证据；paper-ready 主数据只引用 `output/final_paper_nine_network/`。

### 9.2 最终主数据状态

- 唯一最终 manifest：`docs/final_nine_network_manifest.yaml`，人读说明为 `docs/final_nine_network_manifest.md`。
- 九网段 preflight、CAN-only、joint `rho=1 / attempts=3 / K=41 / seed=0 / refinement<=3` 均已完成。
- 数据级验证结果：`output/final_paper_nine_network/summary/data_validation.json` 中 `paper_ready=true`。
- CAN-only 完整五模式结果：`output/final_paper_nine_network/summary/can_only_summary.csv`。
- Joint observed Pareto 与推荐结果：`joint_summary.csv`、`pareto_points.csv`、`main_function_recommendations.csv`。
- 最终事实报告：`docs/final_nine_network_paper_data_report.md`。

### 9.3 稳定性与可写强度

- objective front stable：CH、DA、EP、LC、PT、SU。
- assignment front stable：CH、EP、LC、PT、SU。
- DK、GL、IC 在 3-pass 上限内 objective 与 assignment 均未稳定；DA objective 已稳定但 assignment 未稳定。
- 因此论文可以报告九网段主配置下的 **observed Pareto front** 和上述稳定性事实，但不得把 pass-limit 网络称为数学收敛，也不得把 assignment 不稳定隐藏在 objective stability 后面。
- EP、LC、SU 为单点 observed front（`unique_solution`）；PT 使用 `ideal_point_fallback`；其余五网段使用 `geometric_knee`。