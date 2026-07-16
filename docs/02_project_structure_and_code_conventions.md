# 工程目录、文件职责与代码规范

## 1. 目标目录

项目根目录固定命名为：

```text
canfd-offset-optimizer
```

Python 包名固定为：

```text
canfd_offset_optimizer
```

目录如下：

```text
canfd-offset-optimizer/
├── input/
│   ├── dbc/
│   ├── arxml/
│   └── config/
│       └── project.yaml
├── output/
│   ├── results/
│   ├── plots/
│   └── logs/
├── docs/
│   ├── 01_research_and_design.md
│   ├── 02_project_structure_and_code_conventions.md
│   └── 03_implementation_plan.md
├── clean_pycache.cmd
├── src/
│   └── canfd_offset_optimizer/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── config.py
│       ├── models.py
│       ├── exceptions.py
│       ├── parsers/
│       │   ├── __init__.py
│       │   ├── dbc_parser.py
│       │   ├── arxml_parser.py
│       │   └── project_loader.py
│       ├── timing/
│       │   ├── __init__.py
│       │   └── frame_time.py
│       ├── timeline/
│       │   ├── __init__.py
│       │   ├── slot_map.py
│       │   └── state.py
│       ├── optimization/
│       │   ├── __init__.py
│       │   ├── objective.py
│       │   ├── greedy.py
│       │   ├── local_search.py
│       │   └── gcls.py
│       └── reporting/
│           ├── __init__.py
│           ├── csv_writer.py
│           ├── plotter.py
│           └── summary_writer.py
├── tests/
│   ├── fixtures/
│   │   ├── dbc/
│   │   ├── arxml/
│   │   └── config/
│   ├── unit/
│   │   ├── test_config.py
│   │   ├── test_models.py
│   │   ├── test_frame_time.py
│   │   ├── test_slot_map.py
│   │   ├── test_state.py
│   │   ├── test_objective.py
│   │   ├── test_greedy.py
│   │   └── test_local_search.py
│   └── integration/
│       └── test_end_to_end.py
├── pyproject.toml
├── README.md
├── .gitignore
└── LICENSE
```

## 2. 根目录职责

### `input/`

只放用户输入，不放程序生成内容。

- `input/dbc/`：真实 DBC 文件；程序默认要求恰好选择一个主 DBC，存在多个时必须由 CLI 或配置指定。
- `input/arxml/`：ARXML 文件集合；允许空目录。解析器递归扫描 `.arxml`，不得依赖固定文件名。
- `input/config/project.yaml`：算法参数、字段覆盖和模型规则。

### `output/`

所有内容均由程序生成，可随时删除重建。

- `output/results/`：`offsets.csv`、`slot_loads.csv`、`summary.json`。
- `output/plots/`：负载柱状图、优化前后对比图。
- `output/logs/`：每次运行日志。

### `docs/`

Codex 编码时必须优先读取的三份设计文档。代码与文档冲突时，不得自行猜测，应在提交说明中列出冲突。

### `clean_pycache.cmd`

仅递归删除仓库中的 `__pycache__` 目录，不执行项目创建、依赖安装或核心业务逻辑。

### `src/`

采用 `src-layout`，避免测试时误导入当前工作目录中的同名包。

### `tests/`

测试必须独立于真实项目文件。真实 DBC/ARXML 不得提交到公开仓库；测试夹具应使用脱敏、最小化样例。

## 3. Python 文件职责

### `__init__.py`

定义包版本和公共导出，不执行文件读取、日志初始化或优化计算。

### `__main__.py`

支持：

```bash
python -m canfd_offset_optimizer
```

内容只调用 `cli.main()`。

### `cli.py`

命令行入口，负责：

- 解析参数；
- 调用 `ProjectLoader`；
- 调用 GCLS；
- 调用报告模块；
- 根据异常返回非零退出码。

不得在此文件实现数学算法。

### `config.py`

定义并读取：

- `NetworkOverrides`；
- `OptimizationConfig`；
- `ModelConfig`；
- `ProjectConfig`。

负责 YAML 类型校验、范围校验和默认值，不读取 DBC/ARXML。

### `models.py`

定义不可或尽量不可变的数据类：

- `CanMessage`；
- `ChannelConfig`；
- `NetworkModel`；
- `OffsetAssignment`；
- `ObjectiveValue`；
- `OptimizationResult`；
- `RunSummary`。

该文件不得引用 `cantools` 或 `lxml` 类型。

### `exceptions.py`

定义可定位的领域异常：

- `ConfigurationError`；
- `InputFileError`；
- `MissingFieldError`；
- `DataConflictError`；
- `UnsupportedMessageError`；
- `OptimizationError`。

### `parsers/dbc_parser.py`

使用 `cantools` 读取 DBC，输出标准化的报文中间数据。职责包括：

- 识别标准/扩展帧；
- 读取长度、发送节点、周期和原 Offset；
- 过滤非周期报文；
- 保存 DBC 定义顺序；
- 生成字段来源信息和诊断信息。

禁止在此处计算 Offset。

### `parsers/arxml_parser.py`

使用 `lxml` 和 XPath 读取必要 ECUC 字段，输出：

- 通道；
- nominal bitrate；
- data bitrate；
- BRS；
- 字段来源路径。

