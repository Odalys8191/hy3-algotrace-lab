# 正式选题资格链执行报告（2026-09-11）

执行时间：2026-09-11（Asia/Shanghai）
工作树：`$HY3_PROJECT_ROOT`
外部输出根：`$HY3_DATA_HOME/codecontests-v1/qualification-20260911-v1`
项目性质：个人活动实战作品，非腾讯官方发布

## 1. 结论

- 30 条人工终稿已在不改写人工值的前提下派生为 30 份 `CandidateReview`，30/30 通过
  `CandidateReview.model_validate_json`。
- 30 个原始行均通过既有 Parquet 加载路径回放；`problem_id`、`split`、`row_number`、
  `raw_row_hash` 同时匹配 corrected 清单和冻结清单。没有修改 raw 或冻结原件。
- `create-review-artifact` 30 次、`create-review-set` 2 次、`pin-review-manifest` 1 次、
  `convert-formal` 2 次、`quota`、`freeze-selection`、`verify-selection-chain` 均返回 0；没有
  rc=2 或被覆盖的产物。
- 配额状态为 `fulfilled`：validation 13、test 17，共 30 个 eligible；15 格逐格恰好 2 题。
- 冻结选择哈希（也是 replay receipt 的 `selection_manifest_hash`）：
  `add81f90ac03ae2e1664c798cce55a25e20ffb96d318700028a11c4c471d5d4a`。
- 本轮没有调用模型 API、没有远程请求、没有运行 benchmark、没有运行 Docker Judge，费用为 0。
- `formal=true` 执行意图未生成：当前数据根不存在完整 165 样本 corpus、30 个项目自编 bundle、
  60 行 natural materialization、105 项 Judge evidence 或可供 `BenchmarkConfig` 绑定的
  `verified_data_evidence`。`prepare_formal_intent.py` 因而没有被调用；用占位哈希或编造
  `sample_specs` 会违反 §2.2 和 fail-closed 约束。

## 2. 输入身份与哈希

| 输入 | SHA-256 / 规范哈希 |
| --- | --- |
| `human-review-checklist.corrected.json` 文件字节 | `3c6b154bb0260c549245f77535bc3cfd5bafc2539ec4eb0ae6f371d6764b7c3d` |
| corrected JSON 规范哈希 | `cf9b1cb2d91ce99107ea658598fd99e4040efc31a154c41315f8425d478eafdc` |
| `补充决定-v2-20260911.md` 文件字节 | `74bfabe361ab2a5eacaff6920e2d315d9e1b1dc1d9e3617d65950cb8abe6716b` |
| `检查结果与下一轮.md` 文件字节 | `3dd185b35d8aa002a7b4d76054328901b8b56c1202de0d427ae4b4de0e8cca6b` |
| 冻结 checklist 文件字节 | `546f608e8c4f59a7e1f037393684c3f0578174db75a13d6a0df858adf32bfeb1` |
| 冻结 checklist 规范哈希 | `bdd3612ba78a3e59b20b8cdb2df2cbc991b2b7a097aa1eb3894823c33a0aaf76` |
| 冻结 selection-manifest 文件字节 | `52419177bbb7fc5fa5abb4f291337f8da5c342c67b080ce4b0c0da3db043270c` |
| 冻结原始 `items_hash` | `1c88bc6b594447ad4bede310dcb7af38a69d275449c1d1ac842ef23499942c54` |
| acquisition | `36b67942ceef2bdb4ae676e353dc212ba09afcfb7dd07b4a43f5f023cbf5cb72` |
| acquisition-validation | `96818fa9a1fad8178c9f9a1312711d23608cdc180f744d0e09adb731ab97e0a4` |
| raw validation Parquet | `02e8c1ccedae716f1e43cc813fcb7823c3db666ea92638820aba80e8cef451ab` |
| raw test Parquet | `aa426cbdb202bf8703b658bcb31fd1878ca7cfd33ca07d3b703dc94ca6a2b651` |

启动时 `HEAD=f3e81b471f014ee63ff0441bba5a1bf659e5a736`，工作树干净。acquisition 的
converter 为 `hy3-codecontests-parquet` / `preflight-v1-memory-floor-pyarrow-25.0.1`，没有
converter argv；两次转换和两 split 回放均保持 argv 缺省。

## 3. 人工终稿派生

派生代码先完整加载两份 Parquet，并调用 `scripts/select_human_review.py::_read_raw` 与
`dataset_models._load_rows` 的既有路径交叉核对。30 条全部预验证通过后才使用独占创建写出：

