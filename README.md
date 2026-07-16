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

## 安装与运行

```bash
python -m pip install -e ".[dev]"
python -m canfd_offset_optimizer optimize --dbc input/dbc/network.dbc --arxml input/arxml --config input/config/project.yaml --output output --seed 0 --restarts 20 --log-level INFO
```

对同一 DBC 比较原始 Offset、最小 Offset、Greedy、Greedy + 1-opt 和完整 GCLS：

```bash
python -m canfd_offset_optimizer compare --dbc input/dbc/network.dbc --arxml input/arxml --config input/config/project.yaml --output output/comparison/network --weight-mode payload_bytes --seed 0 --restarts 20
```

对同一 DBC 同时运行 `payload_bytes` 近似权重和 `frame_time_us` 保守物理权重：

```bash
python -m canfd_offset_optimizer compare-weights --dbc input/dbc/network.dbc --arxml input/arxml --config input/config/project.yaml --output output/comparison/dual_weight/network --channel ARXML_CONTROLLER_SHORT_NAME --seed 0 --restarts 20
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
│   └── summary.json
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
│   └── comparison_summary.json
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

`compare-weights` 会在两个权重子目录中分别保留上述完整 `compare` 产物，并额外输出：

```text
<output>/
├── payload_bytes/                 # payload-byte 五阶段完整报告
├── frame_time_us/                 # 保守帧时间五阶段完整报告
├── results/
│   ├── weight_mode_comparison.csv
│   ├── offsets_weight_mode_comparison.csv
│   └── weight_mode_summary.json
└── logs/
    └── run.log
```

当各网段按 `<dual_weight>/<网段>/` 结构运行时，还会在 `dual_weight/` 根目录自动生成：

```text
ALL_offsets_weight_mode_comparison.csv
```

该表按“网段、报文”汇总全部已完成网段的报文名称、CAN ID、周期、载荷长度、保守帧
占用时间、DBC 原始 Offset 以及两种权重的 GCLS Offset。

跨权重汇总只计算每种模式相对其自身原始 Offset 的改善，不比较 Byte 与 μs 原始目标的
绝对大小。生产建议优先审阅 `frame_time_us`，`payload_bytes` 保留为近似基线。

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
