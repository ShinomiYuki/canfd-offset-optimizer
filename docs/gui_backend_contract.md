# GUI Backend Contract

## 1. 接入状态

当前 `app.py` 默认注入 `RealBackend`。真实 adapter 实现
`canfd_offset_optimizer.gui.contracts.OptimizationBackend`。只有 `real_backend.py` 允许接触核心
parser/loader/optimizer 类型，并立即转换为 GUI 不可变 DTO；窗口、worker 和 widgets 不得导入核心类型。

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
重复文件去重；冲突文件稳定改名；不得覆盖或修改原始文件。清单必须可供后续审计。

## 4. 检查契约

检查只能读取 `ImportSession` 工作区副本。`WorkspaceInspection` 必须明确：

- 全部名称唯一的 `NetworkSummary`；
- 缺失的必需输入；
- 阻塞错误和非阻塞 warnings；
- 每个网段的帧协议、具体可用权重和自动/固定权重能力。

每个 `NetworkSummary` 必须区分 `network_id`、`network_name`、`display_name` 和 `source_file`。
`network_id` 是稳定唯一查询键；简洁 `network_name` 用于概览显示；完整文件名只属于来源信息。

DBC 是必需输入，项目配置与 ARXML 可选。没有用户配置时，导入器必须把随程序发布、内容与仓库
`input/config/project.yaml` 一致的默认配置复制到会话 `config/project.yaml`，并在 manifest 与警告中
标明来源；一个用户配置优先于默认配置，多个用户配置仍阻塞。CAN FD 没有可用 ARXML 时只提供
`payload_bytes`。生产适配器通过
核心 parser 发现 Controller `SHORT-NAME`，再以 DBC 来源签名进行唯一关联；匹配歧义时不得猜测，
对应 CAN FD 网段只开放 `payload_bytes`。Classic CAN 固定使用
`payload_bytes_approximation`，不参与 CAN FD 权重选择。GUI 原样显示 `DA` 等网段名，不扩写。

## 5. 批量请求与结果

`GuiBatchOptimizationRequest.can_fd_weight` 是 CAN FD 网段共享的权重选择；
`classic_can_weight` 显式记录且当前固定为 `payload_bytes`。模式、tolerance、restart、
candidate pool、3-opt 和输出根目录仍由批次共享。Backend 必须按每个网段真实的
`frame_protocol` 选择对应权重，并在结果中写入实际的 `bus_type`、`weight_mode` 和 `mode`；
不得用项目级单一权重覆盖全部网段，也不得把 Classic Byte 权重标成 μs。

同一工程包含多个独立的 Classic CAN 与 CAN FD 物理网段属于正常情况，不得因此禁用
mode 或阻止其他网段运行。同一个 DBC/物理网段内部混合 eligible Classic CAN 与 CAN FD
时仍应只跳过该网段，并保留清晰的单位不一致诊断。

`BatchOptimizationResult` 必须为每个发现网段返回一个 `NetworkBatchResult`，并提供不可变
`results_by_network_id` 映射。最终状态是
`succeeded/failed/skipped/cancelled`。成功项包含完整 `GuiOptimizationResult`；失败项包含用户可读
错误；部分失败不能丢失成功结果。批量根目录固定提供 `logs/`、`plots/`、`results/` 和 `dbc/`；
`results/networks_summary.csv` 汇总所有网段，只有成功网段创建 Offset 明细、图表和 DBC 副本，
失败、跳过和取消网段仍必须写独立日志。

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
7. DBC 输出必须从导入工作区副本生成，只允许字节级替换已有 Offset 属性的数字 token；不得调用
   会重排 DBC 的整库序列化，不得覆盖原始用户文件，定位不唯一时失败关闭。
8. 核心尚未提供独立公共 OptimizationService，因此 `real_backend.py` 是唯一受审计的直接适配边界；
   后续公共 service 就绪后应替换此处导入，不影响 GUI contracts/widgets。