- `candidate-reviews/01-cf-1613-c.json` 至 `30-cf-1620-d.json`；
- `raw-rows/01-cf-1613-c.json` 至 `30-cf-1620-d.json`；
- `logs/prederive-validation.json`：逐题文件 SHA、原始行身份与 30/30 验证摘要。

每份 review 只含 `CandidateReview.model_fields` 允许字段。人工字段逐值与 corrected 输入相等；
`cf-1551-d1` 是唯一带 `output_comparison=case_insensitive` 的条目，其余 29 条省略该字段，继续
表示历史 exact 默认值。`cf-1617-c.primary_topic=binary_search`；reviewer 全部为 `odalys`，时间
全部保留原带时区字符串。

执行命令：

```bash
env -u PYTHONPATH .venv/bin/python $HY3_DATA_HOME/codecontests-v1/qualification-20260911-v1/logs/derive_qualification_inputs.py
```

## 4. 资格链命令与产物

所有 Python 子进程继承了外层 `env -u PYTHONPATH`。33 条 review 阶段命令的逐项完整 argv、
returncode、stdout、stderr 位于 `logs/review-chain-commands.json`；5 条 selection 阶段命令的
相同证据位于 `logs/selection-chain-commands.json`。两个日志的每个 returncode 都是 0。

### 4.1 Review artifact / set / manifest

外层命令：

```bash
env -u PYTHONPATH .venv/bin/python $HY3_DATA_HOME/codecontests-v1/qualification-20260911-v1/logs/run_review_chain.py
```

逐题实际形式（对清单 01–30 分别执行，完整展开见上述命令日志）：

```bash
env -u PYTHONPATH .venv/bin/python -m hy3_algotrace.dataset_cli create-review-artifact \
  <candidate-reviews/NN-problem_id.json> --raw-row <raw-rows/NN-problem_id.json> \
  --output <review-artifacts/NN-problem_id.json>
```

随后分别执行 `create-review-set --split validation`（13 个 `--artifact`）与
`create-review-set --split test`（17 个 `--artifact`），再执行：

```bash
env -u PYTHONPATH .venv/bin/python -m hy3_algotrace.dataset_cli pin-review-manifest \
  --validation <review-sets/validation.json> --test <review-sets/test.json> \
  --output <review-manifest.json>
```

产物：

- `review-artifacts/*.json`：30 个；
- `review-sets/validation.json`：13 个 artifact；
- `review-sets/test.json`：17 个 artifact；
- `review-manifest.json`：`content_hash=38b7820e8c80a367feec6a22cbc9cb91ec327e9b97af39d924a6ea09944c251b`。

### 4.2 Conversion / quota / freeze / replay

外层命令：

```bash
env -u PYTHONPATH .venv/bin/python $HY3_DATA_HOME/codecontests-v1/qualification-20260911-v1/logs/run_selection_chain.py
```

该命令顺序执行并记录以下 CLI：

1. `convert-formal raw/validation.parquet --split validation --format parquet ...` →
   `selection/conversion-validation.json`；
2. `convert-formal raw/test.parquet --split test --format parquet ...` →
   `selection/conversion-test.json`；
3. `quota <两份 conversion> --output selection/quota.json`；
4. `freeze-selection selection/selected-ids.json --conversion <validation> --conversion <test> ...`
   → `selection/frozen-selection.json`；
5. `verify-selection-chain selection/frozen-selection.json --validation-raw ... --test-raw ...
   --validation-format parquet --test-format parquet --validation-reviews ... --test-reviews ...`
   → `selection/selection-replay-receipt.json`。

两个 `convert-formal` 都显式传入 acquisition 中的 converter name/version，均未传
`--converter-arg`。回放也未传 `--validation-converter-arg` 或 `--test-converter-arg`。

## 5. 配额与冻结证据

| 主题 | 1200–1500 | 1600–1900 | 2000–2400 |
| --- | --- | --- | --- |
| construction_simulation | cf-1556-b, cf-1579-c | cf-1551-d1, cf-1556-c | cf-1575-k, cf-1618-f |
| greedy | cf-1553-d, cf-1618-d | cf-1554-b, cf-1579-e2 | cf-1618-g, cf-1620-d |
| binary_search | cf-1613-c, cf-1617-c | cf-1549-d, cf-1622-c | cf-1551-e, cf-1552-f |
| dynamic_programming | cf-1553-b, cf-1598-c | cf-1557-c, cf-1567-c | cf-1575-l, cf-1606-e |
| graph | cf-1549-c, cf-1581-b | cf-1552-d, cf-1608-c | cf-1608-d, cf-1613-e |

