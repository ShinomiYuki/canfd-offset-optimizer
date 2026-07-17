# PySide6 GUI 用户指南

## 1. 当前定位

GUI 已采用“统一工程导入 + 全网段顺序批量优化”工作流。当前后端仍是
**MockBackend**，所有结果仅用于界面与流程联调，不能作为工程设计、验证或交付依据。
真实核心尚无满足 GUI 所需的稳定批量 service、结构化进度和协作式取消接口，因此 GUI 不直接
调用 CLI、parser DTO 或 optimizer 私有实现。

## 2. 安装与启动

Python 3.11 或更高版本：

```bash
python -m pip install -e ".[gui,dev]"
python -m canfd_offset_optimizer.gui
```

Windows 也可双击：

```text
scripts\start_gui.cmd
```

脚本以仓库根目录为工作目录，并在缺少 PySide6 时给出安装提示。只使用 CLI 的用户无需安装
`gui` extra。

## 3. 统一工程导入

在“统一工程导入”区域可一次拖入：

- 一个或多个文件；
- 一个或多个目录；
- 文件和目录的任意混合。

目录会被递归扫描。每次导入都会创建独立目录：

```text
user_input/<timestamp>_<project>/
```

原始文件不会被移动或修改。工作区按 `dbc/config/arxml/unrecognized` 分类并保留目录结构，
同时写入 `import_manifest.json`，记录原始绝对路径、工作区相对路径、类型、大小、SHA-256、
导入时间、去重/冲突状态和是否参与解析。

- 同名同内容：按 SHA-256 去重；
- 同名不同内容：添加稳定哈希后缀，不覆盖文件；
- 无法识别或无效输入：保留记录，并在界面明确提示；
- “清空当前会话”只清理界面状态，不删除原始文件或历史 `user_input` 会话。

必需输入为至少一个 DBC 和唯一项目 YAML/YML 配置；ARXML 为可选输入。多个项目配置会被视为
阻塞冲突。导入完成后 GUI 自动检查工作区副本并发现所有 DBC 网段，无需手工选择网段。
主窗口只显示“已发现网段：N 个”和导入统计，不展开长文件名。点击“查看详情”可在“网段详情”
和“导入文件详情”两个标签页查看稳定 network_id、来源 DBC、完整 hash 与路径。详情窗口和主界面
共享同一会话模型，不维护可能过期的副本。

网段名称直接显示为 `BD`、`GL`、`SU` 等简洁原名，不扩写缩写。完整 DBC 文件名仅作为来源
信息和 Tooltip，不作为结果查询键。

## 4. 全网段批量设置

一份不可变设置快照应用到全部已发现网段：

- 权重：`payload_bytes` 或 `frame_time_us`；
- 模式：Peak、Balanced、Variance；
- Balanced tolerance；
- Adaptive/Fixed restart 和 attempts；
- Candidate pool：`1/4/8/16/32`；
- 可选冲突导向 3-opt。

只有 DBC 和配置、没有 ARXML 时，只能选择 `payload_bytes`，并固定为 Peak。提供 ARXML 后可在
两种权重中选择，默认使用 `frame_time_us + Balanced`。权重选项取全部网段支持能力的交集，
不会对不同网段静默采用不同设置。

## 5. 批量运行、进度与取消

点击“开始全部网段优化”后，backend 按发现顺序逐个处理网段。界面显示当前网段、网段序号、
attempt、网段状态、总耗时和总体进度。某个网段失败或被配置为跳过时，错误被记录，后续网段仍
继续运行；工程级失败则终止任务。

导入、检查和优化都由 `QObject + QThread` worker 执行。任务期间输入和设置被锁定，重复启动被
忽略。取消使用线程安全 token：当前网段在安全检查点结束，已完成网段及产物保留，当前网段标记
取消，尚未开始的网段标记跳过。GUI 不调用 `QThread.terminate()`。关闭运行中的窗口时会先确认，
确认后采用相同的协作式停止流程。

## 6. 输出和结果浏览

每次批量运行默认创建：

```text
user_output/<timestamp>_<project>/
├── summary.csv
├── summary.json
├── DA/
├── DK/
└── PT/
```

成功网段目录包含 `offsets.csv`、`metrics.json`、`load_curves.json` 和 `run.log`；失败、跳过或
取消网段包含 `status.json`。工程汇总不会因单个网段失败而丢失。

默认结果页每个网段一行，支持按网段名、最终状态和最小 Zss 改善筛选，并支持列排序。表格显示
状态、模式、原始/优化后 Zss 与 Qss、标准差、改善值、attempts、停止原因、耗时和警告数。
选择某一行只切换该网段的 Offset 表、负载曲线和日志详情，不会重新运行或修改结果。选择关系由
稳定 `network_id` 驱动，因此排序和筛选后仍指向正确结果。失败网段显示空 Offset/曲线及自身错误；
没有选择时显示“请选择一个网段”，不会回退到最后完成的网段。

MockBackend 使用 `SHA-256(network_id)` 派生可复现的网段差异。标准差、Zss 改善、Attempts、
Offset 和四组曲线均来自该网段自己的 DTO；Mock 标识继续保留，数据不代表真实优化器结果。

## 7. 常见问题

- **无法开始运行**：检查“缺少必需输入”或“工程冲突”提示。
- **只有一种权重**：工程未提供 ARXML，因此只能使用 Payload + Peak。
- **一个网段失败**：从汇总表选择该网段查看错误；其他成功网段仍可浏览和导出。
- **取消后仍有输出**：这是预期行为，已完成结果和批量摘要会被保留。
- **结果带 Mock 警告**：当前真实后端尚未接入。

## 8. 开发验收

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
