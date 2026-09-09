# CF 1613C TokenHub smoke：模型下线阻塞

日期：2026-09-09（Asia/Shanghai）。本次未完成端到端 smoke，不能作为正式性能或资格证据。

## 结论与证据边界

续作检查发现本地已存在当天 TokenHub v1/v2 的配置、执行记录与失败账本。
两次 `validate-live-inputs` 均退出 0，两次 `run` 均退出 2，状态为
`execution_failed`；各有一条生成请求预算记录，失败阶段均为 `generation`。
v2 的 HTTP 诊断明确记录服务端返回 **400 / 400004**：

```text
The model or service ID hy3-preview does not exist.
```

两次运行均没有 `report.json`，因此 **`complete` 字段不存在**，不能记成
`complete=true`，也不是预算耗尽生成的 partial report。未产生生成轨迹、模型解
Docker verdict、双审查、仲裁、融合结果或指标报告。

本次续作核验已有工件，没有再次发送推理请求，仅发送一次带现有凭据的
`GET https://tokenhub.tencentmaas.com/v1/models`。响应为 **200**，共 **124** 个
模型，包含 `hy3`，不包含 `hy3-preview`。账本事件在发送前预留，单凭账本不能
证明服务端收到请求；v2 另有 HTTP 响应证据，v1 仅保留执行状态与预算事件。

