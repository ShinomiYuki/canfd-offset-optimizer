> [!IMPORTANT]
> 本文为前置评估记录。GUI 分支的执行边界以 `docs/gui_architecture_plan.md` 为准；
> 当前没有稳定 OptimizationService，因此本分支只实现隔离契约和 MockBackend，不修改核心算法。
# PySide6 GUI 前置架构与实施计划

## 一、仓库检查结论

1. **目前没有供 GUI 直接调用的稳定公共入口。**
   - 包根目录仅公开 `CanMessage`、`NetworkModel`、`ObjectiveValue`、`OptimizationResult`。
   - `load_project()`、`run_gcls()`、报告 writers 虽可导入，但需要 GUI 自行拼装 `LoadedProject`、`SlotMap`、配置覆盖和产物写入，不属于稳定应用层 API。
   - `cli.main()` 会解析进程参数、配置全局日志、写文件并返回退出码，不适合作为 GUI backend。
   - 现有 `restart_observer` 只能提供 `RestartRecord`，没有完整阶段信息和取消能力。
   - 当前工作树及所有可见分支中不存在已实现的 `service/request/result` 类型，因此将其作为 GUI 前置工作新增。

2. **GUI 不应依赖的核心实现类型：**
   - 搜索状态：`SearchState`、`SlotMap`、`SlotHits`、`SearchStatistics`、`ObjectivePolicy`。
   - 增量三报文实现：`SparseContribution`、`SparseRelocation`、`PairObjectiveSnapshot`、`TripleContributionCache`、`ReadOnlyTripleObjectiveEvaluator`。
   - 搜索审计内部类型：`PeakCandidate`、`TripleMoveAudit`、`TripleSearchAudit`、`TripleSearchTimings`、`BalancedCandidateSearchRecord`、`RestartExecutionSummary`。
   - Parser 中间类型：`ParsedDbcMessage`、`DbcParseResult`、`ArxmlChannelData`、`LoadedProject`。
   - Reporting/viz 数据：`MessageReleaseSeries`、`StageCongestionData`、`WindowCongestionData`。
   - `OptimizationResult` 虽已从包根导出，但结构包含大量搜索审计字段；GUI 应只接收稳定、面向展示的 service result DTO。

3. **真实后端策略：先 Mock、后真实接入。**
   - 先按真实运行流程确定 backend contract，使用测试专用 `MockBackend` 完成窗口状态机、worker、进度和取消测试。
   - 增量快照核心线程合入后，再实现 `OptimizerService` 并接入真实 backend。
   - 发布版不提供 Mock 切换入口，Mock 只放在测试目录。

## 二、稳定 Service API 与 GUI 目录

### 公共入口

新增 `canfd_offset_optimizer.service`，并从包根选择性重导出：

- `OptimizerBackend` Protocol：
  `run(request, *, progress=None, cancellation=None) -> OptimizationRunResult`
- `OptimizerService`：真实同步实现，本身不引用 PySide6。
- `OptimizationRequest`：
  - `dbc_path`
  - `arxml_dir`
  - `config_path`
  - `output_root`
  - `seed=0`
  - `channel_override=None`
  - `objective_mode_override=None`
- `ProgressEvent`：
  - `phase`
  - `completed`
  - `total`
  - `message`
- `CancellationToken`：内部使用 `threading.Event`，提供 `cancel()`、`is_cancelled()`、`raise_if_cancelled()`。
- `OptimizationRunResult`：
  - 输出目录和报告前缀
  - 权重/目标模式
  - 初始与最终指标快照
  - `AssignmentRow` 列表
  - warnings
  - `Artifact` 路径清单
  - 总耗时
- `OptimizationCancelled`：与普通输入错误、意外异常区分。

GUI 不接收 `LoadedProject`、`SearchState` 或原始 `OptimizationResult`。

### 目录结构

```text
src/canfd_offset_optimizer/
├── runtime.py
├── service/
│   ├── __init__.py
│   ├── contracts.py
│   └── optimizer_service.py
└── gui/
    ├── __init__.py
    ├── __main__.py
    ├── app.py
    ├── main_window.py
    ├── controller.py
    └── worker.py
```

职责：

