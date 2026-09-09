# 真实数据试运行：2026-09-08

当前代码目录：`/Users/odalys/Documents/hy4oi/.worktrees/integrate-task6-8`。
本轮产物未提交；原始下载文件和本地 `.env` 未修改。

## 已完成

已接通命令行 → 无缓存 Hy3 生成 → Docker Judge → 双审查/必要时仲裁 →
规则融合 → 指标、原始证据与请求账本。每次实际 HTTP 请求（包括重试和修复）
都先占用预算；耗尽时保留 partial report，其他执行失败保留安全标记和账本。
自然生成没有预设人工标签，因此不会凭空产生准确率基准。

独立编写 CF 1613C 的参考代码、六阶段推理轨迹和 oracle，仅依据公开题面。
C++17 编译期检查覆盖 756 个独立枚举小例及三个边界/样例。
这不是 Docker 判题通过或人工认可的证明。

真实外部试运行输入已保存至：
`/Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260908-v1`。

- `catalog/cf-1613-c/`：校验通过的单题完整题包，包含私有测试，仅本地使用。
- `live-inputs.json`：一次自然生成请求，无预设人工真值。
- `config.template.json`：固定题包/输入哈希、提示词版本、high 推理强度，预算 12 次请求。
- `provenance.json`：来源文件哈希、题包哈希、未判题/非正式状态。

模板故意保留真实模型、端点、镜像摘要的待填字段，不能当作已冻结配置运行。
12 次是请求上限而非费用金额；正常无重试、无仲裁时需要三次请求。
没有发出付费模型请求。

## 下一步运行

先让本机 Docker 服务可用，并准备实际 `repository@sha256:...` Judge 镜像。
项目发布运行镜像的依赖证明仍未齐备，不能用占位摘要或宿主机执行替代 Judge。
已有密钥留在环境中；命令不会自动读取 `.env`，也不要把密钥写进配置。
所需变量为 `HY3_BASE_URL`、`HY3_API_KEY`、`HY3_MODEL`、`HY3_JUDGE_IMAGE`。

在上述代码目录，用环境中的真实值创建一个新配置文件：

```bash
.venv/bin/python - <<'PY'
import json, os
from pathlib import Path
from hy3_algotrace.artifacts import ArtifactStore
from hy3_algotrace.benchmark_models import BenchmarkConfig
from hy3_algotrace.hy3_client import endpoint_identity
root = Path('/Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260908-v1')
payload = json.loads((root / 'config.template.json').read_text())
payload['model'] = os.environ['HY3_MODEL']
payload['endpoint_identity'] = endpoint_identity(os.environ['HY3_BASE_URL'])
payload['judge_image_digest'] = os.environ['HY3_JUDGE_IMAGE'].rsplit('@', 1)[1]
config = BenchmarkConfig.model_validate(payload)
ArtifactStore(root).write_json('config.runtime-v1.json', config.model_dump(mode='json'))
PY

.venv/bin/python -m hy3_algotrace.benchmark_cli validate-live-inputs \
  --config /Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260908-v1/config.runtime-v1.json \
  --catalog-root /Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260908-v1/catalog \
  --live-inputs /Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260908-v1/live-inputs.json
```

静态校验成功不代表 Docker 或 API 可用。确认本次模型请求费用后再执行：

```bash
.venv/bin/python -m hy3_algotrace.benchmark_cli run \
  --config /Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260908-v1/config.runtime-v1.json \
  --catalog-root /Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260908-v1/catalog \
  --live-inputs /Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260908-v1/live-inputs.json \
  --artifact-root /Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-runs-20260908-v1
```

启动前检查环境身份和本地固定镜像，不自动拉取镜像。预检/执行失败返回 2；
预算耗尽仍按现有 Runner 约定返回 partial report，请检查 `complete` 字段。
结果只能创建一次；再次运行需新 benchmark_id、新配置文件或新的输出目录。
不得将这一题的结果外推为完整项目性能或正式资格。

## 正式评测的下一项代码任务

除 30 题人工审核外，还存在需要专门设计的生命周期问题：当前正式配置先冻结
完整 corpus_hash，但自然语料的物化又依赖同一运行的生成事件与最终轨迹。
应分开“执行意图冻结”和“运行结果冻结”，明确 sample_id/trace_id 的绑定及
人工标签加入时点，再按共享契约规则决定版本兼容和迁移。不能提前伪造语料哈希，
也不能通过缓存或另一次运行的生成事件绕过正式检查。
新 live 入口明确拒绝 `formal=true`，本轮未修改共享 1.2 契约。