[腾讯官方下线公告](https://cloud.tencent.com/announce/detail/2391)明确说明：
TokenHub 的 `hy3-preview` 自 **2026-08-31 00:00（北京时间）**起下线。
[当前 API 文档](https://cloud.tencent.com/document/product/1823/130078)说明
`GET /v1/models` 返回当前可调用模型；这次实际结果与下线公告、v2 错误相符。
免费包领取不会恢复已下线模型。不能通过重新领取额度、重试相同参数或绕过预检修复。

## 运行条件

- 工作树：`/Users/odalys/Documents/hy4oi/.worktrees/integrate-task6-8`。
- 分支：`codex/integrate-task6-8`；被验证代码提交：
  `6adbd0e43f7613a679587ec437f15a3b0b759643`。续作没有修改源码。
- `/Users/odalys/Documents/hy4oi/.env` 的实际白名单值如下，密钥存在且未输出。
  本次未修改 `.env`，未将其加入配置、工件或版本控制。

```text
HY3_PROVIDER=tokenhub
HY3_API_BASE=https://tokenhub.tencentmaas.com/v1
HY3_MODEL=hy3-preview
HY3_ALLOW_PAID=false
HY3_MAX_PRICE_PROMPT=0
HY3_MAX_PRICE_COMPLETION=0
```

用户在被要求领取有效免费包后回复“继续”；续作据此理解免费包前提已满足，
未代领额度、未独立查看账户余额或后付费设置。旧 `runtime-basis.json` 中的
账户确认字段属于当时记录，本次只核对其原始字节，不扩充为控制台实证。

**费用开关的代码读取尚未实现。** `Hy3Config.from_env()` 实际读取
`HY3_BASE_URL`、`HY3_API_KEY`、`HY3_MODEL`；须在临时进程环境中将
`HY3_API_BASE` 映射为 `HY3_BASE_URL`。12 次是 HTTP 尝试预算，并非 tokens
或货币预算，不能把 `.env` 中的零价格上限当成已实现的自动防超支保护。

配置使用完整 URL `https://tokenhub.tencentmaas.com/v1` 作为
`endpoint_identity`；字符串 `tokenhub` 是 provider 名称，不满足现有 URL 契约。
价格依据保存在独立的 `runtime-basis.json`，没有向 `BenchmarkConfig` 加入额外字段。
其中输入 **1.2 元/百万 tokens**、输出 **4 元/百万 tokens**保留为用户指定的
历史 preview 价格依据，来源为 [TokenHub 模型价格文档](https://cloud.tencent.com/document/product/1823/130055)。
2026-09-09 检查该页时已无 preview 独立价格项，不能称其为核实过的当前 preview
实价或实际扣费；也不能用当前 GA `hy3` 的 1/4 价格冒充 preview 价格。

Docker 实查版本为 **29.2.1**，以下固定镜像引用仍可被 `docker image inspect`
解析。本次普通沙盒不能访问 Docker socket，提升权限后的只读检查退出 0。

```text
localhost:15088/hy3-algotrace-judge@sha256:47c12489acef3ae4e6e386ae346fc4a830e39a4b1e29dd776e444391fb628db3
```

镜像可用不代表本次模型解通过判题；生成阶段失败，尚未执行模型解 Judge。
9 月 8 日参考解的容器结果见原 smoke 文档，不能替代本次结果。

## 配置、命令与不可变工件

外部数据根为 `/Users/odalys/Documents/hy4oi-data/codecontests-v1`。
两次 TokenHub 配置均独立于失效的 OpenRouter runtime，仍使用原始
`smoke-20260908-v1/catalog` 与 `smoke-20260908-v1/live-inputs.json`。
两份 runtime 的 model 均为 `hy3-preview`，reasoning_effort 为 `high`，
`formal=false`，预算 12 次；正常无重试、修复、仲裁时预计三次。

| 版本 | benchmark_id | config SHA-256 |
| --- | --- | --- |
| v1 | `cf1613c-smoke-20260909-tokenhub-v1` | `d9327690aa3724a1513a2602ea89b56c6a47343bb95ed1a36978f9dcad2841ce` |
| v2 | `cf1613c-smoke-20260909-tokenhub-v2` | `d038ab50d5e3e5a6f32f365cc705692ade2559165666c2eb0c16fe2d94564082` |

每个版本的配置根为 `smoke-20260909-tokenhub-<版本>`，输出根为
`smoke-runs-20260909-tokenhub-<版本>`。已有运行占用的 ID/目录不可复用。
续作准备新配置时发现 v1 已存在，创建前断言安全停止，没有覆盖；确认模型下线后
也没有创建无意义的第三次推理运行。

以下是 v1 已保存的 CLI 命令；密钥仅通过子进程环境传入，命令参数不含密钥。
运行前环境另有上述 `HY3_BASE_URL` 映射与固定 `HY3_JUDGE_IMAGE`。
**这些命令用于记录已经发生的失败，不应直接重跑已占用的输出目录。**

```bash
.venv/bin/python -m hy3_algotrace.benchmark_cli validate-live-inputs \
  --config /Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260909-tokenhub-v1/config.runtime-tokenhub-v1.json \
  --catalog-root /Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260908-v1/catalog \
  --live-inputs /Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260908-v1/live-inputs.json

.venv/bin/python -m hy3_algotrace.benchmark_cli run \
  --config /Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260909-tokenhub-v1/config.runtime-tokenhub-v1.json \
  --catalog-root /Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260908-v1/catalog \
  --live-inputs /Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260908-v1/live-inputs.json \
  --artifact-root /Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-runs-20260909-tokenhub-v1
```

v1 执行时间为 19:26:54–19:26:55，v2 为 19:28:54–19:28:55（北京时间）。
v2 验证命令将路径版本替换为 v2；执行命令使用只观察响应元数据与异常的包装器
`.venv/bin/python /private/tmp/hy3_smoke_diagnostic_cli.py <v2配置根>/http-diagnostic.json run ...`，
内部仍执行原 `benchmark_cli`，不改变请求、验证器或缓存行为。
准确 argv、起止时间、退出码见各配置根的 `validate-result.json`、`run-result.json`。

续作对 v2 重新执行 `env -u PYTHONPATH .venv/bin/python -m
hy3_algotrace.benchmark_cli validate-live-inputs`（参数为上述原输入及 v2 配置），
退出 0，返回 `inputs_valid=true, formal=false, docker_checked=false`。

证据索引：

- 每个输出根的 `benchmarks/<benchmark_id>/ledger/000001.json`：
  `solution-trace-v1 / request / retry_number=1`；`ledger-index.json` 哈希已核对。
- 每个输出根的 `failure.json` 与 `live-evidence/natural-1/failure.json`
  位于同一 benchmark 子目录，分别标记执行失败与生成阶段失败。
- v2 配置根的 `http-diagnostic.json`：HTTP 400、错误码 400004 与服务 ID 错误。
- `smoke-audit-20260909-v1/model-availability/9a29baff4037dd2981863722882f132e6c01063845a29a8e6dd878aee9d0ee8b.json`：
  本次带凭据 GET 的状态、模型 ID/状态白名单；不保存凭据或请求头。
- `smoke-audit-20260909-v1/reconciliation/0ed346b790ef209cc60247f089b995508869b1a0781dd668a5afd1d06683c396.json`：
  两份 runtime、源代码、输入、账本哈希核验与本次静态重验、质量门结果。

续作核对了两份 runtime 与各自输出 `config.json` 字节一致，账本索引哈希与
连续序号一致，`runtime-basis.json` 记录的源文件及输入文件哈希均未变化。
本次不修改原始数据、既有运行或 `.env`。外部原始证据不进入公开仓库。

## 收尾验证与恢复条件

提交前实际执行：

```bash
env -u PYTHONPATH .venv/bin/pytest tests/test_live_benchmark.py tests/test_benchmark_cli.py tests/test_benchmark.py -q --basetemp=/private/tmp/hy3-smoke-20260909-focused-b7ac
env -u PYTHONPATH .venv/bin/pytest -q --basetemp=/private/tmp/hy3-smoke-20260909-full-b7ac
.venv/bin/ruff check .
.venv/bin/mypy src
env -u PYTHONPATH .venv/bin/python -m hy3_algotrace.release_validation
git diff --check
```

focused：**58 passed**；完整 suite：**579 passed, 9 skipped**，一条既有
Starlette deprecation warning。9 个 Docker 集成用例因沙盒无法访问 daemon
跳过，不能记成通过。Ruff 与 mypy（35 源文件）通过；文档加入后的
release_validation（133 文件）与 `git diff --check` 通过。变更文档及新审计工件
通过现有密钥的精确匹配泄露检查。没有修改源码修复沙盒假失败。

恢复需先由用户确定可用模型及计费条件。当前 `hy3` 在模型列表中，但不能因此
推定有可用免费额度；原 preview 免费 smoke 授权不等同于 GA 付费授权。
获得明确决定后，以新 model/endpoint/价格依据、新 benchmark_id、新目录重新冻结，
依次静态验证和运行，检查真实 report、请求账本与全链路证据。
即使未来单题 smoke 完成，也只能验证链路，不能外推为正式准确率或资格。
