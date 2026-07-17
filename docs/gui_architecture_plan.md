# GUI 架构计划

## 1. 仓库结论与公共入口

GUI 分支基线为 `0e3e6d6`。当前包根只公开领域模型；`load_project()`、`run_gcls()`、报告 writer 和 `cli.main()` 都不是面向桌面应用的稳定 service。仓库没有 `OptimizationService`、公共 request/result DTO、结构化阶段进度或协作式取消接口。

因此本分支**不接入真实优化器**。按照 GUI 与核心线程的边界，本分支提供隔离的 `OptimizationBackend` Protocol 和 MockBackend。后续核心线程提供稳定 service 后，新增一个实现该 Protocol 的 adapter，并在 `app.py` 组合根替换注入对象；窗口、worker、view model 和 widgets 不得改变。

## 2. GUI 与核心的数据边界

GUI 只依赖 `gui/contracts.py` 中的不可变 DTO：

- `InputInspectionRequest` / `InputSummary` / `NetworkSummary`；
- `GuiOptimizationRequest`；
- `ProgressUpdate` / `CancellationToken`；
- `ObjectiveMetrics` / `OffsetAssignmentRow` / `GuiOptimizationResult`；
- `OptimizationBackend` Protocol。

GUI 禁止导入 `SearchState`、`SlotMap`、局部搜索缓存、restart 记录、增量评价快照、parser 中间类型或 optimizer 私有函数。GUI 不重新计算 Zss/Qss 等核心指标，所有指标、Offset 和负载数组均来自 backend result。

## 3. 文件结构

```text
src/canfd_offset_optimizer/gui/
├── __init__.py
├── __main__.py
├── app.py
├── main_window.py
├── contracts.py
├── backend.py
├── mock_backend.py
├── workers.py
├── view_models.py
├── state.py
├── formatting.py
└── widgets/
    ├── __init__.py
    ├── input_panel.py
    ├── settings_panel.py
    ├── progress_panel.py
    ├── metrics_panel.py
    ├── assignment_table.py
    └── load_chart.py
```

`tests/gui/` 覆盖 contract、校验、Mock、状态、worker 生命周期、主窗口、结果展示、导出和关闭窗口行为。PySide6 只位于 `gui` extra；CLI 包初始化路径不导入 GUI。

## 4. 后台任务与取消

同步 backend 由 `QObject` worker 移入专用 `QThread`。worker 通过 signals 回传 progress、success、failure、cancelled 和 finished；GUI 主线程不执行 inspect/optimize。

取消使用共享、线程安全的 `CancellationToken`。按钮将状态切换为 `cancelling` 并显示“正在请求停止”，不使用 `QThread.terminate()`。关闭窗口时提示用户；确认后发出取消并等待 worker 正常结束。任务状态固定为：`idle → inspecting → ready → running → cancelling → cancelled`，以及 success/failure 分支。

## 5. Mock-first 与真实后端最小接口

MockBackend 必须支持多网段、输入校验、分阶段进度、成功/失败/取消/警告、指标、Offset 表和启动/稳态曲线；优化期间不写 `output/diagnostics` 或任何真实报告。

真实 adapter 的最小要求：

1. `inspect_input(request, progress_callback, cancellation_token) -> InputSummary`；
2. `optimize(request, progress_callback, cancellation_token) -> GuiOptimizationResult`；
3. 请求能够表达网段、`payload_bytes/frame_time_us` 权重、目标模式、Balanced tolerance、restart 策略、candidate pool 和 3-opt；
4. 结果直接提供完整指标、attempt/停止原因、Offset、四组负载数组、warnings 和导出产物；
5. 核心提供阶段/attempt 进度和协作式取消，不要求 GUI 触碰内部状态。

在上述 service 稳定前，发布入口明确标注 Mock 模式，不以 CLI 或私有函数冒充真实接入。

## 6. 预计修改文件

仅修改 GUI 范围：`pyproject.toml` 的 GUI extra/entry/test dependency、README GUI 说明、新增 `src/.../gui/`、`tests/gui/` 和三份 GUI 文档。不会修改 optimizer、SearchState、models、RestartPolicy、诊断、reporting、CLI、golden regression 或论文文件。
