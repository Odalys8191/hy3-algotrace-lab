# Hy3 AlgoTrace Lab 当前任务完成情况

更新时间：2026-09-08（Asia/Shanghai）

## 2026-09-08 真实试运行入口

- 已完成非正式 live CLI 装配、无缓存生成、Docker 判题、审查融合与请求账本。
- 已创建真实 CF 1613C 外部题包和试运行配置模板，原始数据未修改。
- 参考解和六步轨迹已通过契约与编译期检查；未声称 Docker AC 或人工批准。
- 自动试运行与静态校验均屏蔽私有异常内容；预算耗尽保留 partial report。
- 运行条件和可复制命令见 `docs/LIVE_SMOKE_2026-09-08.md`。
- 本轮续作已启动 Docker daemon 29.2.1，并从实际固定基底构建原有 Judge，
  推送至仅绑定本机的 registry；已创建 `config.runtime-v1.json`，
  `validate-live-inputs` 返回 inputs_valid=true。真实参考解 Judge 已运行全部
  204 项测试，编译 AC、verdict AC、204/204 AC（41.297 秒）。
- 两处 live CLI 失败边界缺陷均先复现后修复，独立复审无遗留问题；focused
  tests 186 passed、完整非 Docker pytest 579 passed，Ruff/mypy/发布校验通过。
- 尚未发出真实 Hy3 HTTP 请求；模型、端点、12 次请求上限及官方当前零价格
  已记入外部 request-intent，实际请求仍须用户确认。正式自然语料冻结存在
  生命周期依赖，需下一阶段单独设计，当前适配器拒绝 formal=true。

## 2026-09-07 真实数据推进

- 已找到用户下载的 validation/test Parquet：117/165 题，共 282 题。两份
  原始文件保持在仓库外，未修改，也未提交。
- 发现并修复导入器要求内存字节必须整除 MiB 的真实兼容性缺陷。现在按
  原始字节向下取整 MiB，保持 Judge 分配不超过原始上限；原始行哈希不变。
  共享 1.2 契约未改变，历史已接受的整 MiB 输入结果不变。
- 新增 `python -m hy3_algotrace.data_preflight`，实际生成了 acquisition、
  acquisition-validation、data-preflight、human-review-draft 和 index 工件。
- 282 题中有 84 个结构候选、198 个自动排除；25 个候选触发判题提示，
  59 个未触发。即使只使用未触发提示的候选，仍可匹配出不重复的 30 题，
  满足五主题 × 三难度段 × 每格两题。此结果仅是人工审核前的可行性上界。
- 基础二分、基础图论、中档图论的未触发提示候选各只有两题，优先人工核查。
- 真实审核者身份、审核时间和批准内容保持空缺，没有伪造人工确认，也没有
  创建正式 selection、题包、165 样本或资格报告。
- 最终机器工件位于用户外部数据目录的 `preflight-20260907-v3`，早期 v1/v2
  探索工件保留但不作为最终审核版本。可读材料见
  `docs/DATA_PREFLIGHT_REVIEW_2026-09-07.md`；命令说明见 `data/README.md`。
- 本轮网络无法解析 Hugging Face，未独立取得上游哈希或认证 revision；
  已生成报告明确标记 `publisher_verified=false`，本地校验不冒充来源认证。
- 09-07 时 live 适配器尚未实现；该项已于 09-08 完成，见上方更新。
- Docker Compose CLI 可用，但 daemon 检查没有成功；本轮没有调用 Hy3，
  没有进行 Docker Judge 或付费基准。正式门继续保持 not-ready。

本轮代码与验证证据见 `docs/task-data-preflight.md`。以下为此前集成工作的记录，
其中外部数据获取一项已由上面的实际预检推进，正式数据制作与运行仍未完成。

## 总体结论

Task 6、Task 7、Task 8 已汇总到 `codex/integrate-task6-8`，同进程、失败关闭的正式资格桥及发布接线已完成，并通过 Python 3.12 非 Docker 质量门。当前仍不是可发布、可提交的完整正式成品，因为仓库不包含真实 30 题、165 样本、105 个原始 Judge 证据、真实 Hy3 正式运行、人工确认结果、可取得的发布运行镜像证明或演示录制。

