# CAN FD Offset Optimizer

基于 GCLS（Greedy Construction、Single-message Relocation、Conflict-directed Pair
Search、Reproducible Random Restarts）的周期 CAN FD 报文首次发送 Offset 均衡工具。

工具采用整数微秒和 5 ms 离散时隙，严格区分：

- 启动窗口 `[0, O_max)`；
- 稳态窗口 `[O_max, O_max + hyperperiod)`；
- 首次释放语义 `release_time = offset + k * cycle_time`。

## 输入约定

- DBC：只解析当前 DBC 节点发送的 **TX 周期报文**。发送方为 `Vector__XXX`的矩阵条目视为 RX 并过滤；
- ARXML：递归扫描 `.arxml`，读取目标 Controller 的 nominal bitrate、data bitrate 和
  BRS。DaVinci/AUTOSAR 的 `CanControllerBaudRate`、`CanControllerFdBaudRate` 按
  kbit/s 读取并显式换算为 bit/s；
- YAML：配置候选 Offset、GCLS 参数，并可显式覆盖 ARXML 字段。所有覆盖都会写入
  warning 和 `summary.json`。

当 `weight_mode: frame_time_us` 时，nominal bitrate 与 BRS 不得缺失，BRS 开启时还
必须提供 data bitrate。该模式是包含 ISO CAN FD 固定/动态填充上界和 3 个 nominal-rate
intermission bits 的保守帧时长估计，不宣称逐位精确仿真。估算不包含仲裁失败、
错误帧、重传、排队和 ECU 软件抖动。近似模式必须显式选择
`payload_bytes` 或 `unit`，其报告不会套用物理微秒阈值。

## 目标模式

`frame_time_us` 支持三种固定、不可自由重排的词典序目标：

- `peak`：严格优先降低稳态峰值；
- `balanced`：默认推荐模式。先以相同 seed 和重启次数运行 `peak` 得到“严格峰值
  GCLS 参考值” \(Z^*\)，再使用 `ceil(1.05 × Z*)` 的峰值预算，在预算内优先降低
  稳态负载平方和 \(Q^{ss}=\sum_s L_s^2\)；
- `variance`：实验模式，在物理超限指标之后直接优先降低 `Qss`。

`Z*` 是可复现的启发式 GCLS 参考值，不是数学全局最优证明。由于稳态总工作量固定，
最小化 `Qss` 与最小化稳态负载方差等价。`balanced` 会保留 `peak` 解作为保底，确保
物理超限指标不恶化、稳态峰值不超过预算且 `Qss` 不劣于参考解。`payload_bytes` 和
`unit` 会强制使用 `peak` 并记录 warning，避免对近似权重套用物理峰值预算。

配置示例：

```yaml
objective:
  mode: balanced
  peak_tolerance:
    type: relative
    value: 0.05
  variance_metric: sum_of_squares

optimization:
  variance_offset_cap: 3
```

`peak_tolerance.type` 也可设为 `absolute`，此时 `value` 单位为 μs。`optimize` 和
`compare` 可通过 `--objective-mode peak|balanced|variance` 显式覆盖配置；覆盖会进入
warning、字段来源和摘要。

## 安装与运行

```bash
python -m pip install -e ".[dev]"
python -m canfd_offset_optimizer optimize --dbc input/dbc/network.dbc --arxml input/arxml --config input/config/project.yaml --output output --seed 0 --restart-mode adaptive --log-level INFO
```

### PySide6 GUI（RealBackend）

GUI 依赖为可选 extra；未安装 `gui` extra 时，原 CLI 的导入和运行路径不会导入
PySide6。开发和 GUI 测试环境可使用：

```bash
python -m pip install -e ".[gui,dev]"
```

支持两种启动方式：

```bash
python -m canfd_offset_optimizer.gui
canfd-offset-gui
```

Windows 可直接双击 `scripts\start_gui.cmd` 一键启动。

### Windows 免安装 GUI 发布包

构建机安装 GUI 与打包依赖后，可生成 Windows 10/11 x64 便携文件夹和 ZIP：

```powershell
python -m pip install -e ".[gui,packaging]"
scripts\build_gui_exe.cmd
```

产物位于 `release/CANFDOffsetOptimizer-<version>-win-x64/` 及同名 ZIP。终端用户只需
完整解压后双击 `CANFDOffsetOptimizer.exe`，不需要安装 Python 或项目依赖。程序固定在
EXE 同级目录创建并使用 `user_input`、`user_output`；因此应解压到桌面、工作目录等
当前用户可写位置，不能放入 `Program Files`。升级时应保留这两个数据目录。

正常 GUI 固定使用 **RealBackend**：工作区 DBC 资格、报文字段、原始/优化 Offset、指标和
负载数组均来自核心 parser/project loader/GCLS。真实 adapter 初始化失败时界面明确显示
“仅预览 / 优化不可用”并禁用运行，不会静默回退 Mock，也不会生成伪造的 `user_output`。
`FixtureBackend` 只供自动化 GUI 测试显式注入；`MockBackend` 默认失败关闭。

