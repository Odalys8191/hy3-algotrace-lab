# CF 1613C TokenHub GA hy3 smoke：端到端链路验证完成

日期：2026-09-09（Asia/Shanghai）。**非正式 smoke（formal=false），仅验证链路，结果不得外推为正式性能或资格。**

## 结论

`cf1613c-smoke-20260909-tokenhub-ga-v5` 完成：`report.json` 的 `complete=true`、
`status=complete`、`execution_kind=live`、`remote_attempts_used=5`。单样本
`natural-1` 依次真实走通：生成 → Docker 判题（**AC，204 个测试全过**）→ 双审查
（逻辑审查含一次超时重试与一次 schema 修复，对抗审查一次通过）→ 无需仲裁 →
规则融合 → 指标账本与 report。这是本项目第一次完整真实链路运行。

GA 累计真实请求：v1=3、v2=4、v3=0、v4=5、v5=5，共 17 次；另有 15 次端点行为
隔离探针（不计入 benchmark 账本）。按牌价估算总花费在 ¥1 以内。

## 失败尝试与根因

| 版本 | 请求 | 结果 | 根因 |
| --- | --- | --- | --- |
| ga-v1 | 3 | 生成阶段读超时 | 硬编码 60 秒读超时不足（修复：`1f20f0f`，`HY3_TIMEOUT_SECONDS` 可配置） |
| ga-v2 | 4 | review 阶段 schema 失败 | 根因被 `from None` 隐藏，增强诊断包装器捕获（见下两行） |
| ga-v3 | 0 | `artifact_failed` | 执行环境沙盒拦截 `os.unlink(dir_fd)`，工件原子发布失败；无费用 |
| ga-v4 | 5 | review 语义校验失败 | 同 ga-v2：模型修复一个跨字段违规后引入另一个 |
| ga-v5 | 5 | **complete** | — |

两个端点缺陷被探针隔离确认（15 次最小请求，变量隔离）：

1. **TokenHub hy3 的 `json_schema` 受限解码在 schema 含 `minLength` 时破坏字符串内换行**（表现为删除、改写为字面量 `n` 或空格；`const`、`enum`、`$ref`/`$defs`、嵌套数组均不受影响）。pydantic 为每个 `Field(min_length=1)` 生成 `minLength`，因此 v2/v4 全部字符串字段被殃及，代码挤成一行、判题 `compile_error`。修复：`e825980`，客户端发送前剥离非结构性验证关键字，长度/数值约束仍由客户端 pydantic 校验（fail-closed 不变）。
2. **模型修复 JSON 时只修报告的违规、引入新的跨字段违规**（如 material_error=true 但 first_error_step 不在 material-erroneous 集合）。修复：`03c1366`，repair prompt 显式列出全部跨字段不变量并要求整体复查。

ga-v5 中该修复链按设计工作：逻辑审查响应 `explanation` 为空串（旧 grammar 的
minLength 本应保证），客户端 pydantic 拒收 → schema repair 一次修复成功。

## 运行条件

- 工作树：`/Users/odalys/Documents/hy4oi/.worktrees/integrate-task6-8`（分支
  `codex/integrate-task6-8`），被验证代码提交 `03c1366`（含 `1f20f0f`、`e825980`）。
- `.env`（GA 值，密钥仅从环境读取，未落盘）：`HY3_PROVIDER=tokenhub`、
  `HY3_API_BASE=https://tokenhub.tencentmaas.com/v1`、`HY3_MODEL=hy3`、
  `HY3_ALLOW_PAID=true`、价格上限 1/4（元/百万 tokens）。
- 进程环境覆盖：`HY3_BASE_URL`（映射自 `HY3_API_BASE`）、`HY3_TIMEOUT_SECONDS=600`、
  `HY3_JUDGE_IMAGE=localhost:15088/hy3-algotrace-judge@sha256:47c12489acef3ae4e6e386ae346fc4a830e39a4b1e29dd776e444391fb628db3`。