- quota：`status=fulfilled`、`eligible_total=30`、15 个 `eligible_count` 全为 2；
- quota `content_hash=f65c7f9cc0ea43daf869d1b6b9155df6a5b416926c71fda1cbc5d2e5560ab5af`；
- FrozenSelectionManifest：30 entries；
- `selection_manifest_hash=add81f90ac03ae2e1664c798cce55a25e20ffb96d318700028a11c4c471d5d4a`；
- SelectionReplayReceipt：
  `content_hash=5fb2d318ccf7129650b9d4aedab6988fea7d0750dabff5e3c34bcd22f557d001`，
  `formal_eligibility=false`、`capability_persisted=false`（receipt 只证明回放发生，不自行恢复能力）。

`logs/chain-evidence.json` 再次独立解析全部 Pydantic 工件、复核计数与文件 SHA。生成命令：

```bash
env -u PYTHONPATH .venv/bin/python $HY3_DATA_HOME/codecontests-v1/qualification-20260911-v1/logs/verify_qualification_outputs.py
```

## 6. §2.2 正式执行意图状态

预定运行时身份已经明确，但没有写成无效工件：

- `formal=true`；model=`hy3`；endpoint=`https://tokenhub.tencentmaas.com/v1`；
- `timeout_seconds=600`，运行时必须设置 `HY3_TIMEOUT_SECONDS=600`；
- `remote_attempt_budget=500`；
- Judge 固定镜像：
  `localhost:15088/hy3-algotrace-judge@sha256:47c12489acef3ae4e6e386ae346fc4a830e39a4b1e29dd776e444391fb628db3`；
- 代码版本应取生成时干净工作树的 Git HEAD。

但 `BenchmarkConfig._validate_formal_profile()` 明确要求 30/60/15/60 共 165 个真实 sample spec、
60 个 natural generation ID、165 个 audit ID、30 个问题的逐题分布，以及与真实 corpus hash 一致
的 `verified_data_evidence`。当前磁盘没有这些输入。因此以下预期路径均**未创建**：

- `intent/config.template-formal-v1.json`；
- `intent/config.runtime-formal-v1.json`；
- `intent/intent-manifest-formal-v1.json`。

确定性前置检查见 `logs/intent-preflight.json`。在完整 corpus/证据到位后，才可用下述命令一次性
冻结；同名路径一旦存在不得复用：

```bash
HY3_MODEL=hy3 \
HY3_BASE_URL=https://tokenhub.tencentmaas.com/v1 \
HY3_TIMEOUT_SECONDS=600 \
HY3_JUDGE_IMAGE='localhost:15088/hy3-algotrace-judge@sha256:47c12489acef3ae4e6e386ae346fc4a830e39a4b1e29dd776e444391fb628db3' \
env -u PYTHONPATH .venv/bin/python scripts/prepare_formal_intent.py \
  --template <真实165样本配置模板> --tag formal-v1 --slug hy3-formal \
  --timeout-seconds 600 \
  --out-dir $HY3_DATA_HOME/codecontests-v1/qualification-20260911-v1/intent \
  --repo-root $HY3_PROJECT_ROOT
```

这里没有设置或读取 `HY3_API_KEY`，也没有发起 `formal=true` 运行。

## 7. differential.py 最小方案（本轮未实现）

根因链：

1. `catalog.py::_load_formal_bundle_at` 能从可选 `checker.json` 读取
   `CheckerSemantics.output_comparison`，并放入 `ProblemBundle.output_comparison`；
2. `run_service.py` 与 `live_benchmark.py` 已把该值传给 `Judge.judge`；
3. `differential.py::JudgeSourceCase` 只有 `ProblemRecord` 与源码，
   `validate_judge_cases` / `validate_formal_corpus_judge_cases` 调用 `judge.judge` 时没有 comparison；
4. `run_differential_tests` 又直接执行 `stdout.split() == expected.split()`；
5. 正式 `ProjectBundleManifest` 目前不引用 `checker.json`，persisted evidence 也不记录 comparison。
   因而只在 `differential.py` 加 `casefold()` 无法证明 #9 语义来自冻结审核，且存在放宽其他题目的风险。

最小、默认行为不变且不修改 `contracts.py` 的实现边界：

1. 给内部 `JudgeSourceCase` 增加 `output_comparison: OutputComparison = EXACT`；给
   `PersistedJudgeCaseEvidence` 增加同样的默认字段，使新证据绑定比较语义，旧 exact JSON 仍可读。
