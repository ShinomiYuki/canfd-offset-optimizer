# CAN FD Offset Optimizer

这是一个用于周期 CAN / CAN FD 报文 Offset 均衡分配的工具。当前日常入口是
PySide6 GUI；CLI 保留给开发、诊断、实验和自动化。

工具只重新分配周期报文的首次发送 Offset，使报文释放时刻在时间轴上更分散。
**Offset 优化不会降低平均负载。**

## 这个工具解决什么问题

多个周期报文即使平均负载不高，也可能因为首次发送 Offset 接近而集中落入同一时隙，
形成局部释放峰值。例如：

```text
15 ms: Msg A, Msg B, Msg C, Msg D
```

在候选 Offset 允许的情况下，优化后可以分散为：

```text
15 ms: Msg A
20 ms: Msg B
25 ms: Msg C
30 ms: Msg D
```

报文周期和总传输量没有变化，变化的是报文在时间轴上的相位。

## 优化范围

### 会修改

- 纳入优化的周期 TX 报文首次发送 Offset；
- 输出 DBC 副本中对应报文的 `GenMsgStartDelayTime`。

### 不会修改

- CAN ID；
- Cycle；
- DLC；
- Sender；
- Payload；
- Bitrate；
- 用户导入的原始文件。

DBC Matrix 通常包含多个 ECU 的 TX。DBC 中的 Sender 只表示报文发送者，并不表示该
节点就是本次工程的本机 ECU。GUI 因此要求用户逐个 DBC 选择参与优化的发送节点，
或者明确排除该 DBC。`FLZCU` 只是可能出现的节点名，没有特殊处理。

报文还需要满足当前核心的基础资格条件：

- 存在可识别的具体发送节点；
- 具有有效正周期；
- 帧格式、CAN ID 和 DLC 可解析；
- 命中用户确认的发送节点；
- 未被路由表判定为 routed TX。

Classic CAN 还会排除明确标记为事件发送、诊断、NM 或校准流量的报文，并要求存在
可用的原始 Offset。无合资格报文、全部报文被路由排除、所选报文混合 Classic CAN
与 CAN FD，或输入数据不完整时，该网段会被跳过或单独报告失败，不影响其他网段继续
运行。

## 输入文件

| 输入 | GUI 中是否必需 | 当前用途 | 未提供时 |
| --- | --- | --- | --- |
| DBC | 必需，至少一个 | 报文、CAN ID、周期、DLC、帧类型、Sender 和原始 Offset | 无法检查和优化工程 |
| 路由 Excel（`.xlsx`） | 可选 | 按“目标网段 + CAN ID”识别并排除 routed TX | 不执行路由排除，用户需要确认输入集合是否已排除路由报文 |
| ARXML | 可选 | 为 CAN FD 的 `frame_time_us` 提供 Controller、nominal bitrate、data bitrate 和 BRS | CAN FD 只能使用 `payload_bytes` |
| `project.yaml` | 可选 | 提供时隙、超周期上限、默认搜索参数和网络参数覆盖 | 导入时自动复制内置默认配置 |

只有 DBC 也可以运行，但 CAN FD 权重会受限为 `payload_bytes`，路由报文也不会自动
排除。若要在 GUI 中使用 `frame_time_us`，当前实现必须能把 DBC 网段唯一映射到一个
ARXML Controller，并解析出所需的 bitrate/BRS 参数；`project.yaml` 中的显式参数可以
补充或覆盖 ARXML 值。

导入时，GUI 会把识别到的文件复制到 `user_input/<导入时间>/` 工作区，后续解析和运行
使用该副本。

## 路由报文排除

网关在目标网段发送的 routed TX 通常由源网段报文到达触发，不能当作可自由设置
Offset 的普通本机周期 TX。导入路由 Excel 后，GUI 按目标网段和 CAN ID 与当前工程
DBC 匹配，在 GCLS 运行前排除命中的报文，并保留逐行审计结果。

当前解析器支持：

- 标准网关表中的 `直接报文路由` Sheet；
- 旧版 `Routing(FLZCU)` 表；
- 具有目标网段、CAN ID 等明确列的简化平铺表。

路由 Excel 不是必选输入。未提供时，程序不会根据报文名猜测路由关系。

## 权重

不同物理网段独立计算，不会把 Byte 和微秒混在同一个目标中。

### Classic CAN

Classic CAN 当前固定使用 `payload_bytes`。该值表示每个时隙内的 Payload 字节数之和，
只是 Offset 均衡使用的相对权重，不是物理帧占用时间，也不能解释为真实总线利用率。

