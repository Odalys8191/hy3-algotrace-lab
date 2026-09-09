# 正式语料生命周期：执行意图冻结与运行结果冻结

日期：2026-09-10（Asia/Shanghai）｜性质：设计定稿 + 30 题人工审核冻结准备｜个人活动实战作品，非腾讯官方发布

本轮**未发起任何模型请求**（含付费 GA `hy3`），未产生任何新的运行结果或正式资格证据，
未修改外部数据根的原始数据与既有运行工件。

## 0. 为什么分成两个阶段

自然语料（natural 样本）的实体化依赖运行本身产生的生成事件与最终 trace，因此
「跑之前就要把语料哈希冻结」和「跑完之后才有语料」在单次冻结里是矛盾的。解决方案是
把冻结拆成两次、绑定两类不同的对象：

| 维度 | 执行意图冻结（intent freeze） | 运行结果冻结（result freeze） |
| --- | --- | --- |
| 时点 | 正式运行发起之前 | 运行落盘之时（report/ledger/live-evidence 写出即刻） |
| 冻结对象 | 「打算怎么跑」的全部身份：配置、题集、语料输入、提示词、代码、判题镜像、超时、模型与端点 | 「跑出了什么」的全部证据：report、metrics、CI、breakpoint、charts、账本、observations、live-evidence |
| 绑定标识 | `intent_hash` → 派生 `benchmark_id` | `benchmark_id` 输出目录（create-only） |
| 变更后果 | 任一对象变更 ⇒ 新 `benchmark_id`，旧意图作废 | 永不变更；只允许追加新的 `benchmark_id` |
| 失败语义 | 意图不完整 ⇒ 不允许发起运行（rc=2） | 单题失败 ⇒ 保留 partial、计入账本、`complete=false` |

意图冻结先于运行、结果冻结后于运行，**结果冻结必须携带其意图冻结的哈希**（见 §2.3），
二者之间不存在第三种状态：既没有「先跑再补意图」，也没有「只落结果不绑意图」。

## 1. 非承诺与证据边界

- ga-v5 单题 smoke（2026-09-09，GA `hy3`）只证明链路可跑通，**不可外推为正式性能或正式资格**。
- 本轮产出的 30 题清单是**待人工审核的草案**：审核字段全空，未产生任何 `CandidateReview`。
- 本文档定义规则，不声明任何正式基准已经完成；165 样本、`formal=true` 的运行尚未发生。

## 2. 执行意图冻结

### 2.1 冻结对象清单

下表「代码强制」列指当前源码是否在运行时比对并 fail-closed；标注「仅 manifest」的项
**不被代码校验**，靠人工核对，不得误当作已实现的保护。

| # | 对象 | 载体 | 绑定方式 | 代码强制 |
| --- | --- | --- | --- | --- |
| 1 | `config.runtime` SHA-256 | 外部配置根 `config.runtime-<tag>.json` | 文件字节 SHA-256；配置内容含 `benchmark_id`、`selection_hash`、`corpus_hash`、`ordered_sample_ids`、`sample_specs`、`generation/audit_sample_ids`、`model`、`endpoint_identity`、四个 prompt 版本、`model_parameters`、`code_revision`、`judge_image_digest`、`metric_version`、`chart_version`、`seed`、`bootstrap_replicates`、`remote_attempt_budget`、`formal` | 是（`BenchmarkConfig` 校验 + `validate-config`） |
| 2 | catalog 哈希 | `BenchmarkConfig.selection_hash` | `live_benchmark.catalog_hash()`：每题 `problem/oracle/reference/gold_trace` 的内容哈希聚合 | 是（`validate_live_inputs`） |
| 3 | 语料/输入哈希 | `BenchmarkConfig.corpus_hash` | `LiveInputs.content_hash`（非自然语料）或正式语料清单哈希 | 是（`validate_live_inputs`） |
| 4 | 提示词版本 | 四个 `*prompt_version` 字段 | 与 `prompts.py` 常量逐一比对（`solution-trace-v1`、`logic-dependency-review-v1`、`adversarial-review-v1`、`material-disagreement-arbiter-v1`） | 是（`validate_live_inputs`） |
| 5 | 代码版本 | `code_revision` | 运行前 `git rev-parse HEAD`，要求工作树干净（沿用 ga-v5 准备脚本的断言） | 部分（写入配置；生成时需人工保证干净） |
| 6 | 判题镜像 | `judge_image_digest`（`sha256:…`） | 进程环境 `HY3_JUDGE_IMAGE` 引用中的 digest 必须相等，且运行前 `probe_docker` 校验 `docker info` + `docker image inspect` | 是（`LiveExecutor` + `probe_docker`） |
| 7 | 读超时 | `HY3_TIMEOUT_SECONDS` | 只记录于 intent manifest（runtime-basis 的 `timeout_seconds` 与进程环境覆盖） | **仅 manifest**：`Hy3Config.from_env` 读默认 60，不与冻结值比对 |
| 8 | 模型身份 | `model` | 与运行时 `Hy3Config.model` 全等；正式基准固定 `hy3`（GA），禁止与 `hy3-preview` 混用 | 是（`LiveExecutor`） |
| 9 | 端点身份 | `endpoint_identity` | 去凭据的绝对 URL（scheme+host+path），与运行时 `endpoint_identity(base_url)` 全等；正式基准固定 `https://tokenhub.tencentmaas.com/v1`；非 HTTPS 直接拒绝 | 是（`LiveExecutor`） |
| 10 | 调用预算与随机性 | `remote_attempt_budget`（≤500）、`seed`、`bootstrap_replicates` | 包含在 #1 的 config SHA-256 内；预算低于静态下界（生成数 + 2×审查数）即校验失败 | 是（`BenchmarkConfig`） |

