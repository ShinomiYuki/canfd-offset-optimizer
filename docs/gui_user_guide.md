# PySide6 GUI 用户指南

## 后端与数据真实性

正常启动固定使用 `RealBackend`。它把工作区中的 DBC、ARXML 和 YAML 交给核心
`parse_dbc`、`load_project` 与 `run_gcls`，GUI 只显示核心结果的不可变 DTO 快照。
应用不会回退到 Mock；真实后端初始化失败时，界面显示“仅预览 / 优化不可用”并禁用运行。

`MockBackend` 默认不解析业务数据、不生成成功结果、也不写 `user_output`。
`FixtureBackend` 仅供自动化界面测试显式注入，应用组合根不会引用它。

## 启动

```powershell
python -m pip install -e ".[gui,dev]"
python -m canfd_offset_optimizer.gui
```

Windows 也可双击：

```text
scripts\start_gui.cmd
```

## 统一工程导入

可以一次拖入多个文件、目录或两者混合。每次导入创建独立工作区：

```text
user_input/<timestamp>_<project>/
```

原文件不被修改。`import_manifest.json` 记录原始绝对路径、工作区相对路径、类型、
大小、SHA-256、导入时间、去重/冲突状态和解析使用状态。

至少需要一个 DBC 和唯一一个 YAML/YML 配置。ARXML 可选：

- 仅 DBC + 配置：只能选择 `payload_bytes + Peak`；
- 提供 ARXML：可选择 `payload_bytes` 或 `frame_time_us`；
- `payload_bytes` 始终只支持 Peak。

网段名直接显示 `DA`、`DK`、`PT` 等原名，不解释缩写。

## 资格判定与批量状态

资格由核心 DBC parser 决定，只接收周期 CAN FD TX 报文。每个 DBC 都会在工程汇总中
保留一行：可优化网段进入 GCLS；经典 CAN、无周期 CAN FD TX 或其他核心解析不支持的
网段标记为 `skipped`，并显示核心错误详情。

`skipped` 网段没有 `GuiOptimizationResult`、指标、Offset 表、负载曲线或成功网段目录。
单网段失败不伪装成功，后续网段继续处理；工程汇总分别统计 succeeded、failed、skipped
和 cancelled。

## Offset、进度与取消

GUI 真实适配器对候选集合失败关闭：必须精确等于
`{15, 20, 25, ..., 100} ms`。适配器不四舍五入、不裁剪，也不修补核心结果；配置或核心
返回任一非法 Offset 时，该网段标记为 failed，并保留报文和数值详情。

后台使用 `QObject + QThread`。取消 token 在网段边界以及每个 GCLS restart observer
回调处检查；不使用 `QThread.terminate()`。已完成结果保留，未开始的可优化网段标记取消。

## 结果与曲线

成功网段目录包含：

```text
user_output/<timestamp>_<project>_real/
├── summary.csv
├── summary.json
└── <network>/
    ├── offsets.csv
    └── summary.json
```

Offset 表中的报文名、CAN ID、周期和原始 Offset 来自核心加载模型；优化 Offset、指标、
Attempts 和四组负载数组来自该网段自己的核心 `OptimizationResult`。切换网段时 GUI 先清空
旧曲线，再绑定当前 DTO，并在标题显示网段、窗口类型和源 DBC。失败、跳过和无选择状态均不
复用上一次成功曲线。

## 验收

```powershell
New-Item -ItemType Directory -Force .tmp | Out-Null
$env:QT_QPA_PLATFORM = "offscreen"
$env:TEMP = (Resolve-Path ".tmp").Path
$env:TMP = $env:TEMP
python -m pytest -q tests/gui
python -m pytest -q
python -m ruff check src tests
python -m mypy src
git diff --check
```