### CAN FD

CAN FD 支持两种权重：

- `frame_time_us`：optimizer 权重。根据 nominal bitrate、data bitrate、BRS、帧格式和
  Payload Length 计算 CAN FD 帧时间估计，单位为微秒；它会进入 GCLS 目标，且不是逐帧
  bitstream 或运行时重传仿真。
- `payload_bytes`：optimizer 权重。按 Payload Length 计权，单位为 Byte；忽略协议开销和
  实际 bitrate。

这两个权重都不同于结果页的 `conservative_bus_service_time_us`。后者采用独立的
nominal-only 协议模型，只用于优化后的结果诊断，不会进入 GCLS。

当工程存在唯一可用的 ARXML Controller 映射时，GUI 会提供 `frame_time_us`；
否则只提供 `payload_bytes`。Classic CAN 始终固定为 `payload_bytes`。

## 优化模式

所有模式都先按约束违规数和违规超量排序，再按各自目标比较：

| 模式 | 当前含义 |
| --- | --- |
| Peak | 优先降低稳态峰值，再比较稳态负载平方和及启动窗口指标 |
| Balanced | 先取得严格 Peak 参考解，在容差给出的峰值预算内优先降低稳态负载平方和 |
| Variance | 优先降低稳态负载平方和，再比较稳态峰值；GUI 当前标记为实验模式 |

GUI 的 Balanced tolerance 是相对容差。它只在 Balanced 模式下生效。

## 算法概览

当前核心算法为 GCLS，主要步骤包括：

1. Greedy Construction 生成初始分配；
2. 1-opt 逐条尝试移动报文；
3. conflict-directed Pair Search 针对热点时隙搜索成对移动；
4. restart 使用确定性首轮和后续随机顺序重复搜索。

Balanced 模式还可以从多个 Peak 候选继续搜索。GUI 的高级设置提供 Candidate Pool 和
冲突导向 3-opt；3-opt 会同时调整三个报文，可能明显增加运行时间。

## 安装与启动

要求 Python 3.11 或更高版本。

