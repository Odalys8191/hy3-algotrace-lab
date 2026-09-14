# cf-1553-d 比较语义待人工确认

状态：**R007 已取得真人补充决定并在新版本链中完成验证**。旧人工原件、旧资格链、旧 checker 与全部失败证据保持只读。

公开题面允许答案字母任意大小写。当前冻结记录的不同测试组使用不同大小写风格，冻结人工审核却仍为 `exact`。真实 Docker 完整矩阵中，同一正确参考程序得到30 AC、200 WA；这不是放宽算法要求即可解决的问题。不能按测试来源选择输出大小写，也不能由 agent 将人工记录改成已批准。

另行执行的本地 C++17 根因诊断覆盖该题全部230项测试：exact匹配30项、casefold匹配230项。该诊断只保存汇总、源码和完整记录哈希，明确 `is_docker_evidence=false`、`checker_modified=false`、`human_review_modified=false`，不替代正式矩阵证据。没有发现同字节输入的输出冲突重复项，因此这里不声称同输入在数学上不可满足。

建议人工确认的唯一字段是 cf-1553-d 的 `output_comparison`：由当前缺省的 `exact` 改为 `case_insensitive`。主题、难度、选题集合、标准 stdin/stdout checker 类型及其他人工值不变。

用户于 `2026-09-13` 明确回复：`批准；reviewer=odalys；reviewed_at=2026-09-13T22:10:00+08:00`。该原文已保存到新的只读补充决定目录 `review-output-20260913-v1`；没有沿用旧审核时间、代签或扩大授权到付费实验。

R007 在新的 create-only 目录重放了完整资格链：30 份 review artifact、13/17 validation/test 拆分、15 个配额格及 30 题集合不变，只有 cf-1553-d 的 review hash / checker 比较语义发生变化。新 selection 内部 hash 为 `7e11a827b3ca8adc5a8e87f3a7e4740701792034986b7dab9f8ca887c54004c0`；旧链保持只读。

新 v6 authored corpus 的 sample manifest、105 份源码、公开 trace 与受保护测试记录逐字节核对不变；只有 cf-1553-d bundle 的 checker 和 selection 绑定改变。绑定新 selection 的 cf-1553-d 四个受影响样本已用固定 Judge 镜像完整新跑 920 项测试：gold/paradox 各 230 AC，两个 controlled_wrong 分别为 150 AC/80 WA 与 180 AC/50 WA，基础设施错误为 0。随后以这 4 份新证据和 101 份逐 hash 核验的未受影响证据组成 105 样本/22839 测试的权威 `judge-v3/evidence-index.json`，按类别 105/105 通过。

这只解决 P1 本地受控语料与 Judge 阻塞；`natural_generated=0`、`formal_eligibility=false`，未冻结 A，未调用 Hy3、未运行付费 benchmark 或正式发布。旧 exact 下 gold/paradox 各 30 AC/200 WA、R007 的 create-only 失败尝试及此前偶发 OLE 失败全部保留，不能据此声称偶发 OLE 根因已解决。
