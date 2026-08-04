# 九网段 D 结构诊断结果

本报告由 `analyze-d-structure` 的实际输出生成。诊断只读取锁定 manifest、生产加载链和既有联合候选归档；没有修改 Offset、GCLS、Peak 预算、Pareto 归档、推荐点、DBC、ARXML、路由表或生产配置。

## 1. 运行环境与 provenance

- 诊断实现 commit：`36a546a3be4377f3a43f792e1731dab96d6354f6`。
- Manifest：`docs/final_nine_network_manifest.yaml`，SHA-256 为 `d9ac7828da31c57a384762e3f221ca665511bfc5ef13566461a4883fc5eb3d1b`。
- 共享配置 SHA-256：`c5cfa3fbeaea6519f149e6f85672385c4fe793ced5a02b2439e570f97177f611`。
- 路由表 SHA-256：`d4eabfd6725ff7f2d0db8d3c6c49a75be7ae898c651bee22846761cbc0ee84fc`。
- ARXML `T13J_GW.arxml` SHA-256：`67152910ba5880e65504096cb6b38968f4eaf6aa7683a7952effce92d0bbe2b9`。
- Archive source commit：`80b9ae3ec18d4c7f6ebce2eca02a6fb7b4f6922a`；它与诊断 commit 不同。
- Manifest 中记录的 archive source worktree 为非干净状态；该原始字符串完整保留在每网段 `d_structure_summary.json`，未被改写为干净状态。
- 诊断运行开始时 `git status --short` 为空；诊断输出位于已忽略的 `output/diagnostics/`。
- `rho=1/1`，是未标定默认场景；所有相等、去重和 coverage 计算均使用 `Fraction`。
- 最终 caps：`max_histogram_states=1000000`、`max_exact_pstar_evaluations=1000000`、每网段 `timeout_s=600`。
- 当前环境的 editable install 仍指向相邻 `canfd-offset-optimizer-gui` 工作区，因此运行时显式把 `PYTHONPATH` 绑定到本仓库 `src`；摘要 JSON 中的 CLI 参数串不含这一 shell 环境赋值，以下才是完整实际命令。
- 最终运行命令：

```powershell
$env:PYTHONPATH='src'
python -m canfd_offset_optimizer analyze-d-structure --manifest docs/final_nine_network_manifest.yaml --rho 1 --output-root output/diagnostics --max-histogram-states 1000000 --max-exact-pstar-evaluations 1000000 --timeout-s 600
```

### 1.1 首次 capped 事实与重跑依据

首次九网段运行使用同样的两个状态 cap 和 `timeout_s=300`。其中八个网段为 `exact`，IC 在直方图枚举已经完整得到 `49,946` 个状态后，于第 `31,372` 次 P* 精确评价处触发 `timeout`：`exactness_status=capped`、`structure_classification=incomplete_due_to_cap`、coverage 为 `null`。该次配置 hash 为 `5c75bb3cdcc1f9e2ce0029846be5dd4c2d1cf8a1a42cc3bb60855a4c50cdfdf2`，原始摘要保留在忽略目录的 `output/diagnostics/IC/d_structure/attempts/capped_timeout_300s_summary.json`。

资源评估表明 IC 的直方图总数远低于一百万状态 cap，失败原因只是精确内层时间不足；因此第二次仅把每网段 timeout 提高到 600 秒，没有改变候选域、业务输入、`rho` 或两个状态 cap。IC 最终在 `357.247` 秒完成全部 `49,946` 次 P* 评价。

### 1.2 最终诊断配置 hash

| 网段 | configuration hash |
|---|---|
| CH | `fa41c9229e630ca3350061b92d07c3003c7fe8cc8ac9738707a3e27f5b7c808a` |
| DA | `d2e7732e855aaa4cfae5e0f70f49f9a05428770404125d581648bd60bec68a8d` |
| DK | `be63c06858fe7440c8a301700fab98c55ab77add6dc54f208b1c3ac69808ae18` |
| EP | `0c3a6343b14c43dfef4fe32fc33e83d82d6605aa50cf6d3cc7cb03fff8277723` |
| GL | `5d045721f93d38a04397d32c486a8e70862451fd3effbe31c139bf3de6307601` |
| IC | `13a2d24248fcadc54e96cab68467686f3fdb9c1da2d9fa57a38d765ce1100bd9` |
| LC | `753dcb1feacc8fa4f20cb5a64715bff4b161936a204eb23a5e1f08618afde94b` |
| PT | `090cfa542a98f9dc7f1b7a324a4cda050ae91b586a1a3ad5649da63f3cc7248d` |
| SU | `3857ab8bdf3c8a0ffb05e711dec59673ed1245f7048053e372e58f38a23c6ba4` |

