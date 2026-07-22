# GUI Backend Contract

## 1. 接入状态

当前 `app.py` 默认注入 `RealBackend`。真实 adapter 实现
`canfd_offset_optimizer.gui.contracts.OptimizationBackend`。只有 `real_backend.py` 与纯数据资格服务
`sender_selection.py` 允许接触核心 parser/model 类型，并立即转换为 GUI 不可变 DTO；窗口、worker 和
widgets 不得直接导入核心类型。

## 2. 调用协议

```python
class OptimizationBackend(Protocol):
    def import_inputs(
        self,
        sources: tuple[Path, ...],
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> ImportSession: ...

    def inspect_workspace(
        self,
        session: ImportSession,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> WorkspaceInspection: ...

    def apply_sender_selection(
        self,
        inspection: WorkspaceInspection,
        selection: SenderNodeSelectionConfig,
    ) -> WorkspaceInspection: ...

    def optimize_all_networks(
        self,
        request: GuiBatchOptimizationRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> BatchOptimizationResult: ...
```

方法均同步，由 GUI worker 在专用 `QThread` 调用。Backend 不得创建或操作 QObject/widget，不得
返回可变核心对象，不得直接更新界面。

## 3. 导入契约

Backend 接受多个文件/目录入口，递归发现文件并复制到独立 `user_input` 会话。`ImportRecord`
必须记录原始绝对路径、工作区相对路径、检测类型、状态、大小、SHA-256、时间和 parser 使用标志。
重复文件去重；冲突文件稳定改名；不得覆盖或修改原始文件。`.xlsx` 归类为
`routing_table` 并复制到会话 `routing/` 目录。清单必须可供后续审计。

## 4. 检查契约

检查只能读取 `ImportSession` 工作区副本。`WorkspaceInspection` 必须明确：

- 全部名称唯一的 `NetworkSummary`；
- 缺失的必需输入；
- 阻塞错误和非阻塞 warnings；
- 每个网段的帧协议、具体可用权重和自动/固定权重能力。
- 路由报文表逐行匹配报告，以及每个网段的基础资格数、路由排除数和最终资格数；
- 每个 DBC 的稳定 `dbc_id`、内容 SHA-256、发送节点清单、逐报文资格审计和 DBC 集合 revision；
- 未确认的 `SenderNodeSelectionConfig`。首次导入不得自动选择任何节点，也不得把发现网段数当作可优化网段数。

每个 `NetworkSummary` 必须区分 `network_id`、`network_name`、`display_name` 和 `source_file`。
`network_id` 是稳定唯一查询键；简洁 `network_name` 用于概览显示；完整文件名只属于来源信息。
对于 `<车型>_<网段>_Matrix_<协议/版本>.dbc` 命名，必须将 `_Matrix` 前的网段片段规范化为
`network_name`，例如 `..._ADAS BUS_Matrix_...` 映射为 `ADAS_BUS`；不得将整个文件名误作网段名。

DBC 是必需输入，项目配置与 ARXML 可选。没有用户配置时，导入器必须把随程序发布、内容与仓库
`input/config/project.yaml` 一致的默认配置复制到会话 `config/project.yaml`，并在 manifest 与警告中
标明来源；一个用户配置优先于默认配置，多个用户配置仍阻塞。CAN FD 没有可用 ARXML 时只提供
`payload_bytes`。生产适配器通过
核心 parser 发现 Controller `SHORT-NAME`，再以 DBC 来源签名进行唯一关联；匹配歧义时不得猜测，
对应 CAN FD 网段只开放 `payload_bytes`。Classic CAN 固定使用
`payload_bytes_approximation`，不参与 CAN FD 权重选择。GUI 原样显示 `DA` 等网段名，不扩写。


## 4.1 DBC 本机发送节点选择契约

