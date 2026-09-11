# Agent 交接文档：Hy3 模型端点与版本决策

决策时间：2026-09-09（Asia/Shanghai）｜性质：已确认的用户决策，后续所有 Agent 与正式运行必须遵守

## 一、决策内容

| 阶段 | 模型 | 端点 | 计费 |
| --- | --- | --- | --- |
| Smoke run（链路验证，formal=false） | `hy3-preview` | TokenHub `https://tokenhub.tencentmaas.com/v1` | 新人免费体验包 100 万 tokens（90 天有效） |
| 正式基准（165 样本，formal=true） | `hy3`（GA 正式版） | TokenHub `https://tokenhub.tencentmaas.com/v1` | 按量付费，约 ¥25–50/全量 |

背景：此前 smoke 配置按 OpenRouter `tencent/hy3:free`（$0）冻结，现判定失效，全部切换到 TokenHub。

## 二、决策依据（已搜索核实，2026-09-09）

1. OpenRouter `tencent/hy3:free` 免费窗口为 2026-07-06 至 2026-07-21 16:00 UTC，已过期近两个月；即使免费档仍存，<$10 余额账号限 50 请求/天，无法支撑 165 样本 × 约 3 请求 ≈ 500 次的正式基准。
2. TokenHub 定价：`hy3` GA 为 1 元/百万输入、4 元/百万输出、0.25 元/百万缓存；`hy3-preview` 为 1.2 元/4 元，新人免费包仅覆盖 preview。
3. `hy3-preview`（2026-04-23 发布）与 GA `hy3`（2026-07-06 发布）架构完全一致（295B/21B 激活/256K），GA 提升全部来自后训练：幻觉率 12.5%→5.4%，MathArena Apex 12.8→38.7（+202%），Agent/代码 +20~30%。
4. 任务要求「模型能力调用通过 Hy3 完成」，参考仓库为 GA 版 Hy3，故正式结论必须出自 GA 模型；smoke 用 preview 只验证管道，结果不得外推。

## 三、执行要求

### 1. `.env` 变更（分两阶段）

Smoke 阶段：

```text
HY3_PROVIDER=tokenhub
HY3_API_BASE=https://tokenhub.tencentmaas.com/v1
HY3_MODEL=hy3-preview
HY3_ALLOW_PAID=false
HY3_MAX_PRICE_PROMPT=0
HY3_MAX_PRICE_COMPLETION=0
```

正式基准阶段（跑完 smoke 后切换）：

```text
HY3_MODEL=hy3
HY3_ALLOW_PAID=true
HY3_MAX_PRICE_PROMPT=1      # 元/百万输入，对齐 TokenHub 实价
HY3_MAX_PRICE_COMPLETION=4   # 元/百万输出
```

注意：当前 `.env` 若为 `MODEL=hy3` 且 `ALLOW_PAID=false`、价格上限 0，客户端价格守卫会拦截全部请求，一个都发不出去——这是已知坑，勿重复排查。

### 2. 运行前人工动作

- 在 TokenHub 控制台 → 模型广场 → 右上角「新用户福利免费体验」领取 `hy3-preview` 100 万 tokens 免费包（每主账号一次，90 天有效）。
- 免费额度仅够 smoke（约 3–12 次请求）；正式基准估算 5–10M tokens，必须走 GA 付费或 Hy Token Plan 套餐（套餐仅支持 preview，勿误订）。

### 3. Smoke 配置必须重新生成

- 旧 `config.runtime-v1.json`（含 `smoke-20260908-v1` 目录下所有 OpenRouter 身份工件）按 OpenRouter 冻结，**已失效，禁止直接使用**。
- 按 `docs/LIVE_SMOKE_2026-09-08.md` 流程，用新 `.env` 值（model=hy3-preview、endpoint=tokenhub、TokenHub 定价 basis）重新生成运行时配置并重跑 `validate-live-inputs`。
- benchmark 结果一次性创建：`smoke-runs-20260908-v1` 下已写入的 benchmark_id 不可复用，换新配置需新 benchmark_id 或新输出目录。
- Judge 镜像、catalog、live-inputs 不受端点切换影响，无需重建。

### 4. 真实性与报告约束

- README 与结果报告必须明确标注所用模型版本（preview / GA）与端点；正式结论只能引用 GA `hy3` 的运行。
- smoke 结果（preview）只用于验证链路，不得写入任何正式准确率/错误分布结论。
- 正式资格链已将模型、端点、参数哈希绑定进冻结配置，同一次正式基准内禁止混用两个模型版本。

## 四、当前项目位置（供接手 Agent 快速定位）