每网段的 DBC hash、eligible-set hash、archive hash，以及共享输入 hash 均保存在对应的 `d_structure_summary.json`。运行前后对 `input/`、完整 `output/final_paper_nine_network/`、manifest 及生产 `config.py`、`gcls.py`、`joint.py`、`main_function.py` 共 51 个文件同时比较 SHA-256、mtime 和大小，结果为 `51/51` 未变化。

## 2. 九网段汇总表

`archive H/P*` 分别是归档观察到的唯一 D 直方图数和唯一 P* 水平数；`H coverage` 与 `level coverage` 均为精确分数。

| 网段 | n | decision/fixed | 可达 D 并集（us） | r | ∏｜Dsetᵢ｜ | stars-and-bars | combined upper | 可达 H | 可达 P* | archive H/P* | H coverage | level coverage | 状态 | 分类 | provenance | 秒 |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---:|
| CH | 9 | 8/1 | 5000,10000,20000,25000,50000,100000,500000 | 7 | 419904 | 5005 | 5005 | 1134 | 134 | 6/6 | 1/189 | 3/67 | exact | multiple_reachable_pstar_levels | comparable | 13.483 |
| DA | 17 | 17/0 | 5000,10000,20000,25000,50000,100000 | 6 | 940369969152 | 26334 | 26334 | 24778 | 299 | 14/14 | 7/12389 | 14/299 | exact | multiple_reachable_pstar_levels | comparable | 20.205 |
| DK | 25 | 16/9 | 5000,10000,20000,25000,50000,100000,500000,1000000 | 8 | 104485552128 | 3365856 | 3365856 | 18359 | 265 | 46/45 | 46/18359 | 9/53 | exact | multiple_reachable_pstar_levels | comparable | 50.740 |
| EP | 6 | 6/0 | 5000,10000,20000,25000,50000,100000 | 6 | 11664 | 462 | 462 | 371 | 91 | 2/2 | 2/371 | 2/91 | exact | multiple_reachable_pstar_levels | comparable | 13.081 |
| GL | 25 | 23/2 | 5000,10000,20000,25000,50000,100000,1000000 | 7 | 29249267520503808 | 736281 | 736281 | 95238 | 412 | 56/52 | 28/47619 | 13/103 | exact | multiple_reachable_pstar_levels | comparable | 104.169 |
| IC | 24 | 20/4 | 5000,10000,20000,25000,50000,100000,500000,1000000,2000000 | 9 | 203119913336832 | 10518300 | 10518300 | 49946 | 342 | 38/36 | 19/24973 | 2/19 | exact | multiple_reachable_pstar_levels | comparable | 357.247 |
| LC | 8 | 8/0 | 5000,10000,20000,25000,50000,100000 | 6 | 93312 | 1287 | 1287 | 891 | 114 | 2/2 | 2/891 | 1/57 | exact | multiple_reachable_pstar_levels | comparable | 13.033 |
| PT | 11 | 11/0 | 5000,10000,20000,25000,50000,100000 | 6 | 30233088 | 4368 | 4368 | 3744 | 186 | 5/5 | 5/3744 | 5/186 | exact | multiple_reachable_pstar_levels | comparable | 13.812 |
| SU | 7 | 7/0 | 5000,10000,20000,25000,50000,100000 | 6 | 69984 | 792 | 792 | 672 | 114 | 4/4 | 1/168 | 2/57 | exact | multiple_reachable_pstar_levels | comparable | 12.903 |

九个网段最终全部 `exact`，且全部存在多个可达 P* 水平；没有网段属于 `fixed_d_vector` 或 `proven_constant_pstar`。

## 3. EP、LC、SU 单点现象裁决

### EP