2. `validate_judge_cases` 与 `validate_formal_corpus_judge_cases` 调用
   `judge.judge(..., output_comparison=case.output_comparison)`；`run_differential_tests` 增加同默认参数，
   复用 `docker_judge` 的统一 token comparison helper，禁止独立再写一种 lower 规则。
3. corpus/bundle authoring 把 `ProblemBundle.output_comparison` 复制到 `JudgeSourceCase`；非默认时把
   `checker.json` 作为 `AuthoredBundleEntry` 的可选 JSON `ArtifactRef` 纳入 bundle content hash，
   缺失继续表示 exact。
4. `formal_qualification.py` 从已 pin 的两个 review set 重建 `problem_id → comparison`，要求
   `JudgeSourceCase`、persisted evidence 和可选 `checker.json` 三者一致；#9 必须是
   `case_insensitive`，其余 29 题必须是 exact。任何缺失、篡改或跨题复用 fail closed。

验收测试：

- differential 的 `YES` 对 `yes` 在 #9 语义下 matched，在默认 exact 下 mismatch；空白 token 规则不变；
- injected Judge spy 能看到 gold/mutant/paradox 三类 case 的逐题 comparison；
- 没有 `checker.json` 的旧 bundle、旧 `JudgeSourceCase` 和旧 evidence 保持 exact 且可读；
- 正式资格桥拒绝 case/review/checker/evidence 任意两者不一致、checker problem_id 不匹配、未知字段、
  或对非 #9 题擅自放宽；
- 新报告的 hash 对 comparison 变化敏感；原有 catalog hash 的 exact 默认字节行为不变；
- focused tests、完整非 Docker pytest、`ruff check .`、`mypy src`、release validation 全通过。

这会触及 corpus/bundle 的内部版本化数据模型与正式资格调用点，虽然不需要改共享
`contracts.py`，仍超过“仅改 differential 单点”的安全范围，故本轮只列方案，不把未审设计硬塞进
已经冻结的 selection 链。

## 8. 进入付费正式基准还缺什么

1. 完成 30 个项目自编 bundle、30 gold / 60 controlled-wrong / 15 paradox，并构建完整 corpus；
2. 生成 60 个 natural 样本及内容寻址 materialization，形成完整 165 样本 manifest；这一步会
   调用 GA `hy3`，必须先获得用户明确付费授权；
3. 以真实 Docker Judge 生成并验证 105 项 evidence，并把 #9 comparison 按上一节方案贯通；
4. 在外部 `.env` 配置 TokenHub GA 付费键与运行值（至少 API key、`HY3_MODEL=hy3`、TokenHub
   base URL、`HY3_TIMEOUT_SECONDS=600`、digest-pinned `HY3_JUDGE_IMAGE`）；`.env` 不进 Git；
5. Docker socket `/var/run/docker.sock` 当前存在，但本轮遵守约束未探测 daemon/镜像；正式运行前
   需在用户本机 Terminal 验证 socket 权限、daemon 与固定镜像 digest；
6. 用户再次明确授权付费 formal run；当前估算约 ¥25–50/165 样本全量，500 是远程 attempt 硬上限，
   不是费用守卫；
7. 上述输入完成后生成 `config.runtime` + intent manifest，自校验通过后才允许启动一次性
   `formal=true` benchmark。

本轮没有把缺失条件描述为已就绪，也没有把 selection replay receipt 描述为正式运行资格。

## 9. 本轮验证

均在指定 worktree 中使用隔离的 `/private/tmp` basetemp 执行：

```text
env -u PYTHONPATH .venv/bin/python -m pytest -q tests/test_dataset_models.py tests/test_dataset_cli.py tests/test_intent.py tests/test_task2_review_regressions.py tests/test_dataset_differential.py --basetemp=/private/tmp/hy4oi-qualification-focused-20260911-v1
107 passed in 5.96s

env -u PYTHONPATH .venv/bin/python -m pytest -q -m 'not docker_integration' --basetemp=/private/tmp/hy4oi-qualification-full-20260911-v1
646 passed, 9 deselected, 1 Starlette deprecation warning in 40.89s

env -u PYTHONPATH .venv/bin/python -m ruff check .
All checks passed!

env -u PYTHONPATH .venv/bin/python -m mypy src
Success: no issues found in 36 source files

env -u PYTHONPATH .venv/bin/python -m hy3_algotrace.release_validation --root .
release validation passed (142 files checked)
```

Docker integration 按本轮约束未执行；唯一 warning 是既有 Starlette/httpx deprecation warning。
