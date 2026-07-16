# 实现顺序与 Codex 执行清单

## 1. 最先做什么

**第一步不是解析真实 DBC，也不是写 ARXML XPath。**

第一步应当先建立统一数据模型和一个手工四报文测试夹具，让核心算法完全不依赖外部文件即可运行。原因很简单：DBC/ARXML 解析具有供应商属性名和 AUTOSAR 版本差异，若一开始被解析问题卡住，就无法确认时隙模型和算法是否正确。

第一个可运行目标是：

```text
手工构造 4 条报文
→ 展开 500 ms 时间轴
→ 输出 100 个 5 ms 时隙的负载
→ 验证所有 Offset 为 0 时存在周期性聚集
```

四报文夹具：

```text
0x391 / 20 ms
0x460 / 100 ms
0x15E / 10 ms
0x31B / 50 ms
```

初始权重可以先手工指定为整数微秒；算法跑通后再接入 CAN FD 帧时长计算。

## 2. Codex 总规则

Codex 每次只完成一个可验证的工作包。不得一次性生成全项目后声称完成。每个工作包必须：

1. 先读取 `docs/01_research_and_design.md`；
2. 再读取 `docs/02_project_structure_and_code_conventions.md`；
3. 最后读取本文档对应步骤；
4. 修改代码；
5. 增加或更新测试；
6. 运行 `pytest`、`ruff check`；
7. 汇报修改文件、通过的测试和未完成项。

任何需求冲突必须显式报告，不得自行扩大范围到 FIFO、仲裁或完整 CAN 仿真。

## 3. 推荐依赖

`pyproject.toml` 主依赖：

```toml
[project]
requires-python = ">=3.11"
dependencies = [
  "cantools>=40",
  "lxml>=5",
  "PyYAML>=6",
  "matplotlib>=3.8",
]

[project.optional-dependencies]
dev = [
  "pytest>=8",
  "pytest-cov>=5",
  "ruff>=0.5",
  "mypy>=1.10",
]
```

不要加入 OR-Tools、NumPy、pandas、SciPy，除非后续有明确需求。当前规模用 Python 标准容器足够。

## 4. 编码步骤

### 步骤 1：建立数据模型与配置对象

实现：

- `models.py`；
- `config.py`；
- `exceptions.py`；
- `tests/unit/test_models.py`；
- `tests/unit/test_config.py`。

必须定义：

```text
CanMessage
ChannelConfig
NetworkModel
TimeWindow
OffsetAssignment
ObjectiveValue
OptimizationResult
ProjectConfig
```

验收：

- 所有时间使用整数微秒；
- 非法周期、非法 Offset、空候选集合会报错；
- `{10,20,50,100,500}` ms 自动得到 500 ms 超周期；
- 配置能生成 `[15,20,...,100]` ms 候选集合。

### 步骤 2：实现时隙预计算

实现：

- `timeline/slot_map.py`；
- `tests/unit/test_slot_map.py`。

功能：

- 计算启动窗口和稳态窗口；
- 预计算 `(message, offset)` 的命中时隙；
- 使用半开区间 `[start, end)`；
- 对 10 ms 报文验证一个 500 ms 稳态窗口恰好命中 50 次。

验收：

- 所有索引在 `[0, slot_count)`；
- 直接枚举释放时刻与预计算结果完全相同；
- `15 ms` 与 `25 ms` 对 10 ms 报文的稳态命中相同，但启动命中不同。

### 步骤 3：实现可回滚的时隙状态

实现：

- `timeline/state.py`；
- `tests/unit/test_state.py`。

状态数组：

```text
steady_slot_loads
startup_slot_loads
steady_slot_counts
current_offsets
```

提供：

```text
apply(message, offset)
remove(message, offset)
rollback(message, offset)
clone()
validate_invariants()
```

验收：

- apply 后总负载按预期增加；
- apply + rollback 后所有数组逐元素恢复；
- 任何合法 Offset 下稳态总负载守恒。

### 步骤 4：实现词典序目标

实现：

- `optimization/objective.py`；
- `tests/unit/test_objective.py`。

目标顺序固定为：

```text
N_vio
V_vio
Z_steady
Z_startup
sum_square_load
K_max
```

验收：

- `ObjectiveValue` 可直接比较；
- 峰值恶化不能被平方和改善抵消；
- 阈值单位为整数微秒。

### 步骤 5：实现纯贪心

实现：

- `optimization/greedy.py`；
- `tests/unit/test_greedy.py`。

要求：

