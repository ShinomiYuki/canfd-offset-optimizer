# GUI Backend Contract

## 1. 接入状态

截至本分支基线 `0e3e6d6`，仓库没有稳定的公共 OptimizationService、GUI request/result、
结构化阶段进度或协作式取消接口。因此当前 `app.py` 注入 `MockBackend`，**真实优化器未接入**。

本文件定义核心线程需要提供的最小应用层能力。真实接入必须新增 adapter 实现
`canfd_offset_optimizer.gui.contracts.OptimizationBackend`，不得让窗口或 widgets 导入
`SearchState`、局部搜索缓存、增量快照、restart 内部记录或 optimizer 私有函数。

## 2. 调用协议

```python
class OptimizationBackend(Protocol):
    def inspect_input(
        self,
        request: InputInspectionRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> InputSummary: ...

    def optimize(
        self,
        request: GuiOptimizationRequest,
        progress_callback: ProgressCallback,
        cancellation_token: CancellationToken,
    ) -> GuiOptimizationResult: ...
```

两个方法都是同步方法，但由 GUI 的 worker 在专用 `QThread` 调用。backend：

- 不得访问、创建或修改 QObject/widget；
- 不得假定回调运行在 GUI 主线程；
- 不得从自己的线程直接更新界面；
- 必须把所有展示数据放入 DTO 或进度回调；
- 不得返回可变的核心对象供 GUI 持有。

## 3. 输入检查

`InputInspectionRequest` 包含：

- `dbc_path: Path`；
- `config_path: Path`；
- `arxml_directory: Path | None`。

backend 负责真实格式解析和语义校验。成功返回 `InputSummary`：

- 一个或多个、名称唯一的 `NetworkSummary`；
- 每个网段的名称、报文数量、weight mode 和简短说明；
- 面向用户的 warnings。

GUI 只展示网段摘要，不接触 parser 中间模型。

## 4. 优化请求

`GuiOptimizationRequest` 是不可变 DTO，包含：

- 已验证的输入检查请求；
- 网段名称；
- `peak/balanced/variance` 模式；
- Balanced tolerance；
- `adaptive/fixed` restart 设置及 attempts；
- candidate pool size；
- 是否启用冲突导向 3-opt；
- 用户显式选择的输出目录。

adapter 只能把这些字段映射到稳定的公共 service。字段缺失、组合不合法或核心不支持时，应抛出
带用户可读消息的 `BackendError`，不能静默改写请求语义。

## 5. 进度与取消

backend 通过 `ProgressCallback(ProgressUpdate)` 发送粗粒度、稳定的展示信息：

- `inspecting`、`preparing`、`peak_search`、`balanced_search`、`finalizing` 阶段；
- 简洁用户消息；
- 可用时的当前/总 attempts；
- 已用秒数。

进度不能泄露 assignment hash、solver branches/conflicts、缓存类名或内部 YAML 字段。

`CancellationToken` 是线程安全的协作式令牌。真实 service 应在解析阶段边界、restart/attempt
边界和可安全中断的长循环中轮询，并通过 `raise_if_cancelled()` 抛出
`OptimizationCancelled`。GUI 会保持 `cancelling` 状态直到 backend 确认，禁止使用
`QThread.terminate()` 或伪装为立即停止。

## 6. 优化结果

`GuiOptimizationResult` 必须一次性提供：

- 网段和模式；
- 原始/优化后的完整 `ObjectiveMetrics`；
- 不可变 `OffsetAssignmentRow` 序列；
- 实际 attempts、停止原因和总耗时；
- warnings；
- 稳态窗口优化前/后负载数组；
- 启动窗口优化前/后负载数组；
- backend 已生成的用户产物路径（如有）。

`ObjectiveMetrics` 包含 `Zss/Qss/standard_deviation/Zst/Qst/Nvio/Vvio`。所有指标和负载数组
必须由核心 service 计算；GUI 不得利用 Offset 重新实现目标函数或负载模型。数组前后长度必须
匹配，所有 DTO 使用 frozen dataclass 和 tuple，避免窗口筛选、排序或导出时修改原结果。

## 7. 错误边界

- 可预期的输入、配置、求解或写出错误：抛出 `BackendError`，消息可以直接显示给用户。
- 用户取消：抛出 `OptimizationCancelled`。
- 其他异常：允许穿过 backend 边界；worker 会给出安全主消息，并把类型、消息和 traceback 仅放入
  可展开的技术详情。
- 禁止吞掉异常、返回半成品结果或用空数组表示失败。

## 8. 核心线程需提供的最小公共接口

真实接入前，核心线程仍需提供：

1. 稳定、与 CLI 参数解析解耦的输入检查 service；
2. 接受完整不可变请求并返回完整结果的同步优化 service；
3. 阶段与 attempt 级结构化进度回调；
4. 在安全检查点轮询的协作式取消；
5. 对三种目标、restart、candidate pool 和 3-opt 的明确公共映射；
6. 核心直接计算并返回四组负载数组和全部指标；
7. 面向用户的 warning、停止原因、实际 attempts 和产物路径；
8. 不暴露 `SearchState`、增量评价快照、局部移动缓存或 optimizer 私有函数的 service DTO。

只有上述接口完成等价性验证并稳定后，才可实现真实 adapter。

## 9. Adapter 接入清单

1. 新建独立 adapter 模块，实现 `OptimizationBackend`。
2. adapter 只依赖核心公共 service 和 GUI contracts。
3. 为每个请求字段、结果字段、异常、进度和取消路径增加 adapter 测试。
4. 用同一输入验证 CLI/service 的核心结果等价，不修改 golden regression。
5. 在 `app.py` 组合根将 `MockBackend()` 替换为真实 adapter；窗口和 widgets 不变。
6. 更新 README、用户指南和窗口标题，明确真实后端已接入。

当前状态停留在第 1 步之前：MockBackend 可完整驱动 GUI，但真实 adapter 等待核心公共接口。
