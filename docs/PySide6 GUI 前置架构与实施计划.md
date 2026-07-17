# PySide6 GUI 前置架构与实施计划

> 本文最初用于 GUI 开发前评估。`feature/gui-mvp` 已按评估结论实现 Mock-first GUI，随后完成
> “统一工程导入 + 全网段批量优化”重构。当前有效边界以
> `docs/gui_architecture_plan.md` 和 `docs/gui_backend_contract.md` 为准。

## 已落实的架构结论

1. 核心仍没有满足 GUI 的稳定公共 OptimizationService，当前继续注入 `MockBackend`。
2. GUI 只依赖 `gui/contracts.py` 的不可变 DTO 和 `OptimizationBackend` Protocol。
3. GUI 不依赖 `SearchState`、`SlotMap`、parser 中间类型、restart/增量快照内部对象或 optimizer
   私有函数。
4. 同步 backend 使用 `QObject + QThread` worker；取消使用线程安全 token，不强制终止线程。
5. GUI 改动局限于 GUI 包、GUI 测试、文档和入口配置，不修改正在演进的增量快照核心。

## 当前三段式工作流

```text
import_inputs
  → user_input/<timestamp>_<project>/ + import_manifest.json
inspect_workspace
  → required inputs + conflicts + all NetworkSummary records
optimize_all_networks
  → user_output/<timestamp>_<project>/ + project/network artifacts
```

导入支持多文件、多目录和混合递归扫描；原文件只读，工作区按类型分类，使用 SHA-256 去重并对
同名不同内容稳定改名。检查自动发现全部 DBC 网段。批量优化共享一份设置并顺序执行，单网段失败
继续，取消保留已完成结果并跳过后续网段。

## GUI 目录

```text
src/canfd_offset_optimizer/gui/
├── app.py
├── main_window.py
├── contracts.py
├── backend.py
├── mock_backend.py
├── workers.py
├── state.py
├── view_models.py
├── formatting.py
└── widgets/
    ├── input_panel.py
    ├── settings_panel.py
    ├── progress_panel.py
    ├── metrics_panel.py
    ├── assignment_table.py
    └── load_chart.py
```

## 后续真实接入计划

1. 核心线程提供稳定的工程导入/检查/批量 service、结构化进度和协作式取消检查点。
2. 新增独立 adapter 实现当前 `OptimizationBackend`，并验证与 CLI 核心结果等价。
3. 在 `app.py` 组合根替换 `MockBackend`，不修改窗口、widgets 或跨线程 DTO。
4. 移除 Mock 标识，增加真实 fixture、错误恢复、取消和产物一致性集成测试。

## 验收命令

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:TEMP = (Resolve-Path ".tmp").Path
$env:TMP = $env:TEMP
python -m pytest -q tests/gui
python -m pytest -q
python -m ruff check src tests
python -m mypy src
git diff --check
```
