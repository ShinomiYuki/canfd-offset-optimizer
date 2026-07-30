# CAN FD Offset Optimizer v1.0 发布说明

发布日期：2026-07-29

## 正式能力

- 面向周期 CAN / CAN FD 报文的 Offset 均衡优化，支持 `Peak`、`Balanced` 和
  `Variance` 三种目标模式。
- 使用 GCLS（Greedy Construction + Local Search）完成 Offset 启发式搜索。
- 提供 MainFunction fixed-Offset exact solver：在 Offset assignment 固定时，精确求解
  MainFunction partition。
- 提供 CAN–CPU Joint optimization，在 CAN 负载质量与 CPU Cost Proxy 之间进行联合搜索，
  输出当前搜索得到的 observed Pareto front，并生成 automatic recommendation。
- GUI 已接入完整 Joint workflow，可展示自动推荐诊断以及 MainFunctionTx / TimeBase
  recommendation。
- 支持将正式推荐 assignment 的 Offset 导出到 DBC 副本中的
  `GenMsgStartDelayTime`。
- Joint workflow 输出 `joint_summary.json`、`joint_pareto.csv` 和
  `main_function_recommendation.csv`，分别记录 Joint summary、observed Pareto 候选解和
  MainFunction recommendation。

## 边界与解释

- 当前 Joint outer Offset search 是 heuristic；observed Pareto front 只表示本次搜索实际
  观察到的非支配候选解，不代表已求得全局 Pareto front。
- 在 fixed assignment 下，MainFunction partition 为 exact。
- `CPU Cost Proxy` 是 COM-Tx 调度成本代理，不是实际 CPU utilization。
- DBC 导出仅回写 Offset；MainFunctionTx / TimeBase 以建议和报告形式输出，不表示软件会自动生成完整 AUTOSAR 配置。