第 7 项是已知缺口：超时值不在 `BenchmarkConfig` 内，代码不会拒绝一个与冻结值不同的
`HY3_TIMEOUT_SECONDS`。冻结纪律要求：意图 manifest 写明数值，发起运行前人工核对进程环境；
若数值不同，视同意图变更，必须换 `benchmark_id`。

### 2.2 intent manifest 结构

生成 `config.runtime` 的同一脚本必须同时写出 intent manifest（沿用 ga-v5 的
`runtime-basis.json` 字段并补齐下列键）：

```json
{
  "schema_version": "1.2",
  "kind": "formal_execution_intent",
  "benchmark_id": "<id>",
  "recorded_at": "<tz-aware ISO-8601>",
  "formal": true,
  "config_sha256": "<#1>",
  "selection_hash": "<#2>",
  "corpus_hash": "<#3>",
  "prompt_versions": {"generator": "...", "logic_review": "...", "adversarial_review": "...", "arbiter": "..."},
  "code_revision": "<#5>",
  "worktree_clean": true,
  "judge_image_digest": "sha256:...",
  "timeout_seconds": 600,
  "model": "hy3",
  "endpoint_identity": "https://tokenhub.tencentmaas.com/v1",
  "remote_attempt_budget": 500,
  "intent_hash": "<SHA-256 of the canonical JSON of all fields above except intent_hash>"
}
```

`intent_hash` = 上表 #1–#10 全部字段（不含自身）的规范 JSON SHA-256。`benchmark_id` 由
`intent_hash` 派生（建议 `<slug>-<intent_hash[:12]>`），使「配置变了但 id 没变」在命名层就不可能。

### 2.3 不可变性规则

1. 意图 manifest 与 `config.runtime` 在外部配置根**一次性写出、只读**；同一 `benchmark_id`
   的输出根为 create-only，重复写入必然失败。
2. 冻结后**任何**一项（含 `HY3_TIMEOUT_SECONDS`）发生变更 ⇒ 生成新 `intent_hash` ⇒ 新
   `benchmark_id` ⇒ 新输出根；旧意图标记为 superseded，**不删除、不改写**，并在
   `runtime-basis` 的 `prior_attempts` 中记录已消耗的远程请求数。
3. 结果冻结必须携带 `intent_hash`（写到运行目录的 `run-result.json` / `report.json`
   引用字段），否则该运行不得计入正式结论。
4. 一个意图只对应一次运行尝试；「重试」只允许发生在同一运行尚未产生任何 ledger 记录且
   尚未写出 report 的情况下，否则一律走新 `benchmark_id`。

## 3. 运行结果冻结

落盘即只读，覆盖范围：

- `benchmarks/<benchmark_id>/`：`report.json`、`metrics.json`、`confidence-intervals.json`、
  `breakpoint.json`、`charts/*`、`ledger-index.json`、`observations/*`、`failure.json`；
- `benchmarks/<benchmark_id>/live-evidence/<sample_id>/`：`trace.json`、`judge.json`、
  `result.json`、`failure.json`；
