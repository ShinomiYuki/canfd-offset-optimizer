# CAN FD Offset Optimizer v1.1 发布说明

## 混合协议网段

- 同一物理网段可同时包含 Classic CAN 与 CAN FD 周期 TX 报文，网段级协议显示为 `Mixed`。
- 每条报文继续保留真实协议；Sender Selection、路由排除、GCLS、热力图和 Offset 回写不拆分网段。
- Mixed 固定使用 `payload_bytes`；`frame_time_us` 请求会确定性降级并记录 warning。
- 纯 Classic CAN 与纯 CAN FD 的既有权重行为保持不变。

## 超周期资源保护

- 删除固定 5000 ms 执行上限；`hyperperiod_ms` 仍支持 `auto` 或显式 LCM 倍数。
- 新增 `max_slot_count: 20000` 与 `max_precomputed_hits: 2000000`。
- 在分配命中 tuple 和时隙负载数组前精确预估规模，超限时报告实际值、上限、超周期和时隙宽度。
- 旧 `hyperperiod_cap_ms` 仍可解析，但已 deprecated 且忽略。

## 已知边界

- 不修改 DBC Writer 语义。
- 不自动推导时隙宽度；含 2 ms 周期的 PTBUS2 仍需配置 `slot_ms: 1`。