### 源码运行

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[gui]"
python -m canfd_offset_optimizer.gui
```

安装后也可以使用脚本入口：

```powershell
canfd-offset-gui
```

Windows 下已安装 GUI 依赖时，还可以双击：

```text
scripts\start_gui.cmd
```

### Windows 免安装包

发布包面向 Windows 10/11 x64。完整解压后运行
`CANFDOffsetOptimizer.exe`，不需要单独安装 Python。程序目录必须可写，因为
`user_input` 和 `user_output` 位于 EXE 同级目录。

开发者可以使用：

```text
scripts\build_gui_exe.cmd
```

生成免安装目录、ZIP 和 SHA256 文件。

## GUI 使用流程

1. 导入包含 DBC、可选 ARXML、路由 Excel 和 `project.yaml` 的文件或目录；
2. 为每个 DBC 选择本机发送节点，或明确标记该 DBC 不参与本次优化；
3. 检查发现的网段、资格筛选、路由排除和输入错误；
4. 设置 Offset 最小值、最大值、步长、目标模式和 CAN FD 权重；
5. 按需展开高级搜索设置，调整 Balanced tolerance、Restart、Candidate Pool 或 3-opt；
6. 点击“开始全部网段优化”；
7. 从结果概览选择网段，检查 Offset、曲线、热力图和日志；
8. 检查 `user_output` 中的 DBC 副本和审计文件。

窗口默认最大化。批量运行按网段隔离结果：单个网段失败不会清除已成功网段的结果。

## GUI 结果页

- **快速开始**：输入、参数、结果和输出位置说明；
- **结果概览**：各网段状态、权重和主要指标；
- **Offset 修改**：原始 Offset 与优化后 Offset；
- **可优化报文负载曲线**：原始与优化后负载；稳态窗口可重复展示 1、2、4 或 10 个
  超周期，启动窗口只显示核心返回的真实范围；
- **可优化报文负载热力图**：原始/优化后两行，每个时隙依次显示帧数、当前权重负载和
  协议级保守占用时间，长窗口使用水平滚动；
- **拥挤时隙明细**：列出时隙中的报文、CAN ID、Payload 长度、周期、Offset 和每帧保守
  占用时间；
- **运行日志与详情**：输入、资格、路由排除、运行参数、警告和失败原因。

曲线的稳态重复只作用于显示和 PNG 导出，不会复制或修改核心结果。热力图显示一个核心
稳态或启动窗口，不做多周期重复。

## 保守占用时间估算

### 作用与优化边界

Offset 优化改变周期报文的释放时刻。只看某个时隙同时释放多少帧，无法体现 8 Byte
Classic CAN 与 64 Byte CAN FD 在协议服务时间上的差异。因此结果层额外计算每条报文的：

```text
conservative_bus_service_time_us
```

该值表示：在一次正常成功发送、无错误、无重发、无仲裁等待的前提下，根据帧格式、
Payload Length 和网段 Nominal Bitrate，对协议允许的动态位填充采用 worst-case 上界后得到的
总线服务时间估计。它显示在单条报文明细、原始热力图和优化后热力图中。

这是只读结果诊断，不是 optimizer 权重。它不写入 `CanMessage.frame_time_us`，不改变
`weight_mode`，也不参与 GCLS、Peak/Balanced/Variance、目标函数、Offset assignment 或
assignment hash。即使 optimizer 的 `frame_time_us` 和第三行保守时间都使用 `μs`，两者也不是
同一个指标。

### DBC 提供什么，程序自己知道什么

| 信息 | 实际来源 |
|---|---|
| Classic CAN / CAN FD | DBC 帧属性，由 `dbc_parser.py` 规范化为 `FrameProtocol` |
| Standard / Extended | DBC/cantools 帧元数据，规范化为 `is_extended` |
| CAN ID | DBC `BO_`，用于报文身份和 Standard/Extended 合法性检查 |
| Payload Length | DBC Message Length，单位 Byte；不是 raw DLC code |
| Nominal Bitrate | DBC 显式全局 `BA_ "Baudrate" <bit/s>;`，否则由 GUI 用户按网段确认 |
| CAN/CAN FD 字段结构 | `timing/conservative_service.py` 中的协议模型 |
| CRC17 / CRC21 选择 | 程序内协议模型按 Payload Length 选择 |
| Dynamic bit stuffing 上界 | 程序内 `worst_case_dynamic_stuff_bits()` |
| CAN FD CRC fixed stuff | 程序内 CRC 字段模型 |
| CRC delimiter、ACK、EOF、Intermission | 程序内固定字段模型 |

DBC 不会直接给出“本次发送产生多少 stuff bit”“ACK 占多少 bit”或“EOF 占多少 bit”。
这些是协议规则。Estimator 使用 DBC 给出的报文元数据和程序内协议结构推导 bit 上界；不会从
Signal Init Value、signal range 或 signal 总长度反推 Payload。

### 总计算流程

```text
DBC Message
    ├─ protocol：Classic CAN / CAN FD
    ├─ frame format：Standard / Extended
    └─ Payload Length(Byte)
            +
NetworkTimingConfig.nominal_bitrate_bps
            ↓
protocol frame model
    ├─ dynamic region base bits
    ├─ worst-case dynamic stuffing
    ├─ CAN FD CRC/SBC/parity/fixed stuff
    ├─ CRC delimiter + ACK + EOF
    └─ normal 3-bit Intermission
            ↓
conservative total bit upper bound
            ↓
time_us = ceil(total_bits_upper_bound × 1,000,000 / nominal_bitrate_bps)
```

整数微秒使用向上取整，避免显示值低于当前模型的理论结果。Dynamic stuffing 区域为 `N` bit
时，当前实现使用：

```text
worst_case_stuff_bits(N) = floor((N - 1) / 4)
```

这是协议级最坏上界，不是平均 stuffing，也不是实际 Payload bitstream 仿真。

### Classic CAN

`D` 表示 DBC Payload Length(Byte)，合法范围为 0～8 Byte。SOF 到 15-bit CRC sequence
参与 dynamic stuffing；CRC delimiter、ACK 和 EOF 不参与该动态填充。

Standard Classic CAN：

```text
dynamic_bits = 34 + 8D
             = SOF 1 + arbitration 12 + control 6 + data 8D + CRC sequence 15
stuff_bits   = floor((dynamic_bits - 1) / 4)
total_bits   = dynamic_bits + stuff_bits + 13
```

Extended Classic CAN：

```text
dynamic_bits = 54 + 8D
             = SOF 1 + arbitration 32 + control 6 + data 8D + CRC sequence 15
