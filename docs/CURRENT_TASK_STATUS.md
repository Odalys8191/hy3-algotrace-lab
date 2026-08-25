# Hy3 AlgoTrace Lab 当前任务完成情况

更新时间：2026-08-25（Asia/Shanghai）

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
2. 校验 30 个 bundle 和全部引用字节、完整 165 样本 corpus 和全部引用字节、恰好 105 个 controlled Judge case、持久化 Judge manifest 与原始 `JudgeEvidence`，并在同一 Python 进程直接调用原始证据回放验证器。
3. 仅在临时选择/Judge 能力仍存在时，校验 Task 6 candidate、config、165 个 observation、按冻结顺序排列的 165 个人工确认标签、ledger index 与每个 ledger event。
4. 重算全部哈希，绑定 selection/corpus/bundle/Judge/benchmark/generation 身份、样本 strata、每个 corpus sample 的精确 problem ID 与 gold 字段，要求账本路径安全唯一且序号连续，并同时执行 config 预算与 500 次硬上限。
5. 完整链通过后，只创建一次 `formal-qualification/<content_hash>.json`。报告只含哈希、计数和尝试次数（benchmark ID 也只保留哈希），不含题面、测试、oracle、源码、原始 Judge 证据、诊断、反例、凭据、原始身份或 endpoint。
6. Task 6 独立 `BenchmarkRunReport.formal_eligible=false` 和 `formal_evidence_verified=false` 语义保持不变，没有 fixture/test-mode 资格旁路。

## 2026-08-25 验证记录

使用集成树现有 Python 3.12.14 `.venv` 执行：

```text
.venv/bin/pytest -q tests/test_formal_qualification.py
18 passed

.venv/bin/pytest -q -m "not docker_integration"
483 passed, 9 deselected, 1 Starlette deprecation warning

.venv/bin/ruff check .
All checks passed!

.venv/bin/mypy src
Success: no issues found in 33 source files

.venv/bin/python -m hy3_algotrace.release_validation --root .
release validation passed (119 files checked)
```

新增负向覆盖包括：缺失文件、工件篡改、伪造 receipt、Judge case 缺失/重复、原始 JudgeEvidence 不匹配、不完整账本、超过 500 次尝试、observation 缺失、人工标签缺失/不匹配、selection strata 与自然运行身份不匹配、同 strata problem ID 自重哈希调换、报告隐藏数据/凭据/原始 benchmark ID 不泄漏，以及 CLI/readiness/release-gate 退出码传播。CLI 与 shell 均显示“个人活动项目、非腾讯官方发布”声明；Compose 正式服务也具备可由干净环境显式构建的定义。

本轮没有运行或宣称通过：真实 Docker 集成测试、Docker/Compose 构建、外部 CodeContests 数据获取、真实 30 题/165 样本审计、真实 Hy3 调用、正式发布、运行镜像证明或演示录制。

## 下一阶段外部与人工工作

1. 独立获取并固定 validation/test 原始数据，完成 30 题 selection、bundle、30/60/15 项目编写样本与 60 个真实 Hy3 natural 输出。
2. 使用真实受限 Judge 生成并保护 105 个原始 `JudgeEvidence`，保留完整持久化 evidence manifest。
3. 执行 165 样本 live benchmark、人工盲审与确认，保留不超过 500 次的完整连续 ledger。
4. 向正式资格桥提供 README 列出的全部不可变输入，生成新的内容寻址资格报告；随后完成结果报告、可取得的运行镜像证明、真实 Docker 验收与两分钟以内演示。