## 续作状态：容器与输入就绪，等待真实 HTTP 确认

本节更新上文的初始环境状态；尚未运行 Hy3 生成或模型审查，不是端到端成功报告。
代码仍在指定集成 worktree，保留全部既有未提交文件，未提交/推送；原始题包、
模板、下载字节和本地 `.env` 均未修改。

### 代码验收

修复了 live CLI 的配置读取与工件写入异常边界：缺失/损坏配置、无效输出目录、
重复运行及失败标记写入冲突均安全返回 2，保留已有字节。共 9 个新增用例先失败
后通过；独立代码审查发现的 P2 已复审关闭。共享 1.2 契约、formal 拒绝策略和
容器专用 Judge 路径保持原语义。

focused tests **186 passed**；完整非 Docker pytest **579 passed, 9 deselected**，
一条既有 Starlette deprecation warning。Ruff、mypy（35 source files）、
release_validation（130 files）和 `git diff --check` 均通过。
详细命令见 `docs/task-live-smoke.md`。

### 实际 Judge 镜像与参考解证据

Docker Desktop daemon **29.2.1** 已启动。宿主机 Docker Hub DNS 曾失败，默认
拉取停在凭据辅助程序；使用临时无凭据 Docker CLI 配置后，daemon 实际完成了
官方公共镜像拉取。没有修改用户 Docker 配置。

使用仓库原有 `docker/judge/Dockerfile`，实际固定构建输入为：

- validator：`debian@sha256:0a5bf4ecacfc050bad0131c8e1401063fd1e8343a418723f6dbd3cd13a7b9e33`
- base：`gcc@sha256:73be6ac66afd77044b33ccfd2219c41fa37388cc561e250a576d633d4479abad`
- `time=1.9-0.2`、`util-linux=2.38.1-5+deb12u3`；GCC 12.5.0，linux/arm64。

构建成功并推送到仅绑定 `127.0.0.1:15088` 的本机 registry，真实 Judge 引用为：

```text
localhost:15088/hy3-algotrace-judge@sha256:47c12489acef3ae4e6e386ae346fc4a830e39a4b1e29dd776e444391fb628db3
```

该引用通过实际 `docker image inspect` 和 DockerJudge 执行验证。容器用户为
`65532:65532`，沿用现有网络禁用、只读根、资源限制与禁用 daemon 日志设置。
CF 1613C 参考解真实编译 AC，4 个 hidden tests + 200 个 generated tests 全部
AC，耗时 **41.297 秒**。这是参考解的容器预检；不等于模型生成结果、人工审查
或正式基准资格。本机 registry 容器及其专用数据卷保留供摘要引用解析使用。

### 新配置与请求确认单

在外部 smoke 根创建了 `config.runtime-v1.json`，内容哈希：
`2c40adc652aaad1ff0c3db00c04784ee2c6efefab04225ba613f645618814810`。
它绑定完整源代码哈希、实际 Judge 摘要和原有题包/输入哈希，`formal=false`。

实际运行上文 `validate-live-inputs` 命令，退出 **0**：
`{"docker_checked":false,"formal":false,"inputs_valid":true}`。
随后装配真实自动 live executor 并单独通过 Docker 预检，但没有调用 executor。

- 模型：`tencent/hy3:free`，`reasoning_effort=high`。
- 端点身份：`https://openrouter.ai/api/v1`；请求路径 `/chat/completions`。
- 仅 `cf-1613-c` 的 `natural-1`，最多 **12 次 HTTP 请求**，包括重试、修复和仲裁；
  无重试/修复/仲裁时通常为生成一次、双审查两次，共三次。