- 配置根的 `config.runtime*.json`、`runtime-basis.json`、`http-diagnostic.json`、`run-result.json`。

规则：

1. **只追加**：新增运行只能以新的 `benchmark_id`（因而新的输出根）进行，写入由
   `ArtifactStore` 的 `O_EXCL` + `link` 发布，已存在即 `ArtifactExistsError`。
2. **禁止改写与删除**：任何 edit / patch / rename / 重新生成同名工件 / `rm` 都违反冻结；
   需要修正结论时，写新运行 + 新报告，并在报告中列出被替代的 `benchmark_id`。
3. **partial 也是结果**：失败运行的目录与成功运行同等只读，`failure.json` 与已有
   `trace/judge` 不得清理。
4. **聚合不合并**：多个 `benchmark_id` 的结论在报告里逐个列出、分别标注 `formal` 与
   `complete`，不得把不同意图的运行拼成一份「基准」。

## 4. 单题失败（rc=2，fail-closed）在正式基准中的处理

链路：`LiveExecutor.__call__` 在 generation / judge / review / persist 任一阶段抛出异常
⇒ 写出 `live-evidence/<sample_id>/failure.json`（含 `phase`）⇒ 抛 `LiveExecutionError`
⇒ `benchmark_cli` 执行 `ledger.finalize()` 并写 `benchmarks/<id>/failure.json` ⇒ stdout
输出 `{"status":"execution_failed","formal_eligible":false}` ⇒ **退出码 2**。

1. **保留 partial**：失败样本已落盘的 `trace/judge/result` 与 `failure.json` 全部保留，
   禁止删除或改写；这些是证据，不是垃圾。
2. **计入账本**：失败前已发生的远程请求已在 ledger 中；`ledger.finalize()` 必须执行，
   使消耗可核对。失败**不产生** `MetricObservation`，也不得回填任何占位/猜测观测值。
3. **不得重试覆盖**：禁止用同一 `benchmark_id` 重跑以覆盖失败；补救只能以新
   `benchmark_id`（新输出根）发起，且原运行目录保持原样。
4. **整体失败**：任一样本失败 ⇒ 该 `benchmark_id` 的 `complete=false`、
   `formal_eligible=false`；不得挑选成功样本冒充「完整基准」，也不得据此发布准确率。
5. **预算**：失败请求同样计入 `remote_attempt_budget`（上限 500）；`BudgetExceededError`
   直接 fail，不再转换。
6. **报告口径**：正式报告必须列出失败样本、失败阶段与已消耗请求数，并声明
   「部分运行、非完整基准」。

## 5. 30 题人工审核冻结准备

### 5.1 选择规则

`rule_id = formal-selection-quota-15-cell-v1`，`rule_hash =
66b3a914812e617f85843df28b971078b996014fa4121650f8a21912ca943167`（规则参数的规范 JSON
SHA-256，参数变更即换哈希）。

- 配额：5 个主主题 × 3 个难度段 = 15 格，每格 2 题，共 30 题，同一题只占一个名额。
- 候选定义：结构评估器在**无任何人工审核**前提下通过，且至少能映射到一个受支持主题。
- 优先池：优先取未触发判题提示（多解 / 交互 / 浮点容差）的候选；当该池无法填满 15 格时，
  回退到全部结构候选（本轮未触发回退，见 §5.3）。
- 匹配与排序：确定性二分增广匹配；候选顺序为「支持主题数少 → rating 低 → problem_id」；
  槽位顺序为「格内候选数少 → 主题 → 难度段 → 槽位」；输出顺序为主题、难度段、problem_id。
- 不足任何一格即 fail-closed，不产出残缺清单（脚本退出码 2）。
- 实现：`scripts/select_human_review.py`，匹配逻辑复用
  `hy3_algotrace.data_preflight.assign_candidates`（预检草案与正式清单共用同一实现，避免漂移）；
  测试 `tests/test_select_human_review.py`。

### 5.2 清单与留空字段

- 位置（外部数据根，**不进 git**）：
  `/Users/odalys/Documents/hy4oi-data/codecontests-v1/human-review-20260910-v1/`
  - `human-review-checklist.json`（SHA-256 `bdd3612ba78a3e59b20b8cdb2df2cbc991b2b7a097aa1eb3894823c33a0aaf76`）
  - `selection-manifest.json`（SHA-256 `52419177bbb7fc5fa5abb4f291337f8da5c342c67b080ce4b0c0da3db043270c`）
  - `items_hash = 1c88bc6b594447ad4bede310dcb7af38a69d275449c1d1ac842ef23499942c54`（30 条选题的规范 JSON 哈希）