- 不是 `fixed_d_vector`，也不是 `proven_constant_pstar`。
- 全空间精确可达 `371` 个 D 直方图、`91` 个 P* 水平，明确存在多个可达 P* 水平。
- 既有 archive 观察到 `2` 个直方图和 `2` 个 P* 水平；既有 Pareto 单点不能由“软件目标在全部合法 Offset 空间内为常数”严格解释。
- 不是 `observed_single_level_only`，也不是 cap 未决；最终分类为 `multiple_reachable_pstar_levels`。

### LC

- 不是 `fixed_d_vector`，也不是 `proven_constant_pstar`。
- 全空间精确可达 `891` 个 D 直方图、`114` 个 P* 水平。
- Archive 观察到 `2` 个直方图和 `2` 个 P* 水平；既有单点现象不能归因于结构常数。
- 不是 `observed_single_level_only`，也不是 cap 未决；最终分类为 `multiple_reachable_pstar_levels`。

### SU

- 不是 `fixed_d_vector`，也不是 `proven_constant_pstar`。
- 全空间精确可达 `672` 个 D 直方图、`114` 个 P* 水平。
- Archive 观察到 `4` 个直方图和 `4` 个 P* 水平；既有单点现象不能归因于结构常数。
- 不是 `observed_single_level_only`，也不是 cap 未决；最终分类为 `multiple_reachable_pstar_levels`。

因此，EP、LC、SU 的既有单点现象应保留为联合搜索及其 Q/P* 支配关系下的 observed 事实，不能被改写为 D/P* 全空间退化定理。

## 4. 六个多点网段

CH、DA、DK、GL、IC、PT 的可达 P* 水平总数分别为 `134、299、265、412、342、186`；archive 观察水平数分别为 `6、14、45、52、36、5`。对应 level coverage 为 `3/67、14/299、9/53、13/103、2/19、5/186`，histogram coverage 为 `1/189、7/12389、46/18359、28/47619、19/24973、5/3744`。

六个网段的 archive assignments 全部重新投影到当前 D 直方图，并用当前生产精确内层重算 P*：CH/DA/DK/GL/IC/PT 分别检查 `134/288/301/337/319/191` 个 assignments，所有行均为 `exact_match`。因此 observed 多水平事实与当前结构层级一致。但是，本诊断只证明候选 Offset 经 D 直方图映射后有哪些 P* 水平可达；它不计算完整 Q/P* 目标像，不能据此证明完整 Pareto 前沿或其中必然有多少点。

## 5. Archive coverage 与 provenance

九个 archive source commit 都与诊断 commit 不同。可比性不是仅凭数值相似认定，而是同时满足：

1. 当前 DBC、ARXML、路由和配置 hash 与锁定 manifest 一致；
2. eligible-set hash、decision/fixed 数量及固定消息 `{0}` 域与 manifest 一致；
3. archive network、`rho` 和 domain facts 一致；
4. 每个 archive assignment 完整、Offset 合法、assignment hash 可复算；
5. 所有 archive P* 均由当前生产精确内层重新计算并 exact match。

据此九个网段均标记 `provenance_comparable=true`，可以报告上表中的结构 coverage。该结论只表示旧 archive 的观察项可与当前锁定输入下的 D/P* 结构比较，不把两个 commit 混成同一次实验，也不掩盖 manifest 记录的非干净 archive source worktree。

## 6. 结果边界

- D/P* 结构覆盖不等于 assignment 覆盖；许多 assignments 可映射到同一 gcd 直方图。
- 100% P* level coverage 也不等于 Q/P* Pareto 完整；本次所有网段的 level coverage 均远低于 100%。
- `rho=1` 是未标定场景，不能解释为真实 ECU 标定值。
- Archive provenance 无法证明可比时，诊断必须把 comparison 标为 `not_comparable` 且 coverage 置为 `null`；本报告的 coverage 只基于上述显式可比性检查。
- Capped 结果不能做结构常数判断。首次 IC 运行严格保留为 capped；只有 timeout 提高后完成的第二次运行用于最终 exact 表格。
- 多个可达 P* 水平不意味着完整 Pareto 前沿一定多点；反之，observed 单点也不意味着软件目标在全空间恒定。
- 本报告没有修改论文正文；论文如何改写应等待人工审阅这些真实诊断结果后再决定。