- `app.py`：创建 `QApplication`、真实 service、controller 和窗口。
- `main_window.py`：DBC/ARXML/YAML/输出路径、seed、可选 channel/objective，运行与取消按钮，进度、指标、Offset 表和 PNG 预览。
- `controller.py`：维护 `idle/running/cancelling/succeeded/failed` 状态，不执行核心计算。
- `worker.py`：把同步 backend 放入 `QObject + QThread`。
- 不使用生成式 `.ui` 文件；首版单窗口，控件过大时再拆分 `widgets/`。
- `pyproject.toml` 增加 `gui = ["PySide6>=6.8,<7"]` 和 `canfd-offset-gui` 入口，不影响 CLI 用户。当前 PySide6 支持项目使用的 Python 版本范围，[PyPI](https://pypi.org/project/PySide6/)。

## 三、后台运行、进度与取消

- 采用 worker-object 模式：`QObject` 通过 `moveToThread()` 放入 `QThread`，不把业务 slot 写进 `QThread` 子类；这是 Qt 推荐模式，[Qt QThread 文档](https://doc.qt.io/qt-6/qthread.html)。
- Worker 发出 `progress`、`succeeded`、`failed`、`cancelled`、`finished` signals；UI 更新只在主线程进行。
- 取消按钮直接设置共享 `CancellationToken`。不能依赖排队调用 worker 的取消 slot，因为同步 backend 正在占用 worker 线程事件循环；禁止 `QThread.terminate()`。
- 核心检查点：
  - 加载和各报告 writer 前后；
  - 每次 GCLS restart、Balanced candidate；
  - Greedy 每条报文；
  - 1-opt 每条报文；
  - pair/triple 组合枚举每 256 个候选。
- 进度回调最多约 10 Hz；取消检查不节流。Adaptive restart 用最大尝试数作阶段总量，提前收敛时阶段直接完成；无法估算的加载/绘图阶段使用不确定进度条。
- 首版只允许一个活动任务，不并行运行多个优化器；这也符合当前增量 evaluator 明确的 single-threaded 约束。
- 输出先写入最终目录旁的临时目录。最终目录必须不存在或为空；成功后整体提升为最终目录，取消时删除临时目录，失败时不覆盖已有结果。报告写入期间只能在当前 writer 返回后响应取消。
- 关闭窗口时若任务仍在运行，先请求取消并等待 worker 正常结束，不强制杀线程。

## 四、文件变更与增量快照冲突

### 现有文件修改

- `pyproject.toml`：GUI optional dependency 和脚本入口。
- `README.md`：GUI 安装、启动、取消语义和 v1 范围。
- `src/canfd_offset_optimizer/__init__.py`、`exceptions.py`：稳定 facade 与取消异常导出。
- `optimization/gcls.py`、`greedy.py`、`local_search.py`、`triple_search.py`：可选 progress/cancellation 参数，默认值保持现有 CLI 行为。

`cli.py`、parser、reporting 和 `models.py` 在 GUI v1 不重构；service 复用其下层函数，并以 fixture 测试保证与 CLI optimize 结果一致。

### 新增测试

```text
tests/unit/test_service_contracts.py
tests/unit/test_optimizer_service.py
tests/gui/test_worker.py
tests/gui/test_controller.py
tests/gui/test_main_window.py
tests/gui/fakes.py
tests/integration/test_gui_optimize_backend.py
```

### 与增量快照线程的关系

当前工作树已有未提交核心改动：

- `models.py`
- `optimization/triple_search.py`
- `optimization/triple_incremental.py`
- `reporting/summary_writer.py`
- `diagnostics/triple_ablation.py`
- `tests/unit/test_triple_search.py`

存在一个明确直接冲突：响应式取消需要修改 `triple_search.py`。因此：

1. 先让增量快照线程完成、测试并提交；
2. 确认工作树干净；
3. GUI 分支以后述干净提交为基线创建；
4. Service DTO 不放入 `models.py`，GUI 不读取 `TripleSearchTimings` 等新字段；
5. 取消测试另建文件，避免同时编辑现有 `test_triple_search.py`。

除 `triple_search.py` 的 callback/checkpoint 插桩外，GUI 新目录和 service facade 与增量快照算法没有语义冲突。

## 五、分阶段提交与验收

### 推荐提交顺序

1. **`feat(service): define stable optimize contracts`**
   - 增加 request/result/progress/backend protocol、取消 token 和契约测试。

2. **`feat(gui): add mock-backed PySide6 shell`**
   - 完成窗口、controller、worker 和测试专用 MockBackend；验证状态转换和线程清理。

3. **`feat(core): add cooperative progress and cancellation hooks`**
   - 在增量快照线程合入后，为 GCLS、Greedy、1-opt、pair/triple 搜索增加可选检查点；默认调用结果保持完全一致。

4. **`feat(service): implement real optimize backend`**
   - 依次执行 load、GCLS、CSV、PNG、summary、restart audit，返回展示 DTO 和 artifact manifest；增加成功、输入错误、取消及原子输出测试。

5. **`feat(gui): connect real backend and result presentation`**
   - 发布入口改用 `OptimizerService`，展示指标、Offset、warnings、图像和输出目录。

6. **`docs(test): document GUI workflow and acceptance`**
   - README、完整回归、headless GUI 测试和手工 smoke checklist。

提交信息可以详细一点，用中文。

### 验收命令

```powershell
python -m pip install -e ".[dev,gui]"
python -m pytest -q tests/unit/test_service_contracts.py tests/unit/test_optimizer_service.py
$env:QT_QPA_PLATFORM='offscreen'; python -m pytest -q tests/gui tests/integration/test_gui_optimize_backend.py
python -m pytest -q tests/integration/test_end_to_end.py::test_cli_generates_complete_output
python -m pytest -q
python -m ruff check src tests
python -m mypy src
python -m pytest --cov=canfd_offset_optimizer --cov-report=term-missing
git diff --check
python -m canfd_offset_optimizer.gui
```

验收标准：

- GUI 主线程在加载、优化和绘图期间保持响应。
- 正常任务生成与 CLI optimize 等价的 Offset、指标和完整产物。
- 进度阶段有序，回调不携带 Qt 类型。
- 取消得到 `cancelled` 而不是 `failed`，不产生最终输出目录，也没有遗留 QThread。
- GUI 源码不导入 parser DTO、搜索状态、增量 evaluator 或 reporting 私有类型。
- 原有 CLI、核心测试、ruff 和 strict mypy 全部通过。

### 明确范围

首版仅支持 `optimize`；不包含 `compare`、`compare-weights`、诊断命令、配置编辑器、多任务并行或交互式 Matplotlib。现有 PNG 通过 `QPixmap` 预览，真实绘图仍使用 worker 中的 Agg backend。