- 集成代码树：`.worktrees/integrate-task6-8`（分支 `codex/integrate-task6-8`）；集成改动 `95827ed`、端点决策 `6adbd0e`、超时可配置 `1f20f0f`、schema 净化 `e825980`、repair prompt 不变量 `03c1366`。
- 数据就绪：`/Users/odalys/Documents/hy4oi-data/codecontests-v1/raw/`（validation + test parquet，282 题，无需再下载）。
- **Smoke 链路已验证**：`hy3-preview` 2026-08-31 下线后，用户改用 GA `hy3`（付费授权）。经 ga-v1–v4 失败定位（超时、TokenHub json_schema 含 `minLength` 时剥字符串换行、repair 不含跨字段不变量）并修复后，`cf1613c-smoke-20260909-tokenhub-ga-v5` 于 2026-09-09 完成：`complete=true`，5 次请求，判题 AC（204 测试），双审查/融合/账本全链路真实走通。条件、命令、根因与结果见 [GA smoke 记录](LIVE_SMOKE_GA_2026-09-09.md)；preview 下线背景见 [2026-09-09 smoke 记录](LIVE_SMOKE_2026-09-09.md)。
- 配置与工件位于外部数据根 `smoke-20260909-tokenhub-{v1,v2}`（preview，失败）与 `smoke-20260909-tokenhub-ga-{v1..v5}`（GA）；所有 benchmark ID 均已占用，不可复用。执行环境注意：WorkBuddy 沙盒拦截 Documents 下 `os.unlink` 且无法访问 Docker socket，真实运行需用户 Terminal 或提权执行；pytest 在 `/var/folders/T` 下的 PermissionError 属沙盒假失败，用 `env -u PYTHONPATH .venv/bin/pytest --basetemp=<新目录>` 复核。
- 费用说明修正：上文“客户端价格守卫会拦截”的表述不符合当前源码，三个费用变量均未被客户端读取；价格上限 0 不是已实现的防超支保护。GA 牌价 1/4 元/百万（输入/输出）；smoke 累计真实请求 17 次 + 15 次诊断探针，总花费 ¥1 以内。
- **语料生命周期已定稿**：`docs/FORMAL_CORPUS_LIFECYCLE.md`（2026-09-10）定义执行意图冻结（10 项冻结对象 + intent manifest / intent_hash 派生 benchmark_id，已知缺口：`HY3_TIMEOUT_SECONDS` 仅 manifest 人工核对）与运行结果冻结（落盘即只读、仅追加新 benchmark_id）、单题失败（rc=2 fail-closed：保留 partial、计入账本、禁止重试覆盖）规则。
- **30 题人工审核已完成（2026-09-10 更正；2026-09-11 阻塞解除）**：七字段（primary_topic/reviewer/reviewed_at/notes 等）30/30 填写完毕，审核者 odalys。人工填写原件经语法修正后交付于 `review-output-20260910-v1/human-review-checklist.corrected.json`（修正明细见该目录 `检查结果与下一轮.md`；`review_status=pending_human_review`、`formal_eligibility=false` 为草案元信息，非漏填）。**尚未消费入正式资格链**（create-review-artifact 起的命令均未执行）。原三个阻塞已按用户 2026-09-11 决定解决（详见 `review-output-20260910-v1/补充决定-v2-20260911.md`）：① #2 最终主题为 binary_search（用户 15:33 亲改 corrected.json 并确认终稿），配额 15/15 格全部 2/2，替补议题消解；② #9 cf-1551-d1 维持 standard，判题改为逐题大小写不敏感——实现见提交 `98b1372`（`OutputComparison` 契约、`DockerJudge.judge(..., output_comparison=)`、catalog 可选 `checker.json`（缺失=exact，旧 catalog 哈希字节级不变）、`CandidateReview` 可选 `output_comparison` 字段），corrected.json #9 已带机器字段 `output_comparison=case_insensitive`；③ cf-1551-b2 维持多解排除。剩余已知缺口：意图哈希 `HY3_TIMEOUT_SECONDS` 未入 manifest；differential.py 正式语料判题校验仍默认 exact 比较，正式链消费 checker.json 时需扩展。原始清单冻结于外部数据根 `human-review-20260910-v1/`（items_hash `1c88bc6b…2c54`）。
- **三题 MVP 已完成（非正式）**：2026-09-10 以 GA hy3（TokenHub）对 `cf-1613-c`/`cf-1556-b`/`cf-1554-b` 各跑 1 个自然样本，20/20 请求预算用完：前两题完整链路 AC + final_correct=true，cf-1554-b 生成判题 AC 但审查因预算耗尽 partial。两次阻断失败各做一次最小提示词修复（提交 `943bba2`、`837f336`）。工件在外部数据根 `mvp3-20260910-v1/` 与 `mvp3-runs-20260910-v{1,2,3}/`（create-only），报告见 `/Users/odalys/Documents/hy4oi/mvp-report-20260910-v1/`。详见 [三题 MVP 记录](MVP_3PROBLEM_GA_2026-09-10.md)。非正式小样本，不可外推正式准确率。
- 下一步顺序：解决意图哈希 `HY3_TIMEOUT_SECONDS` 缺口（manifest 纳入超时并派生新 intent_hash；differential 判题扩展可同批或另批）→ 以 `review-output-20260910-v1/human-review-checklist.corrected.json` 为输入执行 `create-review-artifact → create-review-set → pin-review-manifest → convert-formal → quota → freeze-selection → verify-selection-chain` → 正式基准（GA hy3，formal=true，`HY3_TIMEOUT_SECONDS=600` 建议，预算 500）→ 报告/演示。单题 smoke 与三题 MVP 均不可外推为正式性能或资格。
