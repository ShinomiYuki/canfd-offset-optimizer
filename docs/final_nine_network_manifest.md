# 最终九网段实验 Manifest

该文件是 CAN-only 与 CAN/CPU joint 共用的最终输入锁。预检状态：**全部通过**。

| network | sender | protocol | total | periodic TX | routing excluded | eligible | joint decision | joint fixed | StartDelay explicit/default/unknown | timing |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| CH | FLZCU | CAN_FD | 68 | 9 | 0 | 9 | 8 | 1 | 9/0/0 | complete |
| DA | FLZCU | CAN_FD | 50 | 17 | 0 | 17 | 17 | 0 | 17/0/0 | complete |
| DK | FLZCU | CAN_FD | 71 | 25 | 0 | 25 | 16 | 9 | 25/0/0 | complete |
| EP | FLZCU | CAN_FD | 89 | 6 | 0 | 6 | 6 | 0 | 6/0/0 | complete |
| GL | FLZCU | CAN_FD | 90 | 25 | 0 | 25 | 23 | 2 | 25/0/0 | complete |
| IC | FLZCU | CAN_FD | 85 | 24 | 0 | 24 | 20 | 4 | 24/0/0 | complete |
| LC | FLZCU | CAN_FD | 21 | 8 | 0 | 8 | 8 | 0 | 8/0/0 | complete |
| PT | FLZCU | CAN_FD | 43 | 11 | 0 | 11 | 11 | 0 | 11/0/0 | complete |
| SU | FLZCU | CAN_FD | 19 | 7 | 0 | 7 | 7 | 0 | 7/0/0 | complete |

- Source HEAD: `80b9ae3ec18d4c7f6ebce2eca02a6fb7b4f6922a`
- Routing Excel SHA-256: `d4eabfd6725ff7f2d0db8d3c6c49a75be7ae898c651bee22846761cbc0ee84fc`
- Original baseline：只读取 `GenMsgStartDelayTime`。
- 候选点：`min + k·step ≤ max`，不强行补入 max。
- Joint：`rho=1`（未标定默认场景），`attempts=3`，`K=41`，最多 3 次 refinement。
