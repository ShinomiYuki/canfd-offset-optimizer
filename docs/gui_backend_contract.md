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
- 每个网段共同可用的权重能力。

每个 `NetworkSummary` 必须区分 `network_id`、`network_name`、`display_name` 和 `source_file`。
`network_id` 是稳定唯一查询键；简洁 `network_name` 用于概览显示；完整文件名只属于来源信息。

DBC 和唯一配置是必需输入，ARXML 可选。没有可用 ARXML 时只提供 `payload_bytes`。生产适配器通过
核心 parser 发现 Controller `SHORT-NAME`，再以 DBC 来源签名进行唯一关联；匹配歧义时不得猜测，
对应网段只开放 `payload_bytes`。GUI 原样显示 `DA` 等网段名，不扩写。

## 5. 批量请求与结果

`GuiBatchOptimizationRequest` 对全部网段共享权重、模式、tolerance、restart、candidate pool、
3-opt 和输出根目录。Backend 不得静默为不同网段改写设置。

`BatchOptimizationResult` 必须为每个发现网段返回一个 `NetworkBatchResult`，并提供不可变
`results_by_network_id` 映射。最终状态是
`succeeded/failed/skipped/cancelled`。成功项包含完整 `GuiOptimizationResult`；失败项包含用户可读
错误；部分失败不能丢失成功结果。批量根目录提供 CSV/JSON 汇总；只有成功网段创建产物目录，
跳过网段仅在工程 summary 中记录原因。

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

1. `parse_dbc` 是网段和周期 CAN FD TX 报文资格的唯一来源。
2. `load_project` 提供报文、原始 Offset、候选集合、权重和时间窗。
3. `run_gcls` 提供 assignment、目标指标、attempts、停止原因和优化后负载数组。
4. Adapter 使用核心 `SearchState` 按核心基线规则生成原始负载快照，不在 GUI 中复制负载公式。
5. 每个 restart observer 回调检查取消 token 并发送结构化进度；批量结果保留部分成功项。
6. 核心尚未提供独立公共 OptimizationService，因此 `real_backend.py` 是唯一受审计的直接适配边界；
   后续公共 service 就绪后应替换此处导入，不影响 GUI contracts/widgets。