- Docker 29.2.1；固定判题镜像 digest 与上述引用一致。
- 配置根 `smoke-20260909-tokenhub-ga-v5`、输出根 `smoke-runs-20260909-tokenhub-ga-v5`，
  复用 `smoke-20260908-v1` 的 catalog 与 live-inputs。`runtime-basis.json` 记录了
  输入哈希、config SHA-256、先前尝试与探针消耗。

## 命令（已执行，勿重跑已占用目录）

```bash
cd /Users/odalys/Documents/hy4oi/.worktrees/integrate-task6-8
set -a && source /Users/odalys/Documents/hy4oi/.env && set +a

# 1) 生成 v5 配置与 runtime-basis（脚本断言工作树干净、config 未占用）
env -u PYTHONPATH HY3_BASE_URL="$HY3_API_BASE" .venv/bin/python /private/tmp/hy3_smoke_v5_prepare.py

# 2) 静态校验（输出 inputs_valid=true, formal=false）
env -u PYTHONPATH HY3_BASE_URL="$HY3_API_BASE" .venv/bin/python -m hy3_algotrace.benchmark_cli validate-live-inputs \
  --config /Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260909-tokenhub-ga-v5/config.runtime-tokenhub-ga-v5.json \
  --catalog-root /Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260908-v1/catalog \
  --live-inputs /Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260908-v1/live-inputs.json

# 3) 真实运行（诊断包装器经 subprocess 执行 benchmark_cli run，用户 Terminal 执行）
env -u PYTHONPATH HY3_BASE_URL="$HY3_API_BASE" HY3_API_KEY="$HY3_API_KEY" HY3_MODEL="$HY3_MODEL" \
  HY3_TIMEOUT_SECONDS=600 HY3_JUDGE_IMAGE="localhost:15088/hy3-algotrace-judge@sha256:47c12489..." \
  .venv/bin/python /private/tmp/hy3_smoke_v5_runner.py
```

真实运行在本机 Terminal 执行（WorkBuddy 沙盒拦截 Documents 下 `os.unlink`
且无法访问 Docker socket；后台任务无法存活命令边界——这些是环境约束，非代码缺陷）。

## v5 结果要点

- 执行时间：2026-09-09 22:59:41 – 23:15:32（北京时间），约 16 分钟，退出码 0。
- 账本 5 条：`solution-trace-v1`（生成，一次过）→ `logic-dependency-review-v1`
  重试 2 次（首次读超时；第二次响应 `explanation` 空串被 pydantic 拒收，触发
  `schema_repair` 一次成功）→ `adversarial-review-v1` 一次过。
- token 用量（成功请求）：输入 9,380、输出 29,091，牌价约 **¥0.13**（超时重试的
  服务端计费未知，未计入）。
- 判题：`compile=ac`、`verdict=ac`、204 个测试全过；生成代码 40 行、换行正常。
- 审查结论：`final_correct=true`，无 material error，未触发仲裁；
  `arbitration_used=false`。
- 工件齐备：`report.json`（10 个工件哈希索引）、`metrics.json`、
  `confidence-intervals.json`、`breakpoint.json`、`charts/*`、`ledger-index.json`、
  `observations/natural-1.json`、`live-evidence/natural-1/{trace,judge,result}.json`、
  配置根 `http-diagnostic.json`、`run-result.json`。

## 证据边界

- 单题、单样本、非正式：不构成准确率、错误分布或任何正式资格证据。
- 正式基准（165 样本，formal=true，GA hy3）前建议：保留 `HY3_TIMEOUT_SECONDS=600`
  （高推理单次响应可超 300 秒）；schema 已由客户端净化，若 TokenHub 修复
  grammar 行为可再评估恢复完整 schema。
- 本次不修改原始数据文件与既有失败运行；外部原始证据不进入公开仓库。
