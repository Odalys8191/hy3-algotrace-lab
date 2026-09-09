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
- **30 题人工审核清单已冻结**：规则 `formal-selection-quota-15-cell-v1`（rule_hash `66b3a914…3167`），实现 `scripts/select_human_review.py`（复用 `data_preflight.assign_candidates`，测试 `tests/test_select_human_review.py` 13 例）；产物在外部数据根 `human-review-20260910-v1/`（不进 git），items_hash `1c88bc6b…2c54`，审核七字段留空待人工填写，脚本已按原始 Parquet 重算交叉验证一致。本轮未发起任何模型请求。
- 下一步顺序：人工审核 30 题（先审基础二分/基础图论/中档图论三个余量最小格）→ `create-review-artifact → create-review-set → pin-review-manifest → convert-formal → quota → freeze-selection → verify-selection-chain` → 正式基准（GA hy3，formal=true，`HY3_TIMEOUT_SECONDS=600` 建议，预算 500）→ 报告/演示。单题 smoke 不可外推为正式性能或资格。
