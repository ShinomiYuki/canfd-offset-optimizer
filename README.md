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

这两个权重都不同于结果页的 `conservative_bus_service_time_us`。后者采用独立的协议级
保守时序模型，只用于优化后的结果诊断，不会进入 GCLS。CAN FD BRS 开启时按 Nominal/Data
phase 分段计算；BRS 关闭时整帧按 Nominal 计算。

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

### 定义与优化边界

结果层为每条正式参与优化的周期报文计算 `conservative_bus_service_time_us`。它表示：在**当前已确认的真实网段时序配置**下，对一次无错误、无重发、正常成功发送，按协议允许的 worst-case dynamic stuffing、CAN FD CRC fixed stuff、固定字段和正常 3-bit Intermission 得到的总线服务时间保守上界。

保守性来自未知运行时 bit pattern 的 stuffing 上界，不再来自故意取消 CAN FD Data Phase 加速。它只属于优化后的结果诊断，不写入 `CanMessage.frame_time_us`，不参与 GCLS、Peak、Balanced、Variance、restart、assignment、Offset 或 objective。修改网段时序参数只刷新报文时间、时隙求和、热力图和明细，不重新运行优化器。

本模型不包含仲裁失败等待、Error Frame、Retransmission、ACK failure、Bus-Off、排队、ECU 软件调度或实际 Payload bit pattern，也不是精确 airtime、实测总线利用率或 Worst-Case Response Time。

### 数据来源与纯 DBC 工作流

| 信息 | 来源 |
|---|---|
| 协议、Standard/Extended、Payload Length | DBC Message 元数据 |
| Nominal Bitrate | DBC 显式全局 `BA_ "Baudrate"`，否则 GUI 按网段确认 |
| CAN FD Data Bitrate | DBC 中唯一、明确的受支持全局属性，否则 GUI 按网段确认 |
| CAN FD BRS | DBC `CANFD_BRS` 的 per-message 显式值或有效 `BA_DEF_DEF_`；缺失时使用 GUI 网段默认 |
| 协议字段、CRC17/CRC21、stuffing 与 Intermission | `timing/conservative_service.py` |

BRS 的有效值优先级固定为：

```text
DBC per-message BRS > user network default BRS > unavailable
```

不会根据 Payload、Data Bitrate 是否存在或经验值猜测 BRS。纯 DBC 工作流表示不强制用户导出 ARXML；它不表示 CAN FD 的 Data Bitrate/BRS 可以省略。缺少的 network-level timing metadata 在 GUI 中每个网段确认一次，不需要逐条报文填写。

当前实际 GL/IC/DK DBC 含可靠 `CANFD_BRS` 默认值，但没有 Nominal/Data Bitrate，因此 BRS 可由 DBC 自动使用，两个 bitrate 仍需人工确认。空白 `BS_:`、文件名、其他网段和项目经验不会被当作 500 kbit/s 或 2 Mbit/s。

### Classic CAN（保持原模型）

Classic CAN 只需要 Nominal Bitrate。`D` 为 Payload Length(Byte)，范围 0～8：

```text
S(N) = floor((N - 1) / 4)
Standard dynamic_bits = 34 + 8D
Extended dynamic_bits = 54 + 8D
total_bits = dynamic_bits + S(dynamic_bits) + 13
service_time_us = ceil(total_bits × 1,000,000 / nominal_bitrate)
```

`+13` 为 CRC delimiter 1、ACK slot 1、ACK delimiter 1、EOF 7 和正常 Intermission 3。Standard Classic CAN、8 Byte、500 kbit/s 仍为 `135 bit / 270 μs`。

### CAN FD BRS 关闭

CAN FD 合法 Payload Length 为 `0～8、12、16、20、24、32、48、64 Byte`。BRS 明确关闭时整帧确实使用 Nominal Bitrate，原来的单速率公式仍合法：

```text
Standard dynamic_bits = 22 + 8D
Extended dynamic_bits = 41 + 8D
crc_field_bits = 27 (D <= 16) or 32 (D > 16)
total_bits = dynamic_bits + S(dynamic_bits) + crc_field_bits + 13
service_time_us = ceil(total_bits × 1,000,000 / nominal_bitrate)
```

因此 Standard CAN FD 48 Byte、500 kbit/s、BRS OFF 的 `1104 μs` 是合理结果；它不能再作为 BRS ON 的默认示例。

### CAN FD BRS 开启：Nominal/Data phase 分段模型

CAN FD BRS 开启时必须同时提供 Nominal Bitrate 和 Data Bitrate。协议在 BRS bit 的 sample point 切换到 data timing，并在 CRC delimiter 的 sample point 切回 nominal timing。Estimator 不把 Control/Data/CRC 粗暴整体切为 Data Phase，而是按字段边界分解：

