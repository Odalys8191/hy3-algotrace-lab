# 正式付费前工程执行计划

目标：实现逐题 comparison 与两阶段运行身份，制作真实的 30 bundle / 105 本地样本，保留 60 个 natural 身份而无输出，准备可审计的付费运行包。

依据：本轮用户授权、AGENTS.md、QUALIFICATION_CHAIN_2026-09-11.md §7、FORMAL_CORPUS_LIFECYCLE.md。用户已要求持续本地执行；不另设设计确认，不提交 Git。

- [ ] comparison：先运行失败测试，再改 differential/corpus 内部模型；默认 exact，checker 可选引用参加新哈希；资格回放对照 pinned review。测试旧读取和所有不一致拒绝。
- [ ] 生命周期：A 绑定真实 pending corpus、165 身份计划、selection 与完整运行身份；B 绑定实际自然输出、账本与最终 corpus，引用 A。远程入口先验证 A；资格同时验证 A/B。不修改 contracts.py。
- [ ] 来源：保留历史人审模型；为本次项目自编产物增加明确的 agent 来源记录，绑定公开题面与自编生成脚本，无虚构人工审阅。
- [ ] 语料：独立编写 30 参考算法、60 语义 mutant、15 格各一 paradox；公开输入先于实现，完整 Judge 只在本地消费冻结测试矩阵，不输出测试内容。
- [ ] 冻结：新根 prepaid-preparation-20260911-v1，exclusive create；输入快照只读，失败尝试也保留，新版本路径用于修正。
- [ ] 验证：focused、全量非 Docker、ruff、mypy、release validation；固定 Docker 镜像跑集成和 105 项 Judge。所有 Python 使用 env -u PYTHONPATH .venv/bin/python；pytest 新 /private/tmp basetemp。
- [ ] 最后：写中文报告、readiness、真实 hash 与明确剩余付费门槛；源码未提交则以 HEAD + 源码清单哈希标识，绝不假称工作树干净。

边界：资格链/raw/human-review 冻结原件只读；不读取 .env 或 API key，不请求任何计费模型，不启动 benchmark，不 commit/push/delete/reset，不覆盖冻结产物。