GUI 支持选择 `payload_bytes` 和 `frame_time_us` 两种权重。未提供可用 ARXML 总线时序时，
只能选择 `payload_bytes`，并按核心现有语义固定使用 `peak` 模式。界面直接显示发现的名称
（如 `PT`、`DA`、`DK`），不扩写或解释网段缩写。

使用说明见 `docs/gui_user_guide.md`，架构边界见 `docs/gui_architecture_plan.md`。

对同一 DBC 比较原始 Offset、最小 Offset、Greedy、Greedy + 1-opt 和完整 GCLS：

```bash
python -m canfd_offset_optimizer compare --dbc input/dbc/network.dbc --arxml input/arxml --config input/config/project.yaml --output output/comparison/network --weight-mode payload_bytes --seed 0 --restart-mode fixed --restart-attempts 21
```

对同一 DBC 同时运行 `payload_bytes` 的 peak 基线，以及 `frame_time_us` 的三种目标：

```bash
python -m canfd_offset_optimizer compare-weights --dbc input/dbc/network.dbc --arxml input/arxml --config input/config/project.yaml --output output/comparison/dual_weight/network --channel ARXML_CONTROLLER_SHORT_NAME --seed 0 --restart-mode fixed --restart-attempts 21
```

`--channel` 使用 ARXML Controller 的完整 `SHORT-NAME` 覆盖 YAML 通道，不根据文件名
猜测，并会进入 warning、字段来源和 JSON 摘要。该参数也可用于 `optimize` 和
`compare`。

`--weight-mode` 是本次比较的显式覆盖，不修改 YAML，并会写入 warning、字段来源和
`comparison_summary.json`。`payload_bytes`/`unit` 只比较释放均衡度，不代表物理
总线占用时间。

`optimize` 子命令的输出产物：

```text
<output>/
├── results/
│   ├── offsets.csv
│   ├── slot_loads.csv
│   ├── summary.json
│   ├── <网段>_restart_records.jsonl
│   └── <网段>_peak_reference_restart_records.jsonl  # balanced 时生成
├── plots/
│   ├── steady_load.png
│   └── startup_load.png
└── logs/
    └── run.log
```

`compare` 子命令的输出产物：

```text
<output>/
├── results/
│   ├── algorithm_comparison.csv
│   ├── offsets_comparison.csv
│   ├── slot_loads_comparison.csv
│   ├── comparison_summary.json
│   ├── <网段>_restart_records.jsonl
│   └── <网段>_peak_reference_restart_records.jsonl  # balanced 时生成
├── plots/
│   ├── steady_load_comparison.png
│   ├── startup_load_comparison.png
│   ├── steady_congestion_heatmap.png
│   ├── startup_congestion_heatmap.png
│   ├── steady_message_timeline.png
│   └── startup_message_timeline.png
└── logs/
    └── run.log
```

上述 CSV 和 PNG 的实际文件名都会增加网段前缀，例如
`SU_offsets_comparison.csv`、`SU_startup_congestion_heatmap.png`。所有 CSV 字段使用
中文；`CAN_ID`、`Offset`、`payload_bytes_GCLS_Offset`、`frame_time_us_GCLS_Offset`、
`GCLS`、`BRS` 等领域名称保持原样。

其中 `congestion_heatmap.png` 用颜色和格内帧数展示每个 5 ms 时隙的拥挤程度，
`message_timeline.png` 直接对比原始方案与 GCLS 中每条报文的发送时刻；两者均不
表示真实总线占用率。`offsets_comparison.csv` 使用中文字段名，周期和 Offset 均以
毫秒（ms）展示，便于直接审阅和交付。

CSV 使用 UTF-8 with BOM，可直接由 Windows Excel 打开。

`compare-weights` 会保留近似权重 peak 基线、正式 balanced 报告和两个物理实验模式：

```text
<output>/
├── payload_bytes/                 # payload-byte + peak 五阶段完整报告
├── frame_time_us/                 # frame-time + balanced 正式报告
├── objective_modes/
│   ├── peak/                      # 严格峰值实验报告
│   └── variance/                  # 方差优先实验报告
├── results/
│   ├── weight_mode_comparison.csv
│   ├── offsets_weight_mode_comparison.csv
│   ├── weight_mode_summary.json
│   ├── objective_mode_comparison.csv
│   ├── offsets_objective_mode_comparison.csv
│   └── objective_mode_summary.json
├── plots/
│   └── steady_objective_mode_comparison.png
└── logs/
    └── run.log
```

当各网段按 `<dual_weight>/<网段>/` 结构运行时，还会在 `dual_weight/` 根目录自动生成：

