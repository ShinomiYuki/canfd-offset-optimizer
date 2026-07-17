# PySide6 GUI 用户指南

## 1. 当前定位

本 GUI 是面向日常工程流程的桌面 MVP，但当前后端是 **MockBackend**。窗口标题、输入警告和
结果警告都会标明 Mock 状态。Mock 结果不能作为车辆网络设计、验证或交付依据。

真实优化器尚未接入，因为仓库当前没有稳定的公共 OptimizationService、结构化进度和协作式
取消接口。GUI 不会以调用 CLI 或 optimizer 私有函数的方式绕过这一边界。

## 2. 安装与启动

Python 3.11 或更高版本：

```bash
python -m pip install -e ".[gui,dev]"
```

任选一种方式启动：

```bash
python -m canfd_offset_optimizer.gui
canfd-offset-gui
```

只使用 CLI 的用户不需要安装 `gui` extra；包初始化和 CLI 导入路径不会导入 PySide6。

## 3. 完整操作流程

1. 在“输入与输出”区域选择 DBC 和项目 YAML 配置。
2. 如项目需要，选择 ARXML 目录。
3. 显式选择用户输出目录。GUI 不会默认写入 `output/diagnostics/`。
4. 点击“读取网段”。输入检查在后台线程执行，完成后网段列表可用。
5. 选择网段、优化模式、Balanced tolerance 和 Restart 策略。
6. 必要时展开“高级选项”设置 attempts、candidate pool 和 3-opt。
7. 点击“开始优化”，在运行状态区查看阶段、attempt、耗时和日志摘要。
8. 在“结果概览”“Offset 修改”“负载曲线”和“运行日志”标签页审阅结果。
9. 将 Offset CSV、运行摘要 JSON 和负载曲线 PNG 导出到用户选择的位置。

输入路径变化后必须重新读取网段，避免用旧的网段摘要启动新请求。

## 4. 设置说明

- **Peak**：严格峰值模式。
- **Balanced**：默认推荐模式；默认 tolerance 为 `0.05`。
- **Variance**：实验模式。
- **Restart 自动**：使用自适应最少/最多 attempts。
- **Restart 固定**：使用固定 attempts。
- **Candidate pool**：可选 `1/4/8/16/32`。
- **冲突导向 3-opt**：默认关闭。它是高质量离线搜索选项，真实接入后可能显著增加运行时间。

GUI 只把这些选项写入不可变请求，不解释或重写核心算法语义。

## 5. 运行、取消与关闭

输入检查和优化都运行在专用 `QThread` 中，主窗口在任务期间仍可拖动、重绘和响应。任务运行时：

- 会锁定可能破坏当前请求的输入和设置；
- 防止重复启动；
- 保留“取消”按钮。

取消是协作式的。点击后状态显示“正在请求停止”，后台在下一个安全检查点确认后才进入“任务已
取消”，GUI 不使用强制终止线程。任务运行时关闭窗口会先询问；确认后同样请求协作式停止，并在
worker 正常退出后关闭窗口。

## 6. 结果与导出

结果概览显示优化前后的 `Zss`、`Qss`、标准差、`Zst`、`Qst`、`Nvio`、`Vvio`，以及实际
attempts、停止原因、总耗时和 warnings。

Offset 表支持：

- 按报文名或 CAN ID 筛选；
- 只看已修改报文；
- 按各列排序；
- 复制选中行；
- 导出带 UTF-8 BOM 的 CSV。

负载曲线可切换稳态/启动窗口并导出 PNG。曲线数组、指标和 Offset 都直接来自 backend result，
GUI 不重新计算核心目标或负载模型。

## 7. 错误与技术详情

可预期的后端错误会显示简明中文说明。意外异常的主消息不会显示 Python traceback；需要排查时，
可展开错误对话框中的技术详情。日志标签页保留阶段、警告、取消和错误摘要。

常见问题：

- “读取网段”不可用：DBC 或项目配置路径尚未填写。
- “开始优化”不可用：尚未成功读取网段、输入已变化，或未选择输出目录。
- 点击取消后没有立即停止：后台正在等待下一个协作式取消检查点。
- 结果带 Mock 警告：这是当前 MVP 的预期行为，真实后端尚未接入。

## 8. 开发验收

Windows PowerShell：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q tests/gui
python -m pytest -q
python -m ruff check src tests
python -m mypy src
```