- 2026-09-08 核验的 [OpenRouter 官方模型页面](https://openrouter.ai/tencent/hy3:free)
  标价为输入 **$0/百万 tokens**、输出 **$0/百万 tokens**。这是公开标价，
  尚未验证带凭据的路由可用性；不切换到付费模型。
- 真实模型 HTTP 请求数：**0**。没有请求账本、生成解 verdict 或模型审查结果；
  请求意图不是已执行账本。按用户要求，真实 HTTP 必须等其确认。
- 计划输出：`/Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-runs-20260908-v1`。
  密钥仍只在已有本地文件和临时进程环境中读取，未复制到配置、日志或仓库。
  本次装配将已有 `HY3_API_BASE` 映射到进程内的 `HY3_BASE_URL`，未修改 `.env`。

### 外部 create-only 证据索引

以下路径相对于
`/Users/odalys/Documents/hy4oi-data/codecontests-v1/smoke-20260908-v1/continuation-20260908-v1`，
每份 JSON 均由 ArtifactStore 创建，文件名即内容 SHA-256：

- 质量门：`quality-gates/ea76f30a72c95306df68d10d26038c0071611fef9bb81bc9d6179de3d302f9f6.json`
- Judge 构建日志/输入：`judge-builds/1d896d1a2609cee7540528ac44727344bff8733ce0ea0baaa3f51d19601140fc.json`
- 实际镜像锁：`judge-image-locks/fea3a4435547b064d41e0b941221d4565e7c6b2f296351795b2fd05f665574aa.json`
- 原始参考解 JudgeEvidence：`reference-judge/2d6004c58f1753efc64fd03e8e0b748d8ac816240c4469a437223e359f52ef38.json`
- 静态输入校验：`live-input-validation/7b5a4100e57572d96e24fd2df50a7e1392bd8638e50c57c4fb45524c63d8c6d5.json`
- 请求意图/价格来源：`request-intents/8df445fda99944b2b2c63cf81c364f23a1ab72b9a9264ba6f18743e7662b57f7.json`
- 待确认状态：`readiness/d6ed80b94024becab59abfc17656111527978eb8c8daebf33caaabd084851f1f.json`

## 续作：真实运行已执行并失败（2026-09-08 晚）

本节记录获得用户批准后的真实执行结果。它不是成功报告。

### 执行与失败证据

- `validate-live-inputs` 退出 0：`{"docker_checked":false,"formal":false,"inputs_valid":true}`。
- `benchmark_cli run` 退出 2：`{"formal_eligible":false,"status":"artifact_failed"}`。
- 用带完整 traceback 的复现脚本（输出根目录 `/tmp/live-diag-1`）定位：
  `hy3_algotrace.live_benchmark.LiveExecutionError: live sample failed during generation`。
- 账本 `benchmarks/cf1613c-smoke-20260908-v1/ledger/000001.json` 显示
  `phase=request, retry_number=1`，即**只发出 1 次 HTTP 请求**后失败。
- 样本失败标记 `live-evidence/natural-1/failure.json`：`phase=generation`，
  `formal_eligibility=false`。

### 根因：`tencent/hy3:free` 路由已下线

直接调用 OpenRouter 返回 **HTTP 404**：

```json
{"error":{"message":"This model is unavailable for free. The paid version is available now - use this slug instead: tencent/hy3","code":404}}
```

同日核对 `GET https://openrouter.ai/api/v1/models`（426 个模型），腾讯系仅剩：

| 模型 ID | 输入 / 输出（每百万 token） |
| --- | --- |
| `tencent/hy3` | $0.132 / $0.528 |
| `tencent/hy3-preview` | $0.18 / $0.60 |
| `tencent/hunyuan-a13b-instruct` | $0.14 / $0.57 |

**OpenRouter 上已无任何免费 Hy3 路由**，上文记录的 `$0/$0` 公开标价已失效。

### 决策：改用官方渠道（TokenHub）

用户选择不走 OpenRouter 付费，改接腾讯云 TokenHub。

- 控制台：注册腾讯云账号并开通 TokenHub 服务，在 TokenHub 控制台创建 API Key。
- 接口地址（广州，中国大陆）：`https://tokenhub.tencentmaas.com`；
  备用 `https://tokenhub.tencentmaas.cn`；新加坡 `https://tokenhub-intl.tencentmaas.com`。
- OpenAI 兼容路径：`/v1/chat/completions`，即 base_url 填 `https://tokenhub.tencentmaas.com/v1`。
- 模型 ID：`hy3`（另有 `hy3-preview`）。上下文 256K，最大输出 128K。
- `reasoning_effort` 支持 `no_think` / `low` / `high`，`high` 为深度推理，
  与本项目的 `reasoning_effort=high` 一致，无需改提示词或契约。

### 需要改动的位置

1. `/Users/odalys/Documents/hy4oi/.env`（不进仓库）：
   `HY3_PROVIDER`、`HY3_API_BASE`、`HY3_API_KEY`、`HY3_MODEL` 四项。
   注意客户端实际读取的是 `HY3_BASE_URL` / `HY3_API_KEY` / `HY3_MODEL`
   （见 `hy3_client.Hy3Config.from_env`），`HY3_API_BASE` 需在进程内映射为
   `HY3_BASE_URL`。
2. **重新生成运行时配置**：`config.runtime-v1.json` 绑定了
   `endpoint_identity=https://openrouter.ai/api/v1`，换端点后必须生成新配置
   （如 `config.runtime-v2.json`），题包哈希与输入哈希不变。
3. **输出目录必须换新的**：`smoke-runs-20260908-v1` 内已有 `config.json`，
   工件 create-only，重跑会撞 `ArtifactExistsError`。

### 已知缺口

`HY3_ALLOW_PAID`、`HY3_MAX_PRICE_PROMPT`、`HY3_MAX_PRICE_COMPLETION`
在 `src/` 下没有任何读取点（全仓搜索无匹配）。也就是说"只用免费模型"目前只是
`.env` 里的声明，代码并不执行价格闸门。切换到付费渠道不会被代码拦截，但也
意味着没有自动防超支保护。若需要该约束，应作为独立任务补上。

## 渠道选型：TokenHub 额度与 CodeBuddy CLI 的定位

### TokenHub 不是完全免费，但免费额度够起步

新人免费体验包（活动至 2026-12-31，每主账号每模型一次）中，**赠送 100 万
Tokens / 90 天的是 `hy3-preview`**，官方免费额度表未列 `hy3`。要点：

- 免费额度首次调用时平台自动领取，也可在控制台「模型广场 → 新用户福利
  免费体验」手动勾选。额度用尽后未开后付费则服务停止，不会产生意外账单。
- 按量价（广州区在线推理）：输入约 ¥1/百万、输出约 ¥4/百万。
- 订阅 Hy Token Plan 个人版（仅覆盖 `hy3-preview`）：Lite 3500 万 Tokens
  28 元/月，Standard 1 亿 78 元/月。
- `hy3-preview` 支持 256K 上下文、结构化输出、Function Calling、Cache 缓存，
  `reasoning_effort` 支持 `no_think` / `low` / `high`。

粗算（仅估算，需实测校准）：正式基准约 390 次请求，每次按 6k 输入 + 6k 输出
估 ≈ 470 万 Tokens，按量约 ¥12；high 推理若输出翻倍约 ¥25–30。免费 100 万
Tokens 大约只够 smoke 加 15–30 个样本，不足以支撑完整 165 样本基准。

**禁止开启 Prompt Cache**：`live_benchmark` 刻意用 `cache=None` 构造无缓存
`Hy3Client`，保证自然生成不被复用。开缓存会直接破坏"每次都是真生成"的证据链，
即使能省钱也不能用于正式样本。

### CodeBuddy CLI 不能作为主评测通道

CodeBuddy Code CLI（`codebuddy` / `cbc`）支持 `-p` 非交互与
`--output-format json`，也有 `--model`。但它不适合当基准的模型通道：

- 它是 agent，不是裸推理接口：输出混有系统提示、工具调用与文件上下文，
  评出来的是「Hy3 + CodeBuddy 脚手架」，与赛题要评估的"推理过程"不符。
- 没有 `reasoning_effort` 控制，无法固定 `high`。
- 无法提供可验证的 `endpoint_identity` 与模型身份证明；`BenchmarkConfig`
  哈希绑定端点身份与 `model_parameters`，CLI 调用填不进去，冻结配置链会断。
- 结果不可复现：别人按 README 重跑需要一个 OpenAI 兼容端点，而不是一个
  需要登录的桌面/命令行 agent。

### CodeBuddy CLI 可以并入的三处

1. **开发侧**：用它写这个项目本身的代码，本来就是它的用途，且免费。
2. **离线素材初稿**（性价比最高）：30 题的参考 C++17、gold trace、受控错误
   变体，让 CLI 批量出初稿再由人工审核定稿。人工编写的样本本就不计为模型
   自然生成，不影响正式证据链，但须在 bundle/corpus 中如实声明 authorship。
3. **可选加分章节**：同一批题目对比「裸 API」与「CLI agent」的过程正确率与
   错误定位差异，写成"agent 脚手架对过程评估的影响"。只能作为附加章节，
   不得并入 165 样本主基准。
