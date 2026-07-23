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

免安装版请完整解压 `CANFDOffsetOptimizer-<version>-win-x64.zip`，然后双击
`CANFDOffsetOptimizer.exe`。便携包已经包含 Python、PySide6 和全部运行依赖。程序固定在
EXE 同级目录创建并使用：

```text
user_input/
user_output/
```

整个程序文件夹必须位于当前用户有写权限的位置，不能放在 `Program Files`，也不能直接在
ZIP 内运行。升级时先退出程序，再保留或复制旧版本的 `user_input` 和 `user_output`。

## 统一工程导入

可以一次拖入多个文件、目录或两者混合。每次导入创建独立工作区：

```text
user_input/<timestamp>_<project>/
```

原文件不被修改。`import_manifest.json` 记录原始绝对路径、工作区相对路径、类型、
大小、SHA-256、导入时间、去重/冲突状态和解析使用状态。

至少需要一个 DBC。YAML/YML 项目配置、ARXML 和路由报文排除表均可选：

- `.xlsx` 路由报文排除表与其他文件一起拖入统一导入区，不提供独立路径输入框；
- 标准网关路由配置表以 `直接报文路由` Sheet 为权威数据源（Sheet 名末尾空格也兼容）。
  解析器只读取目标侧的 `目标网段报文名称`、`目标网段报文CANID` 和
  `目标网段CAN通道`，并将 `DACAN`、`DMCAN`、`ICCAN` 等通道映射为 `DA`、`DM`、`IC`；
- 旧版完整通信路由表继续以 `Routing(FLZCU)` Sheet 为左域数据源，
  自动忽略 `Cover`、`History`、`Routing(FRZCU)` 和 `信号转义`。解析器读取
  `Service Subscriber Data` 下的目标 `Msg Name`、`Msg ID`，再把
  `Service Subscriber Subnet` 横向矩阵中非空的 CAN/CAN FD 订阅网段逐项展开；例如
  `FL_CANFD_IC`、`FL_CAN_BD` 分别映射为 `IC`、`BD`。LIN 目标不属于当前 DBC Offset
  优化范围，不生成排除记录；
- 不含 `直接报文路由` 和 `Routing(FLZCU)` 的简化表仍使用明确别名映射而不是模糊猜测：目标网段支持
  `目标网段`、`目标网络`、`目标总线`、`target_network`、`destination_network`、`target bus`；
  CAN ID 支持 `CAN ID`、`报文ID`、`消息ID`、`帧ID`、`message_id`、`identifier`；可选报文名
  支持 `报文名`、`报文名称`、`消息名`、`消息名称`、`message_name`；
- 路由表按“目标网段 + CAN ID”匹配。目标网段通过当前工程的 `network_name` 精确映射为稳定
  `network_id`，CAN ID 支持十六进制 `0x123`、`123h` 和十进制 `291`；报文名只用于审计；
- 解析优先级固定为 `直接报文路由`、`Routing(FLZCU)`、简化平铺表。未提供路由表时排除数为 0；
  提供的 `.xlsx` 损坏、简化表缺少目标网段/CAN ID 列或任一权威 Sheet 模板结构不完整时会明确
  阻止运行，不会回退到低优先级 Sheet 或假装成 0 条；
  单条未找到、歧义或无效 CAN ID 会记录诊断并继续；

- 用户没有提供 YAML/YML 时，导入器自动把程序内置的 `default_project.yaml` 复制为本次
  `user_input/<session>/config/project.yaml`。内置文件内容与仓库
  `input/config/project.yaml` 一致，并在 `import_manifest.json` 和日志中明确标记；
- 用户提供一个 YAML/YML 时优先使用用户文件，不叠加默认配置；提供多个仍属于阻塞冲突；
- 因此只导入一个 DBC 也可以开始；前提是该 DBC 至少包含一条核心支持的周期 CAN FD TX 报文。
  如果 DBC 只有经典 CAN、RX 或非周期报文，界面会明确显示“没有可优化网段”，而不是误报输入不完整；