必须处理 XML namespace；不得假设 Vector 导出的所有项目具有相同容器层级。

### `parsers/project_loader.py`

聚合 DBC、ARXML 和 YAML，完成：

- 字段优先级合并；
- 冲突检测；
- 单位归一化；
- 周期集合检查；
- 超周期计算；
- `NetworkModel` 构造。

### `timing/frame_time.py`

把报文格式和通道参数转换成整数微秒权重。必须把精确公式与近似模式分开，并让输出携带 `weight_mode`。

### `timeline/slot_map.py`

预计算每个 `(message, offset)` 在启动窗口和稳态窗口命中的时隙索引。该模块应为纯函数，不维护全局状态。

### `timeline/state.py`

维护搜索过程中的可变状态：

- `steady_slot_loads`；
- `startup_slot_loads`；
- `steady_slot_counts`；
- 当前 Offset；
- apply/remove/rollback 操作。

必须提供一致性检查方法。任何试探操作都必须可无损撤销。

### `optimization/objective.py`

只定义和计算词典序目标：

```text
(N_vio, V_vio, Z_steady, Z_startup, sum_square_load, K_max)
```

不得进行搜索。

### `optimization/greedy.py`

实现确定性贪心构造。输入统一模型和预计算数据，输出完整合法 Offset 分配。

### `optimization/local_search.py`

实现：

- 单报文重定位；
- 热点时隙选择；
- 冲突候选提取；
- 双报文邻域移动；
- Offset 交换。

只接受严格改善。

### `optimization/gcls.py`

默认求解流程编排器：

```text
排序/扰动 -> Greedy -> 1-opt -> 冲突双报文 -> 保留最优
```

负责随机种子和重启次数，不重复实现各子算法。

### `reporting/csv_writer.py`

输出 `offsets.csv` 和 `slot_loads.csv`，使用 UTF-8 with BOM，方便 Windows Excel 打开中文。

### `reporting/plotter.py`

输出负载图。绘图只消费结果对象，不参与指标计算。

### `reporting/summary_writer.py`

输出机器可读的 `summary.json`，包括输入哈希、配置、警告、指标、随机种子和运行时间。

## 4. Doxygen 风格 Python 注释规范

这里采用 **Doxygen 风格 docstring**，不是在每一行代码旁边写废话。模块、公共类、公共函数和复杂私有函数必须写注释；显而易见的局部变量无需逐行解释。

### 4.1 模块注释

```python
"""! @file slot_map.py
@brief 预计算周期报文在启动窗口和稳态窗口内命中的离散时隙。

@details
本模块只执行时间轴展开与时隙索引计算，不维护优化状态，
也不读取 DBC、ARXML 或 YAML。
"""
```

### 4.2 数据类注释

```python
@dataclass(frozen=True, slots=True)
class CanMessage:
    """! @brief 描述一条参与 Offset 优化的周期 CAN FD 报文。

    @param name 报文名称。
    @param can_id 规范化后的 CAN ID。
    @param is_extended 是否为 29 位扩展帧。
    @param cycle_time_us 周期，单位为微秒。
    @param frame_time_us 帧权重，单位为微秒。
    @param allowed_offsets_us 合法 Offset 的升序元组。
    @param original_offset_us 原始 Offset；未知时为 None。
    @param sender_ecu 发送 ECU 名称。
    @param definition_index 报文在 DBC 中的定义顺序。
    """
```

### 4.3 函数注释

```python
def build_steady_slots(
    message: CanMessage,
    offset_us: int,
    window: TimeWindow,
) -> tuple[int, ...]:
    """! @brief 计算报文在稳态窗口内命中的时隙索引。

    @param message 参与计算的周期报文。
    @param offset_us 待评价的首次发送延迟。
    @param window 稳态窗口与时隙宽度。
    @return 按时间升序排列的时隙索引元组。

    @raises ValueError 当 Offset 不属于报文合法集合时抛出。

    @invariant 返回索引均满足 0 <= index < window.slot_count。
    @note 半开区间规则统一使用 [start, end)。
    """
```

### 4.4 复杂逻辑的行内注释

行内注释解释“为什么”，不要复述代码：

```python
# 先移除旧位置，避免候选 Offset 与自身负载叠加。
state.remove(message, current_offset)
```

禁止：

```python
# 把 current_offset 赋值给 old_offset
old_offset = current_offset
```

### 4.5 TODO 规范

```python
# TODO(owner): 支持 Vector 自定义 BRS 属性名称映射。
```

不得留下没有上下文的 `TODO`、`FIXME` 或注释掉的大段旧代码。

## 5. 类型与质量要求

- Python 3.11+；
- 所有公共函数使用类型注解；
- 时间内部统一使用整数微秒；
- Offset、周期和时隙边界禁止使用浮点数；
- 数据模型优先使用 `dataclass(frozen=True, slots=True)`；
- 路径使用 `pathlib.Path`；
- CSV 使用标准库 `csv`；
- 日志使用标准库 `logging`；
- 测试使用 `pytest`；
- 格式与静态检查使用 `ruff`、`mypy`；
- 不在模块 import 时执行文件 I/O；
- 不捕获后静默吞掉宽泛 `Exception`。