stuff_bits   = floor((dynamic_bits - 1) / 4)
total_bits   = dynamic_bits + stuff_bits + 13
```

这里的 `+13` 不是经验常数：

```text
CRC delimiter 1
+ ACK slot 1
+ ACK delimiter 1
+ EOF 7
+ normal Intermission 3
= 13 bit
```

Standard Classic CAN、8 Byte、500 kbit/s 的完整示例：

```text
dynamic_bits = 34 + 8 × 8 = 98
stuff_bits   = floor((98 - 1) / 4) = 24
total_bits   = 98 + 24 + 13 = 135 bit
time         = ceil(135 × 1,000,000 / 500,000) = 270 μs
```

因此，同样是 Standard Classic CAN、8 Byte、500 kbit/s 时，不同 CAN ID 数值、报文名称、
周期和 Offset 不会改变该保守时间。CAN ID 是否为 Extended 会改变帧结构，具体 ID bit pattern
不会用于本模型的实际 stuffing 推测。

### CAN FD

CAN FD 合法 Payload Length 为 `0～8、12、16、20、24、32、48、64 Byte`。SOF 到数据字段
按 dynamic stuffing 上界处理。Standard 和 Extended 的 dynamic region 分别为：

```text
Standard dynamic_bits = 22 + 8D
Extended dynamic_bits = 41 + 8D
stuff_bits             = floor((dynamic_bits - 1) / 4)
```

Standard 的 22 bit 由 SOF、11-bit identifier、RRS、IDE、FDF、res、BRS、ESI 和 DLC 组成；
Extended 的 41 bit 还包含 SRR、IDE 和 18-bit identifier extension。

CRC 长度按当前实现选择：

```text
Payload Length <= 16 Byte → CRC17
Payload Length >  16 Byte → CRC21
```

CRC 字段还包含 3-bit Stuff Bit Count、1-bit parity，以及 CAN FD fixed stuff bits。实现把
`4 + CRC length` 作为 protected bits，并计算：

```text
crc_field_bits = protected_bits + 1 + floor(protected_bits / 4)
```

因此：

```text
CRC17 + SBC/parity/fixed stuff region = 27 bit
CRC21 + SBC/parity/fixed stuff region = 32 bit
```

CRC 字段之后同样加入 13 bit：CRC delimiter 1、ACK slot 1、ACK delimiter 1、EOF 7 和正常
Intermission 3。最终：

```text
total_bits = dynamic_bits + stuff_bits + crc_field_bits + 13
```

Standard CAN FD、8 Byte、500 kbit/s：

```text
dynamic_bits = 22 + 8 × 8 = 86
stuff_bits   = floor((86 - 1) / 4) = 21
CRC17/SBC/parity/fixed stuff = 27
total_bits   = 86 + 21 + 27 + 13 = 147 bit
time         = ceil(147 × 1,000,000 / 500,000) = 294 μs
```

Standard CAN FD、64 Byte、500 kbit/s：

```text
dynamic_bits = 22 + 8 × 64 = 534
stuff_bits   = floor((534 - 1) / 4) = 133
CRC21/SBC/parity/fixed stuff = 32
total_bits   = 534 + 133 + 32 + 13 = 712 bit
time         = ceil(712 × 1,000,000 / 500,000) = 1424 μs
```

这说明 CAN FD 报文不会因为属于同一网段而具有相同时间；协议、Standard/Extended、Payload
Length 和 Nominal Bitrate 相同的报文才会得到相同结果。

### 500 kbit/s 参考结果

以下结果由当前 `estimate_conservative_bus_service_time()` 重新计算，均为 Standard Frame：

| Protocol | Payload | Conservative bits | Conservative time |
|---|---:|---:|---:|
| Classic CAN | 4 B | 95 bit | 190 μs |
| Classic CAN | 8 B | 135 bit | 270 μs |
| CAN FD | 8 B | 147 bit | 294 μs |
| CAN FD | 16 B | 227 bit | 454 μs |
| CAN FD | 24 B | 312 bit | 624 μs |
| CAN FD | 32 B | 392 bit | 784 μs |
| CAN FD | 48 B | 552 bit | 1104 μs |
| CAN FD | 64 B | 712 bit | 1424 μs |

Extended Frame 使用更长的 dynamic region，结果不会小于相同 Payload 和 bitrate 的 Standard
Frame。例如 Extended Classic CAN 8 Byte 为 160 bit/320 μs；Extended CAN FD 64 Byte 为
736 bit/1472 μs。

### 为什么只要求 Nominal Bitrate

Classic CAN 整帧按 Nominal Bitrate 计时。对于 CAN FD，当前工具采用的是
**conservative calculation policy**，不是“CAN FD 实际整帧只使用 Nominal Bitrate”：

```text
CAN FD 整帧所有 bit 均按 Nominal Bitrate 计时
```

因此本指标不要求 Data Bitrate、BRS 或 ARXML。该策略假设：

```text
Data Phase Bitrate >= Nominal Bitrate
```

在该假设成立时，不计 data-phase speed-up、把整帧都按较慢的 Nominal Bitrate 计时，会比正常
高速 data phase 更保守。若要估算某一真实 BRS 帧的实际 airtime，则必须使用 Data Bitrate、BRS
和更精确的 phase/bitstream 信息；那不是本指标的语义。

一旦 DBC 已提供协议、Standard/Extended 和 Payload Length，协议固定字段、CRC 规则和 stuffing
上界都由 timing 模块确定，所以唯一仍用于把 bit 数换算成时间的网段级参数就是 Nominal Bitrate。
Sample point、SJW、TSEG 和 prescaler 在 bitrate 已确定后不改变本模型中的单 bit 时长。

### Nominal Bitrate 来源与缺失行为

只有 DBC 中唯一、明确、正数的全局属性才会被自动接受：

```dbc
BA_ "Baudrate" 500000;
```

单位为 bit/s。空白 `BS_:`、`BA_DEF_DEF_ "Baudrate"` 默认值、文件名、其他网段和项目经验都不会
被当作已确认速率。无法可靠读取时，GUI 的“网段速率参数”窗口保持为空，由用户按 kbit/s 确认；
程序不会静默假设 500 kbit/s。批量填充只作用于尚未配置的 CAN FD 网段，不覆盖已有值。

Nominal Bitrate 缺失不会阻止 Offset 优化，因为该指标不属于优化资格条件。优化结果、assignment
和现有负载仍然有效，但每帧保守时间不可计算，非空热力格显示 `保守 —`。若一个时隙只有部分
成员可计算，则显示已知下界 `保守 ≥xxx μs*`，并在 Tooltip 中说明缺失原因。优化完成后修改
bitrate 只刷新结果 presentation，不重新运行 GCLS。

### 时隙汇总、热力图和报文明细

对原始和优化后状态分别使用当前正式 heatmap members：

```text
slot conservative time
    = sum(当前 slot 中每条 member 的 conservative_bus_service_time_us)
