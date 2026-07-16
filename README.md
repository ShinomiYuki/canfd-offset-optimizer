# CAN FD Offset Optimizer

基于 GCLS（Greedy Construction、Single-message Relocation、Conflict-directed Pair
Search、Reproducible Random Restarts）的周期 CAN FD 报文首次发送 Offset 均衡工具。

工具采用整数微秒和 5 ms 离散时隙，严格区分：

- 启动窗口 `[0, O_max)`；
- 稳态窗口 `[O_max, O_max + hyperperiod)`；
- 首次释放语义 `release_time = offset + k * cycle_time`。

## 输入约定

- DBC：只解析当前 DBC 节点发送的 **TX 周期报文**。发送方为 `Vector__XXX`
  的矩阵条目视为 RX 并过滤；
- ARXML：递归扫描 `.arxml`，读取目标通道 nominal bitrate、data bitrate 和 BRS；
- YAML：配置候选 Offset、GCLS 参数，并可显式覆盖 ARXML 字段。所有覆盖都会写入
  warning 和 `summary.json`。

当 `weight_mode: frame_time_us` 时，nominal bitrate 与 BRS 不得缺失，BRS 开启时还
必须提供 data bitrate。该模式是包含 ISO CAN FD 固定/动态填充上界、但不包含
intermission 的保守帧时长估计，不宣称逐位精确仿真。近似模式必须显式选择
`payload_bytes` 或 `unit`，其报告不会套用物理微秒阈值。

## 安装与运行

```bash
python -m pip install -e ".[dev]"
python -m canfd_offset_optimizer optimize --dbc input/dbc/network.dbc --arxml input/arxml --config input/config/project.yaml --output output --seed 0 --restarts 20 --log-level INFO
```

输出目录：

```text
output/results/offsets.csv
output/results/slot_loads.csv
output/results/summary.json
output/plots/steady_load.png
output/plots/startup_load.png
output/logs/run.log
```

CSV 使用 UTF-8 with BOM，可直接由 Windows Excel 打开。

## 质量检查

```bash
python -m pytest -q
python -m ruff check src tests
python -m mypy src
python -m pytest --cov=canfd_offset_optimizer --cov-report=term-missing
```

清理 Python 字节码缓存可运行：

```bat
clean_pycache.cmd
```

设计与实现边界以以下文档为准：

1. `docs/01_research_and_design.md`
2. `docs/02_project_structure_and_code_conventions.md`
3. `docs/03_implementation_plan.md`
