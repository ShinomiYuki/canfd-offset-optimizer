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

至少需要一个 DBC。YAML/YML 项目配置和 ARXML 均可选：

- 用户没有提供 YAML/YML 时，导入器自动把程序内置的 `default_project.yaml` 复制为本次
  `user_input/<session>/config/project.yaml`。内置文件内容与仓库
  `input/config/project.yaml` 一致，并在 `import_manifest.json` 和日志中明确标记；
- 用户提供一个 YAML/YML 时优先使用用户文件，不叠加默认配置；提供多个仍属于阻塞冲突；
- 因此只导入一个 DBC 也可以开始；前提是该 DBC 至少包含一条核心支持的周期 CAN FD TX 报文。
  如果 DBC 只有经典 CAN、RX 或非周期报文，界面会明确显示“没有可优化网段”，而不是误报输入不完整；

- 仅 DBC + 配置：只能选择 `payload_bytes + Peak`；
- 提供 ARXML：核心先发现 Controller `SHORT-NAME`，再按 DBC 来源签名做唯一对应；
  全部可优化网段均有唯一、可解析的 Controller 时，可选择 `payload_bytes` 或
  `frame_time_us`；无法唯一对应的网段只开放 `payload_bytes`，不会猜测通道；
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

## 快速开始、结果与图表

右侧“快速开始”页用三步说明导入、设置和批量运行，并以浅显语言解释权重、目标模式、
Balanced 容差、重启策略、Attempts、候选池、3-opt、显示范围及输出目录。该页面只提供说明，
不会自动更改参数或启动任务。

每次批量运行创建固定分类目录：

```text
user_output/<timestamp>_<project>_real/
├── logs/
│   ├── batch.log
│   └── <network>.log
├── plots/
│   ├── <network>_load_curve.png
│   └── <network>_heatmap.png
├── results/
│   ├── networks_summary.csv
│   └── <network>/offsets.csv
└── dbc/
    └── <原 DBC 文件名>.dbc
```

`results/networks_summary.csv` 汇总所有网段（包括失败、跳过和取消）；成功网段的 Offset 明细放在
各自子目录。`logs` 保存批次日志和每个网段的独立日志。`plots` 自动导出每个成功网段默认
0～2000 ms 的重复稳态负载曲线，以及不重复的单个稳态窗口拥挤热力图。

`dbc` 中的文件是导入工作区 DBC 的新副本，不会修改用户传入的原文件。写入器只在已有
`GenMsgStartDelayTime`、`GenMsgDelayTime` 或 `MsgStartDelayTime` 报文属性行中替换 Offset 数字；
编码、换行、空格、注释、顺序及所有其它字节保持不变。属性选择顺序与核心 parser 一致；例如
同时存在 `GenMsgStartDelayTime` 和 `GenMsgDelayTime` 时只覆盖前者，后者保持不变。参与优化的报文
缺少原 Offset、同一优先属性重复或无法精确定位时会失败关闭，不插入字段、不猜测、不整文件重排。

Offset 表中的报文名、CAN ID、周期和原始 Offset 来自核心加载模型；优化 Offset、指标、
Attempts 和四组负载数组来自该网段自己的核心 `OptimizationResult`。切换网段时 GUI 先清空
旧曲线，再绑定当前 DTO，并在标题显示网段、窗口类型和源 DBC。失败、跳过和无选择状态均不
复用上一次成功曲线。

稳态曲线仍以核心返回的单个 500 ms 超周期、5 ms 时隙数组为唯一数据源。GUI 默认把该序列
重复展示 4 次，在固定宽度画布中显示 0～2000 ms；可切换 500、1000、2000 或 5000 ms，
不会插值、修改 DTO 或重新运行优化。标题会明确标注超周期重复次数。启动窗口始终只显示核心
返回的真实范围，并禁用稳态显示范围选项。导出 PNG 使用当前选择的完整显示范围。

“负载热力图”页参考主分支 `congestion_plotter` 的拥挤热力图语义：上排为原始方案，下排为
优化后方案；颜色按同一时隙释放帧数固定分为白色 0 帧、绿色 1 帧、黄色 2 帧、橙色 3 帧、
红色 4 帧、黑色 5 帧及以上。帧数来自核心时隙快照，不从负载值推测。稳态和启动热力图均只显示核心返回
的单个真实窗口，不使用负载曲线的多超周期重复规则。热力图页顶部的“网段”下拉框列出本批次
所有成功网段，可直接切换；选择会同步结果概览、Offset、负载曲线和日志的当前网段。

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