- 批量设置中的权重选项只作用于 CAN FD 网段：存在唯一可解析的 ARXML Controller 时，
  可选择“帧时间权重（`frame_time_us`）”或 Payload 权重；无法唯一对应时只开放
  `payload_bytes`，不会猜测通道；
- Classic CAN 网段固定使用“Payload 长度近似权重（`payload_bytes`）”，不可手动切换，
  并在技术详情和输出中标记
  `classic_weight_model = "payload_bytes_approximation"`；
- Classic CAN 的负载单位为 `Byte/slot`，Zss 是加权峰值，Qss 是加权平方和；该近似仅用于
  相对均衡，不代表实际占用时间、真实总线负载百分比或 75% 物理阈值判断，Nvio/Vvio
  显示为“不适用”；
- 同一物理网段若同时包含 eligible Classic CAN 与 CAN FD 周期 TX，本版本明确拒绝，
  不混合 Byte 与 μs。Peak、Balanced、Variance 均可用于每个网段自己的权重单位。

后续改进项：实现包含标准/扩展帧、协议开销、位填充和 nominal bitrate 的完整 Classic CAN
`frame_time_us` 模型；本版本不实现该精确模型。

网段名直接显示 `DA`、`DK`、`PT` 等原名，不解释缩写。
`..._ADAS BUS_Matrix_...` 一类 DBC 文件名会显示并匹配为 `ADAS_BUS`，完整文件名仍只作为来源信息。


### 必须先选择 DBC 本机发送节点

导入和解析完成后，主界面进入“待选择发送节点”，此时“开始全部网段优化”保持禁用，并提示
“请先完成 DBC 本机发送节点选择。”点击批量设置中的“选择发送节点”打开独立窗口：

1. 左侧逐个选择 DBC；
2. 右侧勾选该 DBC 中代表本机 ECU 的一个或多个发送节点；
3. 如果某个 DBC 只用于参考，则明确勾选“该 DBC 不参与本次优化”；
4. 所有 DBC 都处理完成后点击“应用选择”。

程序不会根据 `FLZCU`、`GW`、`VCU` 或文件名自动猜测本机节点。节点名采用精确匹配；
“在其他 DBC 中选择同名节点”只有用户主动点击后才传播完全相同的名称。取消窗口不会应用草稿。
未知/空发送节点和 `Vector__XXX` 会显示为不可选择的审计项。

预览依次显示 DBC 总报文、所选节点发送数、基础合资格数、其他 ECU 排除数、路由排除数和最终
参与优化数。只有确认选择、输入合法且至少一个网段存在最终合资格报文时才能开始。所有 DBC
明确排除、所选节点没有周期候选或候选全部被路由表排除时仍不能运行。

选择按工作区相对路径和文件 SHA-256 形成的 `dbc_id` 保存。重新导入时，相同内容可安全保留；
新增或内容变化的 DBC 回到未处理，不能仅凭同名文件复用。运行完成后修改选择会立即清空当前旧
结果并要求重新优化，避免新配置继续显示旧 Offset 或负载曲线。

## 资格判定与批量状态

正式资格顺序为“用户所选本机发送节点 → 核心基础资格 → 路由表目标侧排除”。只有发送节点
与当前 DBC 选择集合有交集的报文才交给核心继续检查；路由表再从这批本机基础合资格周期 TX 中
执行排除。匹配成功的 `routing_excluded` 报文在创建搜索状态和调用 GCLS 前即被移除。每个 DBC 都会在工程汇总中
保留一行：可优化的 CAN FD 或 Classic CAN 网段进入 GCLS；没有可优化周期 TX、同一物理
网段混合两种协议、全部基础资格报文均被路由排除或其他核心解析不支持的网段标记为
`skipped`，并显示明确原因。

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
user_output/<YYYYMMDD_HHMMSS_ffffff>/
├── logs/
│   ├── batch.log
│   └── <network>.log
├── plots/
│   ├── <network>_load_curve.png
│   └── <network>_heatmap.png
├── results/
│   ├── networks_summary.csv
│   ├── run_config.json
│   ├── routing_exclusion_summary.csv
│   ├── message_eligibility.csv
│   └── <network>/offsets.csv
└── dbc/
    └── <原 DBC 文件名>.dbc