- 输入：`raw/validation.parquet`（117 题，`02e8c1cc…51ab`）、`raw/test.parquet`（165 题，
  `aa426cbd…b651`），共 282 题；结构候选 84 题，未触发判题提示候选 59 题，本轮使用优先池。
- 每条记录留空并等待人工填写的字段：`checker_reviewed`（`false`）、`checker_kind`
  （`unreviewed`）、`primary_topic`（`null`）、`primary_topic_reviewed`（`false`）、
  `reviewer`（`null`）、`reviewed_at`（`null`）、`notes`（`""`）。这些字段**不得由工具或
  模型代填**；填写后才可走既有 `create-review-artifact / create-review-set /
  pin-review-manifest` 路径，本清单本身不是这些命令的有效输入。

### 5.3 选出的 30 题

与 2026-09-07 预检草案（`preflight-20260907-v3`）提出的 30 题集合**完全一致**（脚本从原始
Parquet 重新计算，交叉验证通过）。审核优先级建议沿用预检结论：基础二分、基础图论、中档图论
余量最小，优先审核；不通过时人工复核备选，无法补足则保持 not-ready，不自动放宽标准。

| # | 题目 | split | 行号 | rating | 主主题（草案） | 难度段 | raw_row_hash（前 16） |
| --- | --- | ---: | ---: | ---: | --- | --- | --- |
| 1 | [1613_C](https://codeforces.com/problemset/problem/1613/C) | test | 116 | 1200 | 二分 | 1200-1500 | `e44dd4912017f199` |
| 2 | [1617_C](https://codeforces.com/problemset/problem/1617/C) | test | 130 | 1300 | 二分 | 1200-1500 | `5a1e8331230deece` |
| 3 | [1549_D](https://codeforces.com/problemset/problem/1549/D) | validation | 8 | 1800 | 二分 | 1600-1900 | `04166918aa89c8ec` |
| 4 | [1622_C](https://codeforces.com/problemset/problem/1622/C) | test | 157 | 1600 | 二分 | 1600-1900 | `4273a723e35811f9` |
| 5 | [1551_E](https://codeforces.com/problemset/problem/1551/E) | validation | 15 | 2000 | 二分 | 2000-2400 | `eab0ec62c98cbf55` |
| 6 | [1552_F](https://codeforces.com/problemset/problem/1552/F) | validation | 22 | 2200 | 二分 | 2000-2400 | `5c6d7a4f9d67359f` |
| 7 | [1556_B](https://codeforces.com/problemset/problem/1556/B) | validation | 46 | 1300 | 构造/模拟 | 1200-1500 | `5e983459905edb67` |
| 8 | [1579_C](https://codeforces.com/problemset/problem/1579/C) | test | 16 | 1500 | 构造/模拟 | 1200-1500 | `781d8c71dea6b349` |
| 9 | [1551_D1](https://codeforces.com/problemset/problem/1551/D1) | validation | 13 | 1700 | 构造/模拟 | 1600-1900 | `749718ec2bf90576` |
| 10 | [1556_C](https://codeforces.com/problemset/problem/1556/C) | validation | 47 | 1800 | 构造/模拟 | 1600-1900 | `5ba3ad2deb408017` |
| 11 | [1575_K](https://codeforces.com/problemset/problem/1575/K) | test | 11 | 2200 | 构造/模拟 | 2000-2400 | `e605498c7e6068f9` |
| 12 | [1618_F](https://codeforces.com/problemset/problem/1618/F) | test | 138 | 2000 | 构造/模拟 | 2000-2400 | `3641de678c1eee9c` |
| 13 | [1553_B](https://codeforces.com/problemset/problem/1553/B) | validation | 26 | 1300 | 动态规划 | 1200-1500 | `4deb0da2ba805453` |
| 14 | [1598_C](https://codeforces.com/problemset/problem/1598/C) | test | 61 | 1200 | 动态规划 | 1200-1500 | `9e92ab1ec7130895` |
| 15 | [1557_C](https://codeforces.com/problemset/problem/1557/C) | validation | 55 | 1700 | 动态规划 | 1600-1900 | `5dd33d648618d88a` |
| 16 | [1567_C](https://codeforces.com/problemset/problem/1567/C) | validation | 95 | 1600 | 动态规划 | 1600-1900 | `fec8d992aff85606` |
| 17 | [1575_L](https://codeforces.com/problemset/problem/1575/L) | test | 12 | 2100 | 动态规划 | 2000-2400 | `a819e9afaaa5cd5a` |
| 18 | [1606_E](https://codeforces.com/problemset/problem/1606/E) | test | 97 | 2100 | 动态规划 | 2000-2400 | `860eb3cc9ca9d547` |
| 19 | [1549_C](https://codeforces.com/problemset/problem/1549/C) | validation | 7 | 1400 | 图论 | 1200-1500 | `b5f61a04152ba651` |
| 20 | [1581_B](https://codeforces.com/problemset/problem/1581/B) | test | 28 | 1200 | 图论 | 1200-1500 | `ccf546010a642661` |
| 21 | [1552_D](https://codeforces.com/problemset/problem/1552/D) | validation | 20 | 1800 | 图论 | 1600-1900 | `86fbb7e7e0ce16fa` |
| 22 | [1608_C](https://codeforces.com/problemset/problem/1608/C) | test | 109 | 1700 | 图论 | 1600-1900 | `ce2ca84945294828` |
| 23 | [1608_D](https://codeforces.com/problemset/problem/1608/D) | test | 110 | 2400 | 图论 | 2000-2400 | `c9c69e87b853df5e` |
| 24 | [1613_E](https://codeforces.com/problemset/problem/1613/E) | test | 118 | 2000 | 图论 | 2000-2400 | `f5e97d9d58931a83` |
| 25 | [1553_D](https://codeforces.com/problemset/problem/1553/D) | validation | 28 | 1500 | 贪心 | 1200-1500 | `27a945f1a5e8e550` |
| 26 | [1618_D](https://codeforces.com/problemset/problem/1618/D) | test | 136 | 1300 | 贪心 | 1200-1500 | `20703a9b8bfed0f6` |
| 27 | [1554_B](https://codeforces.com/problemset/problem/1554/B) | validation | 35 | 1700 | 贪心 | 1600-1900 | `2759ad8502f2030d` |
| 28 | [1579_E2](https://codeforces.com/problemset/problem/1579/E2) | test | 18 | 1700 | 贪心 | 1600-1900 | `471958c80f4553e8` |
| 29 | [1618_G](https://codeforces.com/problemset/problem/1618/G) | test | 139 | 2200 | 贪心 | 2000-2400 | `c51b494f45e910bf` |
| 30 | [1620_D](https://codeforces.com/problemset/problem/1620/D) | test | 151 | 2000 | 贪心 | 2000-2400 | `2497bd70cc738340` |

### 5.4 下轮顺序

1. 人工审核 30 题（先审余量最小的三格），填写 §5.2 的七个字段，附真实审核者标识与带时区时间。
2. 生成 `CandidateReview` 工件 → review set → pin manifest → `convert-formal → quota →
   freeze-selection → verify-selection-chain`。
3. 语料/基准就绪后，按 §2 生成正式 intent manifest（GA `hy3`、TokenHub 端点、
   `HY3_TIMEOUT_SECONDS=600`、预算 500），再发起 `formal=true` 运行。

## 6. 执行环境注意（本轮实测）

- WorkBuddy 沙盒会拦截 `~/Documents` 下**目录相对** `unlink`（`os.unlink(..., dir_fd=fd)`
  返回 `EPERM`），而 `ArtifactStore` 发布后会做该清理；普通路径 `unlink` 正常。
  `scripts/select_human_review.py` 的 `_publish` 因此会在捕获该 `PermissionError` 后回读已
  发布工件并比对规范哈希，一致才接受，不一致仍 fail-closed；残留的 `.…tmp` 文件需手工
  `rm`（外部数据根新目录中已清理）。**真实运行仍建议在本机 Terminal 执行。**
- pytest 在 `/var/folders/T` 下报 `PermissionError` 属沙盒假失败：用
  `env -u PYTHONPATH .venv/bin/pytest --basetemp=<全新目录>` 复核，勿改源码。
- 提交前若遇 `git index.lock`：先 `pgrep -x git` 确认无 git 进程再清理。
- `.env` 不提交；外部原始数据与既有运行工件只读，不进 git。
