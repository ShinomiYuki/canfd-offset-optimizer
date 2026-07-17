# GUI 数据真实性根因与修复报告

1. **BD/DM/DG 曾错误进入优化**：旧 `MockBackend._networks_from_dbc` 将每个 DBC 无条件标记为可优化，并伪造报文数。现由核心 `parse_dbc` 判定；经典 CAN 与无周期 CAN FD TX 明确跳过。
2. **出现 17、23、42 ms 等非法 Offset**：旧 Mock 按 hash/index 生成任意毫秒数，未使用核心候选域。现真实适配器只接受核心 `{15,20,...,100} ms`，异常失败关闭。
3. **原始 Offset 与 DBC 不一致**：旧 Mock 从 seed 计算“原始值”，从未解析 DBC。现直接映射核心 `CanMessage.original_offset_us`；缺失或不属于 `{15,20,...,100} ms` 时显式报告 message/value/source 并使该网段失败，不取整、不截断、不回退。
4. **不同网段曲线可能相同或残留**：旧数据是模拟数组，且切换成功结果时没有先清空画布。现四组数组逐结果直接复制自核心；选择切换先清空再重绘，失败/跳过/无选择显式清空。
5. **结果关联风险**：历史实现可能依赖显示名或最近一次结果。现汇总、Offset、曲线和日志统一通过稳定 `network_id -> NetworkBatchResult -> GuiOptimizationResult` 查询。
6. **生产仍使用 Mock**：旧 `app.py` 直接构造 `MockBackend`。现只构造 `RealBackend`；初始化失败使用不可用门禁，绝不静默回退或制造成功输出。
7. **测试把模拟行为当业务正确性**：旧测试直接依赖 Mock 公式。现界面流程测试显式使用 `FixtureBackend`；新增真实适配器、CSV 回归、失败关闭、资格与 DTO/曲线独立性测试。

回归 CSV `tests/fixtures/ALL_offsets_weight_mode_comparison.csv` 只作为只读测试证据，生产代码不读取、不推断网段名单，也不把 CSV 当优化输入。

## 当前工程资格验收

使用当前导入工作区的 12 个 DBC 调用 `RealBackend.inspect_workspace`（未运行长时间优化）得到：

- 发现 12；可优化 9；跳过 3；
- CH 9、DA 17、DK 25、EP 6、GL 25、IC 24、LC 8、PT 11、SU 7；
- BD、DM：核心 parser 报告经典 CAN；
- DG：核心 parser 报告没有周期 CAN FD TX 报文。

生产实现没有上述九个可优化网段的名称集合；名称和计数只存在于测试回归断言与本报告中。