缺少上述外部输入时，`scripts/formal-readiness.sh` 明确返回 not-ready（退出码 3），`scripts/formal-release-gate.sh` 将其转换为发布失败。任何持久化 selection receipt、corpus audit、qualification report 或布尔字段都不能恢复正式资格。

## 分支快照

| 范围 | 分支 | 状态 |
| --- | --- | --- |
| 题面与计划 | `main` | 保持不变；本文件由主工作区未跟踪副本复制后仅在集成树更新 |
| Task 1–5 集成基础 | 已包含于集成树 | 应用、契约、工件、Judge、Hy3、审查、API 基础均保留 |
| Task 6 UI、基准、指标 | 已包含于集成树 | HTTP-only Streamlit、500 次硬预算、不可变账本、165 样本候选与人工标签链 |
| Task 7 数据与语料工具 | 已包含于集成树 | selection/bundle/corpus/Judge 原始证据校验工具完整；正式内容仍需外部获取与人工编写 |
| Task 8 发布、CI、安全 | 已包含于集成树 | README、Compose、CI、安全扫描、发布门与运行锁脚手架完整 |
| Task 6–8 正式资格集成 | `codex/integrate-task6-8` | 同进程桥、CLI、脚本、Compose profile、CI 和文档已接通 |

## 正式资格桥完成内容

1. 从冻结 selection、原始 validation/test 字节、格式、acquisition、独立 review 字节与 manifest 重新生成实时 `VerifiedSelectionChain`，不接受 `SelectionReplayReceipt` 作为能力。
2. 对 corpus manifest 只读取一个不可变快照，以同一 payload 完成解析和 lint；每次后续读取 trace 时都重新核对声明的字节长度和 SHA-256。校验 30 个 bundle 和全部引用字节、完整 165 样本 corpus、按 canonical controlled corpus 顺序编码的恰好 105 个 Judge case/持久化 evidence，以及原始 `JudgeEvidence`。每个正式 Judge case 还必须包含与 `hidden_tests + generated_tests` 完全同序的逐测试证据，并保持逐测试状态、汇总 verdict 与反例暴露一致。
3. 在同一 Python 进程直接调用原始证据回放验证器；临时 Judge 结果必须仍登记在进程本地弱引用能力注册表中，禁止 pickle、浅拷贝、深拷贝或伪造/反序列化对象恢复资格。仅在该能力存在时，解析内容寻址的 60 行 natural materialization，逐行绑定 corpus trace/source、解析后的 trace、真实选题记录、模型可见输入、仓库 generator prompt、模型、无凭据 endpoint、保留 JSON 标量类型与顺序的参数、request/cache identity 和 Task 6 generation attempt event hashes。
4. 重新构造 165 项盲审 export/mapping，验证 165 个 initial decision 与按 seed 固定的延迟 20% 复审、reviewer ID 和带时区且递增的时间戳，重算 replay/agreement，并要求 replay observations/labels 与已验证 benchmark 及 human-label artifact 完全一致。四个输入只能位于 benchmark artifact root 下的 canonical create-only 路径。
5. 重算全部哈希，绑定 selection/corpus/bundle/Judge/benchmark/generation 身份、样本 strata、每个 corpus sample 的精确 problem ID 与 gold 字段；Task 6 与正式桥共享按 sample/operation 排序的 retry/repair 状态机（每阶段重试号从 1 连续、最多 3 次、最多一个置于 request 后的 repair block），并同时执行 config 预算与 500 次硬上限。
6. 完整链通过后，只创建一次 `formal-qualification/<content_hash>.json`。报告只含哈希、计数和尝试次数（benchmark ID 也只保留哈希；natural 与人工链仅保留安全组合哈希），不含题面、测试、oracle、源码、原始 Judge 证据、诊断、反例、凭据、prompt、response、reviewer 原始身份或 endpoint。
7. Task 6 独立 `BenchmarkRunReport.formal_eligible=false` 和 `formal_evidence_verified=false` 语义保持不变，没有 fixture/test-mode 资格旁路。

