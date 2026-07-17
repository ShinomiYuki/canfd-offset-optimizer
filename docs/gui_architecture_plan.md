# GUI 架构与批量工作区边界

## 1. 当前决策

仓库仍没有可直接满足 GUI 的稳定公共 OptimizationService。GUI 保持 Mock-first，不导入 parser
中间 DTO、搜索状态、增量快照或 optimizer 私有函数。真实 service 就绪后只替换组合根注入的
backend adapter，窗口、worker、DTO 和 view model 不应因核心内部结构变化而改变。

## 2. 三段式 Backend Protocol

`gui/contracts.py` 提供不可变 DTO 和同步 `OptimizationBackend`：

1. `import_inputs(sources, progress, cancellation) -> ImportSession`
2. `inspect_workspace(session, progress, cancellation) -> WorkspaceInspection`
3. `optimize_all_networks(request, progress, cancellation) -> BatchOptimizationResult`

统一导入复制原文件到版本化 `user_input` 会话，生成清单；检查阶段只读取工作区副本并发现全部
网段；批量阶段顺序运行并在版本化 `user_output` 会话中生成工程摘要和每网段产物。

核心边界 DTO 包括 `ImportRecord/ImportSession`、`NetworkSummary/WorkspaceInspection`、
`GuiBatchOptimizationRequest`、`ProgressUpdate`、`GuiOptimizationResult`、
`NetworkBatchResult/BatchOptimizationResult` 和 `CancellationToken`。所有跨线程集合使用 tuple，
结果 dataclass 为 frozen。

网段使用稳定 `network_id` 作为唯一键，并独立保留 `network_name/display_name/source_file`。
`BatchOptimizationResult.results_by_network_id` 是不可变映射；概览排序或筛选后的选择先读取行内
network_id，再由主窗口统一驱动 Offset、曲线和日志三个详情页。

## 3. 文件职责

```text
src/canfd_offset_optimizer/gui/
├── app.py                 # composition root，当前注入 MockBackend
├── contracts.py           # 稳定 GUI DTO、Protocol、取消令牌
├── backend.py             # backend 公共重导出
├── mock_backend.py        # 工作区导入和确定性批量模拟
├── workers.py             # QObject worker / QThread signal boundary
├── state.py               # 纯工作流状态机
├── main_window.py         # 编排，不解析输入、不计算指标
├── view_models.py         # 只读批量汇总与 Offset models
├── formatting.py          # 用户显式产物格式
└── widgets/               # 导入、设置、进度、汇总、详情和曲线
```

主窗口只保留导入计数和“已发现网段：N 个”。`ProjectDetailsDialog` 直接复用 InputPanel 持有的
`NetworkDetailsTableModel` 与 `ImportDetailsTableModel`，避免复制会话数据。

PySide6 只存在于 GUI 包和 `gui` optional extra。CLI 导入路径不依赖 Qt。

## 4. 工作流与失败隔离

主状态为 `idle → importing → inspecting → ready → running`，并进入 `succeeded/partial/failed`
或经 `cancelling → cancelled`。输入缺失或冲突进入 `incomplete`，只能重新导入。

批量任务首版严格顺序执行，避免核心单线程增量 evaluator 的并发风险。单个网段失败不会中断后续
网段；工程级初始化失败才进入工程失败。取消异常携带 `partial_result`，确保 worker 可以把已完成
网段安全送回 GUI。

## 5. 与增量快照核心线程的关系

本次重构只涉及 `src/.../gui/`、`tests/gui/`、GUI 文档和 README，不修改 optimizer、parser、
reporting、models、CLI 或增量快照文件，因此没有直接代码冲突。真实 backend 接入仍应等待核心
线程提供稳定批量 service、进度和取消检查点；adapter 不得把 `SearchState`、`SlotMap`、
`TripleContributionCache`、parser 中间对象等泄露给 GUI。

## 6. 验收重点

- 文件/目录/混合拖入和递归扫描；
- 工作区复制、manifest、哈希去重、稳定冲突改名、原文件不变；
- 多网段自动发现、Payload/Frame Time 能力约束；
- 顺序批量、单网段失败继续、工程失败、协作式取消保留部分结果；
- 工程汇总、每网段产物、筛选/排序/详情切换；
- QThread 生命周期、关闭窗口安全停止、CLI 不导入 PySide6；
- 全量 pytest、ruff、strict mypy 和 `git diff --check`。