```

未选择 sender、`routing_excluded`、非周期或其他资格已排除报文不会重新加入。空时隙的总量是
0；全部成员不可计算时显示 `—`。这个和不是实测总线占用、仲裁仿真、队列完成时间或 Worst-Case
Response Time，只是同一时隙内释放的可优化周期报文之单帧保守服务时间总和。

热力格三行含义：

```text
3 帧          ← 当前 slot 的正式报文数量
72 B          ← 当前 optimizer weight_mode 的 slot load
保守 812 μs   ← 独立的 protocol-level conservative service time total
```

若 optimizer 使用 `frame_time_us`，第二行也可能是 `μs`，但仍来自 optimizer 权重模型；第三行始终
来自 nominal-only conservative estimator，不能混用。当前功能只显示绝对微秒值，不计算
`conservative_time / slot_width`，也不提供 occupancy/utilization/load-rate 百分比。

热力图下方明细包含 Message Name、CAN ID、`长度(Byte)`、Cycle、Offset 和
`保守占用时间(μs)`。`长度(Byte)` 是 DBC Message Payload Length，不是 raw DLC code、整个 CAN
frame 长度或 signal bit 长度总和。例如 CAN FD raw DLC code 15 对应 64 Byte，GUI 显示 `64`。

### 模型边界与代码位置

当前模型包含协议固定字段、Payload、worst-case dynamic stuffing、CAN FD CRC fixed stuff、ACK、
EOF 和正常 3-bit Intermission；不考虑仲裁失败等待、Error Frame、Retransmission、ACK failure、
排队、ECU 软件调度、实际 Payload、实际运行时 bitstream 或 CAN FD data-phase speed-up。它应称为
“保守占用时间”或 “Conservative Bus Service Time”，不能解释为精确 airtime、实际发送时间或
Worst-Case Response Time。

关键实现入口：

- `src/canfd_offset_optimizer/timing/conservative_service.py`
  - `estimate_conservative_bus_service_time()`
  - `worst_case_dynamic_stuff_bits()`
- `src/canfd_offset_optimizer/parsers/dbc_parser.py`
  - `read_dbc_nominal_bitrate()`
- `src/canfd_offset_optimizer/gui/heatmap_details.py`：把正式 slot members 转成报文级和时隙级结果；
- `src/canfd_offset_optimizer/gui/heatmap_view_model.py`：缓存报文估算并构造三行展示。

## DBC 回写

优化结果写入输出 DBC 副本中的：

```text
GenMsgStartDelayTime
```

`GenMsgDelayTime` 是独立属性，不是当前 Offset 的读取或回写别名，Writer 不会修改它。

Writer 只替换参与优化报文的 `GenMsgStartDelayTime` 数值。报文缺少显式赋值但 DBC
存在合法的 `BA_DEF_ BO_ "GenMsgStartDelayTime"` 定义时，Writer 会补充显式赋值；
其余内容保持不变。同一报文的同值重复声明会同步更新，冲突值不会自动覆盖。

如果 DBC 缺少合法属性定义、存在冲突声明、输出路径不安全或写后验证失败，DBC 输出会
fail-closed。核心优化结果仍记为成功，Offset CSV、图表、热力图和日志继续保留，GUI
显示“成功（DBC写回失败）”及具体原因。

## 输出

每次批量运行在 `user_output` 下创建纯时间戳目录：

```text
user_output/<YYYYMMDD_HHMMSS_ffffff>/
├─ logs/
│  ├─ batch.log
│  └─ <network>.log
├─ plots/
│  ├─ <network>_load_curve.png
│  └─ <network>_heatmap.png
├─ results/
│  ├─ networks_summary.csv
│  ├─ run_config.json
│  ├─ message_eligibility.csv
│  ├─ routing_exclusion_summary.csv
│  └─ <network>/offsets.csv
└─ dbc/
   └─ <原始 DBC 文件名>