每个 DBC 必须按 `dbc_id = hash(工作区相对路径 + 文件 SHA-256)` 独立保存选择。正式配置对象为
`SenderNodeSelectionConfig`，包含 `selected_transmitters_by_dbc`、`excluded_dbc_ids`、`confirmed`
和 `dbc_revision`。每个 DBC 必须选择至少一个具体发送节点，或明确标记“该 DBC 不参与本次优化”。
节点名仅去除首尾空白并精确匹配；不做 contains、大小写猜测或 ECU 名称硬编码。`Vector__XXX`、
空节点和未知节点进入审计，但不能作为本机节点选择。

多 transmitter 报文按集合交集判定，只要报文发送节点与当前 DBC 的选择集合有交集就命中，且同一
报文只计数一次。正式顺序固定为：

```text
selected transmitter intersection
    → core base eligibility
    → routing target network + CAN ID exclusion
    → OptimizationRequest / GCLS
```

`RealBackend` 将 `selected_transmitters` 传给 `load_project`/`parse_dbc`，随后才重建路由排除后的
`NetworkModel`。因此其他 ECU 的 Matrix 报文不可能进入 OptimizationRequest、GCLS、assignment、
负载曲线或 DBC replacement。检查阶段可以预先解析路由表并保存匹配标记，但正式候选应用顺序不变。

DBC 集合或内容变化后通过 revision 重新协调：只有 `dbc_id` 完全一致的条目可保留；新增或 hash
变化的 DBC 回到未处理，只要存在未处理项就撤销 confirmed。不得仅按文件名复用选择。

## 5. 批量请求与结果

`GuiBatchOptimizationRequest.can_fd_weight` 是 CAN FD 网段共享的权重选择；
`classic_can_weight` 显式记录且当前固定为 `payload_bytes`。模式、tolerance、restart、
candidate pool、3-opt 和输出根目录仍由批次共享。Backend 必须按每个网段真实的
`frame_protocol` 选择对应权重，并在结果中写入实际的 `bus_type`、`weight_mode` 和 `mode`；
不得用项目级单一权重覆盖全部网段，也不得把 Classic Byte 权重标成 μs。

路由排除由独立 `RouteMessageTableParser` 解析 `.xlsx`，以精确映射后的
`RouteMessageKey(target_network_id, can_id)` 为唯一主键。报文名不参与主键；名称不同仍排除并记录
warning。存在 `直接报文路由` Sheet 时必须优先且只读取该 Sheet，使用目标报文名称、目标 CAN ID
和目标 CAN 通道，并将 `DACAN` 一类通道名的末尾 `CAN` 去除后映射到 DBC 网段；源网段字段不生成
排除记录。不存在该 Sheet、但存在 `Routing(FLZCU)` 时必须只读取该左域 Sheet：从
`Service Subscriber Data` 取得目标报文名和目标 CAN ID，将 `Service Subscriber Subnet`
横向矩阵中非空的 `FL_CAN_*`/`FL_CANFD_*` 列展开并映射到 DBC 网段名；不得混入
`Routing(FRZCU)` 或 LIN 订阅目标。两种权威 Sheet 均不存在时才使用简化平铺表头契约；权威
Sheet 存在但结构无效时必须报错，不得回退。
解析和匹配在 `WorkspaceInspection` 阶段完成，早于 GUI 批量请求创建；RealBackend 在
`load_project` 后立即重建只含最终资格报文的核心 `NetworkModel`、时间窗和 `SlotMap`，之后才创建
baseline `SearchState` 并调用 `run_gcls`。因此路由报文不可能进入 assignment、GCLS 搜索空间、
DBC Offset replacement 或原始/优化后的可优化报文负载曲线。

同一工程包含多个独立的 Classic CAN 与 CAN FD 物理网段属于正常情况，不得因此禁用
mode 或阻止其他网段运行。同一个 DBC/物理网段内部混合 eligible Classic CAN 与 CAN FD
时仍应只跳过该网段，并保留清晰的单位不一致诊断。

