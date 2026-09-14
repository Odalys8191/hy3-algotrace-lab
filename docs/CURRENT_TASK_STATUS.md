# Hy3 AlgoTrace Lab 当前状态

更新时间：2026-09-14（Asia/Shanghai）

## 已完成并公开

- FastAPI、HTTP-only Streamlit UI、C++17 Docker Judge、规则检查、双 Reviewer/仲裁、
  首错定位、错误分类、指标、不可变工件、远程 attempt/token/RMB 安全闸门。
- 30 题分层选择与 105 个项目自编受控样本；公开投影含 30 gold、60
  controlled-wrong、15 paradox，不含题面副本、hidden tests 或 oracle。
- 外部保留的受控 Judge 证据覆盖 105 样本/22,839 测试，按类别语义 105/105 通过；
  其中 4 份为受比较规则影响后的新执行，101 份为逐哈希复核复用，`formal=false`。
- 三题 GA `hy3` 非正式 MVP：两题形成完整 Judge + 过程评估结果，第三题 Judge AC 但
  审查前预算耗尽。36 秒脱敏 GIF 已提交。
- 公开评测包、结果摘要、有效性状态与分析报告见根 README 的交付索引。

## 尚未完成

- 60 个 natural 输出和完整 165 样本正式 benchmark；
- 真实人工盲审、定位准确率/误报率、seeded 20% 延迟盲复审；
- 可发布 runtime 镜像 attestation 与完整正式资格门；
- 75 样本 balanced pilot：当前仅 1/75 result，第 2 个样本因 Reviewer repair 仍含未知
  step ID 而 `execution_failed`，不会自动重启或包装成完整结果。

因此当前仓库是可复核的开源研究原型与部分实验交付，不是完成的正式模型基准。

## 最新验证边界

R020 在源码最后变化后记录：非 Docker 747 passed / 9 deselected / 1 warning，Ruff、
mypy（39 个源文件）、release validation（158 files）通过；Docker 曾 8/9 出现历史偶发
OLE，定向 1/1 后第二次完整 9/9。R021 新增公开导出/GIF/报告，最终门以本轮发布记录为准。

机器可读状态：

- [`evaluation/results/current-results.json`](../evaluation/results/current-results.json)
- [`evaluation/validation/status.json`](../evaluation/validation/status.json)
- [`evaluation/materials/manifest.json`](../evaluation/materials/manifest.json)