```

`message_eligibility.csv` 记录每条报文进入或未进入优化的原因；
`routing_exclusion_summary.csv` 保留路由表逐行匹配结果；`run_config.json` 记录本次
Offset 搜索参数和各 DBC 的发送节点选择。DBC 输出保持原始文件名，原始用户 DBC 不会
被修改。

## CLI

GUI 是当前日常入口。CLI 保留了单网段优化、阶段比较、权重比较、Restart 分析、
Balanced tolerance 扫描、Candidate Pool 分析、3-opt 消融和可选 CP-SAT 验证：

```powershell
canfd-offset --help
canfd-offset optimize --help
```

CLI 当前要求显式提供 DBC、ARXML 目录、配置和输出路径。CP-SAT 验证需要额外安装
OR-Tools：

```powershell
python -m pip install -e ".[solver]"
```

## 当前边界

- 只调整合资格周期 TX 报文的首次发送 Offset，不降低平均负载；
- GUI 图表统计的是本次纳入 GCLS 的可优化报文，不是整条物理总线的全部流量；
- routed TX 只有在提供并成功匹配路由 Excel 时才会自动排除；
- Classic CAN 的 `payload_bytes` 是工程近似；
- CAN FD optimizer 的 `frame_time_us` 是基于 nominal/data bitrate 和 BRS 的权重估计；它不同于结果页 nominal-only 的保守占用时间；
- 默认自动超周期受 5000 ms 上限约束，周期最小公倍数超过上限的网段不能直接运行；
- 不模拟完整 CAN 仲裁、事件触发、错误帧、重传、网关运行时延迟或 ECU 调度抖动。

当前优化结果仅反映本次纳入优化集合的周期发送报文，在指定时隙宽度、权重模型和排除
规则下，调整 Offset 后的相对负载时序分布及峰值变化。由于结果未覆盖未选中节点、
路由排除报文、非周期报文、诊断/NM 报文及其他未进入优化集合的总线流量，因此它不
等同于真实物理总线的完整负载、实际总线利用率或最终实车时序结果。

## 开发与检查

安装开发依赖：

```powershell
python -m pip install -e ".[gui,dev]"
```

仓库质量门禁：

```powershell
python -m pytest -q
python -m ruff check src tests
python -m mypy src
```

GUI 使用说明见 [`docs/gui_user_guide.md`](docs/gui_user_guide.md)，Backend 调用边界见
[`docs/gui_backend_contract.md`](docs/gui_backend_contract.md)。

## 问题与需求

发现 bug 或有新的使用需求时，请提交 GitHub Issue，并附上复现步骤、输入条件、日志或
截图。不要在 Issue 中上传公司内部 DBC、ARXML、路由表或其他敏感工程数据；需要说明
输入时请使用脱敏后的最小样例。

## 许可证

本项目采用 [GNU Affero General Public License v3.0 only](LICENSE)，SPDX 标识为
`AGPL-3.0-only`。

作者：篠見由紀。