`BatchOptimizationResult` 必须为每个发现网段返回一个 `NetworkBatchResult`，并提供不可变
`results_by_network_id` 映射。最终状态是
`succeeded/failed/skipped/cancelled`。成功项包含完整 `GuiOptimizationResult`；失败项包含用户可读
错误；部分失败不能丢失成功结果。批量根目录固定提供 `logs/`、`plots/`、`results/` 和 `dbc/`；
批次根目录名必须是纯微秒时间戳。`results/networks_summary.csv` 汇总所有网段，成功网段创建 Offset
明细和图表并尝试生成 DBC 副本，
失败、跳过和取消网段仍必须写独立日志。`results/routing_exclusion_summary.csv` 保留每个 Excel
来源行；`results/message_eligibility.csv` 保存每条 DBC 报文的发送节点、所选节点命中、周期、路由
命中、最终状态和排除原因；`run_config.json.sender_node_selection` 保存确认状态、revision 及每个
DBC 的选择/明确排除。网段 CSV/日志保存
`base_eligible_message_count`、`routing_excluded_count`、`final_eligible_message_count`。

指标、Offset、负载数组、attempts 和停止原因全部由 backend/service 提供，GUI 不重新计算。
批量行与详细结果的 network_id、名称和来源必须一致；不得共享可变 metrics/assignment 容器，
也不得用最后完成的结果填充其他网段。

## 6. 进度、取消与错误

`ProgressUpdate` 可表达 import/inspect/prepare/network/finalize 阶段、当前网段、序号、attempt、
网段状态、耗时和总体进度。进度不得泄露搜索缓存或 parser 内部类型。

取消使用 `CancellationToken`。当前网段应在安全检查点停止，已完成网段保留，后续网段标记跳过，
并抛出携带 `BatchOptimizationResult` 的 `BatchOptimizationCancelled`。禁止强制终止线程。

可预期错误抛 `BackendError`；意外异常由 worker 转换为安全主消息和独立技术详情。禁止吞异常、
返回空半成品或把工程失败伪装成全部网段失败。

## 7. 真实 Adapter 当前实现

1. `parse_dbc` 是网段和周期 CAN TX 报文资格及 Classic/FD 协议分类的唯一来源；同一物理网段
   混合 eligible Classic/FD 时必须拒绝。
2. `load_project` 提供报文、原始 Offset、候选集合、权重和时间窗。
3. `run_gcls` 提供 assignment、目标指标、attempts、停止原因和优化后负载数组。
4. Adapter 使用核心 `SearchState` 按核心基线规则生成原始负载快照，不在 GUI 中复制负载公式。
5. 每个 restart observer 回调检查取消 token 并发送结构化进度；批量结果保留部分成功项。
6. 成功后自动导出当前网段的稳态负载图和热力图。负载曲线可重复 DTO 稳态数组；热力图必须使用
   核心 slot count 快照和主分支固定拥挤分级，并且只展示一个真实窗口，不重复数组。
7. DBC 输出必须从导入工作区副本生成。已有 Offset 只允许字节级替换数字 token；继承
   `BA_DEF_DEF_` 默认值的参与优化报文可补充显式 `BA_` 赋值，但属性必须已声明为 `BO_`。
   同一报文最高优先级 Offset 属性存在多条同值声明时，必须保留全部声明并同步替换所有数字
   token，`replaced_count` 仍按报文数统计；重复声明值冲突、属性未声明或写后回读不一致时将
   DBC 导出降级为警告。不得调用会重排 DBC 的整库序列化，不得覆盖原始用户文件。核心优化
   成功项仍必须携带完整 `GuiOptimizationResult`，通过
   `dbc_write_error` 和实际 `exported_files` 表达 DBC 缺失，其他产物和 GUI 展示不得丢失。DBC
   basename 不得改变，最终路径采用 240 字符预算，临时文件必须使用短名称并在失败后清理。
8. 核心尚未提供独立公共 OptimizationService，因此 `real_backend.py` 是受审计的优化适配边界；
   `sender_selection.py` 仅负责 DBC 发送节点清单、资格预览与 revision 校验。后续公共 service 就绪后
   应替换这两处核心导入，不影响 GUI contracts/widgets。