- 排序键固定；
- 候选 Offset 遍历顺序固定；
- 分数相同选择更小 Offset，确保确定性；
- 输出每条报文恰好一个合法 Offset。

验收：

- 四报文夹具能得到完整解；
- 相同输入重复运行结果一致；
- 结果不劣于“所有报文都取最小 Offset”的配置。

### 步骤 6：实现单报文局部搜索

实现：

- `optimization/local_search.py` 中的 relocation；
- `tests/unit/test_local_search.py`。

要求：

- 先移除当前报文再评价候选；
- 只接受严格改善；
- 完整一轮无改善时停止；
- 记录评价次数和接受移动次数。

验收：

- 结果不得劣于输入贪心解；
- 停止时任意单条报文改变 Offset 都不能改善目标。

### 步骤 7：实现冲突导向双报文搜索

继续完善 `local_search.py`：

- 选择最热时隙；
- 提取热点贡献报文；
- 限制候选数量；
- 尝试双重定位和 Offset 交换；
- 改善后重新运行单报文重定位。

验收：

- 不扫描无关报文对；
- candidate cap 和邻域步数生效；
- 所有接受操作严格改善；
- 没有合法改善时正常返回。

### 步骤 8：实现 GCLS 编排和随机重启

实现：

- `optimization/gcls.py`。

要求：

- 每次重启只扰动同周期、同权重组内顺序；
- 每次保存随机种子；
- 全局最优使用词典序比较；
- 重启次数为 0 或 1 时仍能正常工作。

验收：

- GCLS 不劣于首次纯贪心；
- 固定 seed 得到完全相同结果；
- summary 中包含每次重启的目标值。

### 步骤 9：实现报告输出

实现：

- `reporting/csv_writer.py`；
- `reporting/summary_writer.py`；
- `reporting/plotter.py`。

验收：

- CSV 可由 Excel 正常显示中文；
- `summary.json` 可被标准 JSON 解析；
- 图表只读取结果，不修改结果；
- 输出文件名稳定。

### 步骤 10：接入 DBC

实现：

- `parsers/dbc_parser.py`；
- DBC 最小测试夹具；
- 对应单元测试。

先打印解析诊断，不要立即与算法深度耦合。解析输出必须转换为内部模型，不允许优化代码持有 `cantools.Message`。

验收：

- 正确读取标准/扩展 ID、长度、发送节点、周期和定义顺序；
- 过滤非周期报文；
- 缺周期时错误中包含报文名称；
- DBC 原始 ID 与规范化 ID 不混用。

### 步骤 11：接入 ARXML 与帧权重

实现：

- `parsers/arxml_parser.py`；
- `timing/frame_time.py`；
- 对应测试夹具和单元测试。

先支持真实项目实际出现的 AUTOSAR 版本和字段路径，再抽象通用 XPath 适配；不要凭空实现所有 AUTOSAR 版本。

验收：

- 能读取目标通道 bitrate 和 BRS，或给出明确缺失诊断；
- YAML 覆盖会产生 WARNING；
- `frame_time_us` 始终为正整数；
- 未知配置不会静默使用生产默认值。

### 步骤 12：实现 ProjectLoader、CLI 和端到端测试

实现：

- `parsers/project_loader.py`；
- `cli.py`；
- `__main__.py`；
- `tests/integration/test_end_to_end.py`。

目标命令：

```bash
python -m canfd_offset_optimizer optimize \
  --dbc input/dbc/network.dbc \
  --arxml input/arxml \
  --config input/config/project.yaml \
  --output output
```

Windows PowerShell 可使用反引号续行或写成单行。

验收：

- 从夹具输入生成完整输出；
- 错误时退出码非 0；
- 日志中包含数据来源与覆盖信息；
- 输出 GCLS 与原始配置的指标对比。

## 5. 最终检查

Codex 完成代码后必须运行：

```bash
python -m pytest -q
ruff check src tests
mypy src
```

并用四报文夹具执行一次 CLI，确认至少生成：

```text
output/results/offsets.csv
output/results/slot_loads.csv
output/results/summary.json
output/plots/steady_load.png
output/logs/run.log
```

## 6. 明确禁止的扩展

没有新指令前，不实现：

- FIFO；
- CAN 仲裁；
- 事件驱动总线仿真；
- CP-SAT；
- 模拟退火；
- 遗传算法；
- DBC/ARXML 回写；
- GUI。

这些内容会稀释当前目标，也会让 Codex 在尚未证明时隙模型正确前制造大量无关代码。