```text
P = 17 (Standard) or 36 (Extended)  # SOF through BRS
Q = 5 + 8D                          # ESI + DLC + Payload
S_prefix = floor((P - 1) / 4)
S_data_with_carry = ceil(Q / 4)
CRC_field = 27 (CRC17) or 32 (CRC21), including fixed stuff

nominal_full_bits = (P - 1) + S_prefix + 12
data_full_bits    = Q + S_data_with_carry + CRC_field
transition_guard = 2 × (1/Nominal + 1/Data)

service_time_us = ceil(
    nominal_full_bits × 1,000,000 / nominal_bitrate
  + data_full_bits    × 1,000,000 / data_bitrate
  + transition_guard × 1,000,000
)
```

Dynamic stuffing 从 SOF 连续到 Data Field。前缀从空 stuffing history 开始；Data suffix 可能继承前缀的连续位状态，因此使用 `ceil(Q/4)` 的 phase-safe 上界。CRC 字段计入 Stuff Bit Count、parity 和 fixed stuff，ACK、EOF 与 Intermission 属于 nominal 尾段。

BRS 和 CRC delimiter 都在各自 bit 的 sample point 内切速。当前网段 DTO 只保存 bitrate，不保存 sample-point segment 长度；为避免凭空制造比例，两个 transition bit 不强行归入整数 phase bit，而是单独保存精确的 `Fraction` duration guard：每个边界在相邻速率各取一次完整 bit-time 上界。`total_bits_upper_bound` 仅保留为兼容性的计时核算上界，不是一条具体物理 bitstream 的去重 wire-bit 数。该处理对任意正 bitrate（包括少见的 Data < Nominal）仍安全；Data < Nominal 会提示异常配置但不会静默改值。

### 当前估算器参考值

以下数值由当前 estimator 实际计算，均为 Standard Frame：

| Protocol / timing | Payload | Nominal | Data | Conservative time |
|---|---:|---:|---:|---:|
| Classic CAN | 8 B | 500 kbit/s | — | 270 μs |
| CAN FD, BRS ON | 8 B | 500 kbit/s | 2000 kbit/s | 126 μs |
| CAN FD, BRS ON | 16 B | 500 kbit/s | 2000 kbit/s | 166 μs |
| CAN FD, BRS ON | 32 B | 500 kbit/s | 2000 kbit/s | 249 μs |
| CAN FD, BRS ON | 48 B | 500 kbit/s | 2000 kbit/s | 329 μs |
| CAN FD, BRS ON | 64 B | 500 kbit/s | 2000 kbit/s | 409 μs |
| CAN FD, BRS OFF | 48 B | 500 kbit/s | — | 1104 μs |
| CAN FD, BRS OFF | 64 B | 500 kbit/s | — | 1424 μs |

相同 CAN FD 报文在 `500k/2M, BRS ON` 下必须明显快于 `500k, BRS OFF`，但长 Payload 仍比短 Payload 占用更长。Extended 64 Byte、500k/2M、BRS ON 为 `455 μs`。

### 缺失参数与 partial 语义

- 缺 Nominal：Classic CAN 与 CAN FD 均不可计算；
- CAN FD BRS unknown：不可计算，不按 ON、OFF 或两者较大值猜测；
- CAN FD BRS ON 且缺 Data Bitrate：不可计算，不回退为 `Data = Nominal`；
- CAN FD BRS OFF：不需要 Data Bitrate；
- ARXML：不是本诊断的必需输入。

这些情况不阻止 Offset 优化。热力格全部成员不可计算时显示 `保守 —`；部分成员可计算时显示 `保守 ≥xxx μs*`，Tooltip 给出已计算数和缺失原因。时隙值始终为当前正式 members 的逐帧保守时间之和，不重做仲裁、queue 或 stuffing 联合仿真：

```text
slot conservative time = sum(member.conservative_bus_service_time_us)
```

### GUI 单位与代码位置

热力图第二行严格跟随 optimizer `weight_mode`：`payload_bytes → B/slot`，`frame_time_us → μs/slot`；第三行始终是独立的 `保守 xxx μs`。当前功能不计算 `conservative_time / slot_width` 或 utilization 百分比。

关键实现：

- `timing/conservative_service.py`：Classic、BRS ON/OFF 和 phase bounds；
- `parsers/dbc_parser.py`：Nominal/Data 与 per-message `CANFD_BRS`；
- `gui/timing_resolution.py`：effective BRS 优先级；
- `gui/heatmap_details.py` / `gui/heatmap_view_model.py`：members 求和、缓存和 presentation；
- `gui/widgets/network_timing_dialog.py`：Nominal、Data、BRS 的网段级确认。
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
- CAN FD optimizer 的 `frame_time_us` 是优化权重；它与结果页独立的 phase-aware 保守占用时间不是同一字段；
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