```

`results/networks_summary.csv` 汇总所有网段（包括失败、跳过和取消）；成功网段的 Offset 明细放在
各自子目录。`routing_exclusion_summary.csv` 保留原始目标网段、规范化 `network_id`、规范化及原始 CAN ID、Excel/DBC 报文名、
匹配状态、排除状态、来源文件、Sheet、行号和诊断。`message_eligibility.csv` 逐条记录 DBC、
网段、CAN ID、报文名、全部 transmitter、所选节点命中、周期、路由命中、最终状态和排除原因。
`run_config.json` 除路由统计外，还在 `sender_node_selection` 中记录 dbc_id、文件、网段、所选节点、
明确排除和 revision。`logs` 保存批次日志和每个网段的独立日志。`plots` 自动导出每个成功网段
4 个真实稳态超周期的重复负载曲线，以及不重复的单个稳态窗口拥挤热力图。

`dbc` 中的文件是导入工作区 DBC 的新副本，不会修改用户传入的原文件。核心 parser 会把 CAN FD DBC 的
`BA_DEF_DEF_` 消息属性默认值解析为未显式赋值报文的真实原 Offset。写入器在已有
`GenMsgStartDelayTime`、`GenMsgDelayTime` 或 `MsgStartDelayTime` 属性行中只替换数字；对于继承
默认值的参与优化报文，则在输出副本末尾补充显式 `BA_` 赋值。新增属性按 DBC 已声明且实际使用
最多的 Offset 属性选择，不会发明未声明属性。原有编码、换行、空格、注释、顺序及其它字节保持
不变。批次目录只使用微秒时间戳，DBC 最终文件名保持与来源文件一致；写入临时文件使用短随机名，
DBC 最终路径采用 240 字符安全预算。同一优先属性重复、缺少有效默认值、未声明可写属性、路径超限
或写后校验不一致时，只将 DBC 导出标记为失败：核心优化、Offset CSV、负载图、热力图和 GUI 结果
继续保留，网段仍计为成功并显示“成功（DBC写回失败）”。Classic CAN 临时方案仍要求显式原
Offset。网段日志和汇总 CSV 会记录 DBC 输出状态、错误及替换、补充条数。

Offset 表默认只包含真正进入 GCLS 的报文。路由排除报文没有 `optimized_offset`，不会进入
assignment、“只看已修改报文”或 DBC Offset replacement；其原始 DBC 内容在输出副本中保持不变。
Offset 表中的报文名、CAN ID、周期和原始 Offset 来自核心加载模型；优化 Offset、指标、
Attempts 和四组负载数组来自该网段自己的核心 `OptimizationResult`。切换网段时 GUI 先清空
旧曲线，再绑定当前 DTO，并在标题显示网段、窗口类型和源 DBC。失败、跳过和无选择状态均不
复用上一次成功曲线。

负载页明确命名为“可优化报文负载曲线”。当前核心负载模型统计参与 Offset 优化的报文集合，
不存在不可调度背景负载层；因此路由报文从原始和优化后两组负载中一致排除，GUI 不自行重算。
稳态曲线以核心返回的单个真实超周期数组和 `LoadWindowMetadata` 为唯一数据源。元数据统一记录
时隙宽度、稳态/启动时隙数、真实稳态超周期和启动范围。GUI 默认把当前网段的真实稳态序列重复
展示 4 次；可切换 1、2、4 或 10 个完整超周期，选项同时显示对应实际毫秒数。例如 PT 的
100 ms 超周期默认显示 400 ms，BD 的 500 ms 默认显示 2000 ms，GL 的 1000 ms 默认显示
4000 ms，IC 的 2000 ms 默认显示 8000 ms。展示不截断、不补空白、不插值、不修改 DTO，也不
重新运行优化。启动窗口始终只显示核心返回的真实范围，并禁用稳态重复数选项。导出 PNG 使用
当前选择的完整重复范围。

“负载热力图”页参考主分支 `congestion_plotter` 的拥挤热力图语义：上排为原始方案，下排为
优化后方案；颜色按同一时隙释放帧数固定分为白色 0 帧、绿色 1 帧、黄色 2 帧、橙色 3 帧、
红色 4 帧、黑色 5 帧及以上。帧数来自核心时隙快照，不从负载值推测。稳态和启动热力图均只显示核心返回
的单个真实窗口，不使用负载曲线的多超周期重复规则。热力图页顶部的“网段”下拉框列出本批次
所有成功网段，可直接切换；选择会同步结果概览、Offset、负载曲线和日志的当前网段。

热力图不再把任意数量的时隙压缩进固定宽度。单格宽度按当前字体下“帧数”和当前权重负载文本
实测宽度加留白确定，并设有可读最小值；画布宽度按“时隙数 × 单格宽度”自然增长。原始行、
优化后行和时间轴位于同一个水平滚动画布中，左侧行标题与图例固定。切换网段或稳态/启动窗口时
会绑定该网段该窗口自己的 DTO、重建宽度并回到起点，不插值、合并、重采样或重复热力数组。

非空热力格直接显示两行：`N 帧` 与当前真实累计负载；`payload_bytes` 显示 `B`，
`frame_time_us` 显示 `μs`。热力图下方“拥挤时隙明细”默认列出原始和优化后所有 4 帧及以上
时隙，每条报文独占一行，并显示时间窗口、同时帧数、时隙总负载、报文名、完整十六进制 CAN ID、
周期及对应状态的 Offset；可筛选仅 4 帧或 5 帧及以上。点击拥挤格会定位表格，点击表格会滚动并
高亮对应热力格。没有拥挤时隙时显示明确空状态。

“导出热力图 PNG”渲染完整逻辑画布，与当前滚动位置无关；图片包含全部时隙、两行和时间轴。
达到平台单图尺寸或内存安全上限时明确报告“当前热力图过宽，无法以单张 PNG 导出”，不会静默
缩小为不可读图片。进度条只有在当前网段的负载图、自动热力图和 DBC 副本都生成后才把该网段
标记为完成。

## 批量优化设置的信息层级

主窗口启动后默认最大化。“批量优化设置”默认只展示网段统计、模式、紧凑的
Offset 范围与步长、候选摘要，以及“高级搜索设置”入口。基础区域分别显示 Classic CAN
和 CAN FD 权重：Classic CAN 固定为只读的 `payload_bytes` 长度近似；CAN FD 可选择
`frame_time_us` 或 `payload_bytes`，默认使用 `frame_time_us`。

修改前，权重、模式、Balanced tolerance、Restart、Restart 参数、Candidate pool、
三个 Offset 字段和 3-opt 混在基础区域或同一个纵向表单中。修改后层级如下：

```text
批量优化设置
├─ 网段统计 / 查看详情
├─ 模式
├─ Classic CAN 权重（固定只读）
├─ CAN FD 权重（可选择）
├─ Offset 范围、步长、候选摘要
└─ 高级搜索设置（默认折叠）
   ├─ Balanced tolerance（仅 Balanced 显示）
   ├─ Restart
   ├─ 固定 attempts 或自动最少/最多 attempts（按 Restart 二选一显示）
   ├─ Candidate pool
   └─ 3-opt 与耗时提示
```

折叠或条件隐藏只改变可见性，不重置任何值；再次显示时保留用户先前输入。

## Offset 搜索范围

基础设置可直接设置 Offset 最小值、最大值和步长，单位均为整数毫秒。默认值为
`15 / 100 / 5 ms`，因此默认候选集与原版本完全一致。候选值严格按
`min + k × step <= max` 生成；最大值不要求能被步长命中，也不会被额外追加。
界面会实时显示候选数量和实际最大候选值，候选较多时给出耗时提示，但不会截断。

原 DBC 中的 Offset 是真实基线输入，不要求属于新候选集，也不会被取整或替换；
优化结果则必须属于本次配置生成的候选集。每次批量输出会在
`results/run_config.json` 的 `offset_search` 字段记录配置最大值、实际最大候选值和候选数量。

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