```text
ALL_offsets_weight_mode_comparison.csv
```

该表按“网段、报文”汇总全部已完成网段的报文名称、CAN ID、周期、载荷长度、保守帧
占用时间、DBC 原始 Offset、`payload_bytes` GCLS Offset，以及 `frame_time_us` 的
peak、balanced、variance 三种 GCLS Offset。

跨权重汇总只计算每种模式相对其自身原始 Offset 的改善，不比较 Byte 与 μs 原始目标的
绝对大小。生产建议优先审阅 `frame_time_us/` 中的 balanced 结果；`payload_bytes`、
peak 和 variance 作为对照保留。

## Restart 策略与审计

`attempts` 统一表示**包含首次确定性 Greedy 尝试在内的总尝试数**。推荐配置使用确定性
自适应策略：至少运行 20 次，此后每 10 次检查一次完整 Peak 词典序目标；连续 20 次没有
严格改善即停止，最多运行 80 次。到达 80 次上限只表示“达到上限但未验证饱和”，不构成
全局最优或充分搜索证明。

```yaml
optimization:
  restart_policy:
    mode: adaptive
    min_attempts: 20
    check_interval: 10
    patience_attempts: 20
    max_attempts: 80
```

固定成本实验可使用：

```yaml
optimization:
  restart_policy:
    mode: fixed
    total_attempts: 21
```

旧 YAML `random_restarts=N` 和旧 CLI `--restarts N` 暂时保留“额外 N 次”的兼容语义，
会规范化为 `total_attempts=N+1` 并产生弃用 warning；同一 YAML 同时声明旧字段和
`restart_policy` 会明确报错。

普通 `optimize`、`compare` 和 `compare-weights` 会在 `results/` 中输出带网段前缀的
`restart_records.jsonl`。每行包含 attempt index/kind、seed、完整命名目标、完整 Offset
assignment、规范化 assignment SHA-256、运行时间、评价次数和接受次数。balanced 的严格
Peak 参考阶段单独保存。运行摘要同时记录请求策略、实际 attempts、停止原因、是否达到上限
以及审计文件位置。

## 诊断命令

下列命令属于独立诊断流程，不改变 GCLS 作为主启发式求解器的定位：

```bash
python -m canfd_offset_optimizer analyze-restarts --dbc input/dbc/network.dbc --arxml input/arxml --config input/config/project.yaml --output output/diagnostics/network/restart_stability --channel ARXML_CONTROLLER_SHORT_NAME --batch-count 30 --max-attempts 80 --checkpoints 1,3,5,10,20,21,40,80

python -m canfd_offset_optimizer scan-tolerances --dbc input/dbc/network.dbc --arxml input/arxml --config input/config/project.yaml --output output/diagnostics/network/tolerance_scan --channel ARXML_CONTROLLER_SHORT_NAME --tolerances 0,0.02,0.05,0.08,0.10,0.15,0.20

python -m pip install -e ".[solver]"
python -m canfd_offset_optimizer verify-cpsat --dbc input/dbc/network.dbc --arxml input/arxml --config input/config/project.yaml --output output/diagnostics/network/cpsat --channel ARXML_CONTROLLER_SHORT_NAME --tolerance 0.05 --time-limit-seconds 300
```

- `analyze-restarts` 保存 append-only `restart_records.jsonl`，支持 `--resume`，并校验输入、
  配置、主键和 assignment hash；报告目标稳定性与 assignment 稳定性、跨批命中率和
  restart 饱和曲线。
- `scan-tolerances` 固定扫描多档峰值宽容度，只复用同一个严格 Peak 参考。某档没有改善
  仅表示当前 GCLS 未找到预算内改善，不证明该可行域不存在更优解。
- `verify-cpsat` 使用可选 OR-Tools 在同一离散 Offset、半开稳态窗口、multiplicity、帧时间
  权重和峰值预算下最小化 `Qss`。只有 `OPTIMAL` 可证明该**固定离散模型和预算**下的
  最优值；`FEASIBLE` 只报告可行解、best bound 和 gap，`UNKNOWN/INFEASIBLE` 不能用于
  宣称 GCLS 已最优。

项目对 GCLS 的统一表述是“获得高质量、可复现的近似解”，不将启发式结果表述为已证明的
全局最优 Offset。

## 质量检查

```bash
python -m pytest -q
python -m ruff check src tests
python -m mypy src
python -m pytest --cov=canfd_offset_optimizer --cov-report=term-missing
```

清理 Python 字节码缓存可运行：

```bat
scripts\clean_pycache.cmd
```

设计与实现边界以以下文档为准：

1. `docs/01_research_and_design.md`
2. `docs/02_project_structure_and_code_conventions.md`

## 许可证

本项目采用 [GNU Affero General Public License v3.0 only](LICENSE)，SPDX 标识为
`AGPL-3.0-only`。
