# 三题 MVP 记录：非正式小样本（GA hy3 @ TokenHub）

运行时间：2026-09-10（Asia/Shanghai）｜性质：非正式 MVP（formal=false），小样本链路验证，结果不得外推正式准确率

## 一、范围与决策

- 从已人工审核的 30 题中选 3 题，每题 1 个自然样本：`cf-1613-c`（1200，binary_search，复用 smoke 全套工件）、`cf-1556-b`（1300，construction_simulation）、`cf-1554-b`（1700，greedy）。
- 选题标准：tags→主题唯一且与人工审核主题一致；单一整数输出，无多解/容差/大小写歧义（已知 #9 规避；#2 保持 greedy 未动）。
- 三题 `raw_row_hash` 与人工审核清单（`review-output-20260910-v1/human-review-checklist.corrected.json`）经 Parquet 重算交叉验证一致。
- 未扩充候选、未改正式门槛、未改通用 Judge。生成输入仅题面+公开测试，隐藏测试与 oracle 信息未传给生成模型。

## 二、新增工件（外部数据根 `$HY3_DATA_HOME/codecontests-v1/`）

- `mvp3-20260910-v1/`：三题 catalog（两道新题的 `reference.cpp` 为 AI-authored MVP 参考解，宿主与 Docker 各全量 AC 预检：407/407 与 203+202 全过，重复运行稳定）、`live-inputs.json`、`live-inputs-remaining.json`、三次运行的 `run-result*.json` 与 `http-diagnostic*.json`。
- `mvp3-runs-20260910-v{1,2,3}/`：全部 create-only 保留（含失败轮的 partial、failure.json、ledger）。
- 报告：`$HY3_REPO_HOME/mvp-report-20260910-v1/MVP报告-非正式小样本.md`（含 cf-1556-b 完整样例与三次运行失败账本）。

## 三、运行与结果（预算 20 次，实际 20/20，未超支）

| 题 | 运行 | Judge | 双审查/融合 | 结果 |
| --- | --- | --- | --- | --- |
| cf-1613-c | v2 | AC 204/204 | 一致，final_correct=true，未仲裁 | ✅ 完整 |
| cf-1556-b | v3 | AC 203/203 | 一致，final_correct=true，未仲裁 | ✅ 完整 |
| cf-1554-b | v3 | AC 202/202（生成代码） | 预算耗尽未完成 | ⚠️ partial |

- 成功请求 token 合计：入 50,069 / 出 187,467，牌价估算约 ¥0.80（另有 1 次读超时请求 usage 不可见）。
- 耗时：v1 失败 7.1 分钟（natural-1 审查空 `per_step_reviews`）；v2 22.5 分钟（完成 cf-1613-c 后 cf-1556-b 生成空必填字符串失败）；v3 14.9 分钟（完成 cf-1556-b；cf-1554-b 审查首轮校验失败后预算耗尽）。

## 四、两次阻断失败与最小修复（均已过全量测试+ruff+mypy 后提交）

1. 提交 `943bba2`：schema 修复提示词补「per_step_reviews 非空且逐步覆盖全部步骤」（v1 根因：`sanitize_json_schema` 剥 minItems 后，修复提示词未说明该不变量）。
2. 提交 `837f336`：补「必填字符串不得为空，修复须写出真实内容」（v2 根因：修复提示词的“保留字符串内容”规则使空值被原样保留）。
- 附带修复既有 ruff 违规（`scripts/select_human_review.py` 及其测试）使质量门回绿。9 个 Docker 集成测试错误为环境性（缺构建输入环境变量），与改动无关。

## 五、执行环境注意（沿用）

- WorkBuddy 沙盒拦截 Documents 下 `os.unlink` 且无法访问 Docker socket，真实运行需用户 Terminal 或提权执行；pytest 用 `env -u PYTHONPATH .venv/bin/pytest --basetemp=<新目录>` 复核。
- `HY3_TIMEOUT_SECONDS=600`；Judge 镜像 `localhost:15088/hy3-algotrace-judge@sha256:47c1248…8db3`。
- 所有 benchmark_id（`mvp3-20260910-tokenhub-ga-v{1,2,3}`）已占用不可复用；续跑需新 benchmark_id，预算按总账 20 减已耗计。

## 六、下一轮最值得修复（优先级排序）

1. 审查结构化输出稳定性前移：把非空/逐步覆盖不变量写入首次审查请求提示词，并评估 `HY3_SCHEMA_REPAIR_LIMIT=2` 的预算代价。
2. cf-1554-b 补完：生成代码已判题 AC，仅差双审查+融合，新 benchmark_id 下约 4–6 次请求闭环。
3. 账本补盲：超时/中断请求 usage 不可见，应在账本单列条目使成本核算闭环。

正式流程（人工审核补全 → 资格链 → 30 题/165 样本正式基准）不受本轮影响，仍按 `docs/FORMAL_CORPUS_LIFECYCLE.md` 与 AGENT_HANDOVER.md 既有顺序推进。