## 2026-08-26 验证记录

使用集成树现有 Python 3.12.14 `.venv` 执行：

```text
.venv/bin/pytest -q tests/test_formal_qualification.py tests/test_judge.py tests/test_benchmark.py tests/test_dataset_corpus.py tests/test_dataset_differential.py tests/test_local_release_wiring.py tests/test_release_validation.py
198 passed，1 Starlette deprecation warning

.venv/bin/pytest -q tests/test_formal_qualification.py
71 passed

.venv/bin/pytest -q -m "not docker_integration"
538 passed, 9 deselected, 1 Starlette deprecation warning

.venv/bin/ruff check .
All checks passed!

.venv/bin/mypy src
Success: no issues found in 33 source files

.venv/bin/python -m hy3_algotrace.release_validation --root .
release validation passed (118 files checked)

.venv/bin/pytest -q tests/test_release_validation.py tests/test_local_release_wiring.py
65 passed，1 Starlette deprecation warning

scripts/formal-readiness.sh
缺少正式输入时退出 3

scripts/formal-release-gate.sh
将 not-ready 转换为退出 1
```

新增负向覆盖包括：缺失文件/工件篡改、伪造 receipt、Judge case 缺失/重复/换序、持久化 evidence 换序、逐测试 Judge evidence 缺失/重复/换序/未知/NOT_RUN/基础设施失败/汇总不一致/反例暴露不一致、DockerJudge 控制字符替换与 2,048 字符截断后的真实反例回放、原始 JudgeEvidence 不匹配、corpus manifest 与 trace 的确定性读边界替换、natural materialization 未解析或逐行 trace/source/request/input/prompt/参数/event hash 伪造、人工 export/mapping/decision/reviewer/timestamp/replay/path 伪造、人工 batch/decision/replay ID 的绝对路径与 `..` 路径逃逸、canonical 人工工件文件或父目录通过符号链接指向 root 内别名目标、bool/int/float 参数类型替换、Judge 能力 pickle/浅拷贝/深拷贝/伪造、不完整账本、超过 500 次尝试、retry 999、重试号倒序、repair 先于 request、重复 repair、sample/operation block 换序、observation 或人工标签缺失/不匹配、selection strata/自然运行身份/problem ID 不匹配、报告隐藏数据/凭据/原始 benchmark ID 不泄漏，以及缺失嵌套 benchmark 输入时 direct CLI/readiness/release-gate 一致安全返回 2。CLI 与 shell 均显示“个人活动项目、非腾讯官方发布”声明；Compose 正式服务也具备可由干净环境显式构建的定义。

本轮没有运行或宣称通过：真实 Docker 集成测试、Docker/Compose 构建、外部 CodeContests 数据获取、真实 30 题/165 样本审计、真实 Hy3 调用、正式发布、运行镜像证明或演示录制。`scripts/security-scan.sh` 因本机未安装 Gitleaks 按设计退出 69，因此全历史 Gitleaks 扫描也没有被描述为通过；上面的 Python 发布/安全单测与 118 文件发布校验均已实际执行。

## 下一阶段外部与人工工作

1. 独立获取并固定 validation/test 原始数据，完成 30 题 selection、bundle、30/60/15 项目编写样本与 60 个真实 Hy3 natural 输出及其内容寻址 materialization manifest。
2. 使用真实受限 Judge 生成并保护 105 个原始 `JudgeEvidence`，保留完整持久化 evidence manifest。
3. 执行 165 样本 live benchmark、人工盲审与确认，保留 canonical export/mapping/decision/replay 四工件及不超过 500 次的完整连续 ledger。
4. 向正式资格桥提供 README 列出的全部不可变输入，生成新的内容寻址资格报告；随后完成结果报告、可取得的运行镜像证明、真实 Docker 验收与两分钟以内演示。
