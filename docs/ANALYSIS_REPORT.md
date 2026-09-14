# Hy3 AlgoTrace Lab 分析报告

日期：2026-09-14｜状态：非正式、部分完成｜模型：GA `hy3`（TokenHub）

## 1. 研究问题与设计依据

传统代码评测主要回答“程序在测试上是否正确”，但不能区分以下两种情况：

- 答案错误，且推理过程在某个环节已经偏离；
- 答案正确，但证明、复杂度或边界分析存在实质错误。

因此本项目把证据拆为三层，并固定融合优先级：

1. **确定性证据**：schema/身份/步骤覆盖、静态规则、编译与受限执行；
2. **语义证据**：logic reviewer 与 adversarial reviewer 独立检查每个步骤；
3. **争议处理**：两个 Reviewer 的实质签名不一致时才进入 arbiter。

确定性执行证据优先，Reviewer 不能把 WA 改写成 AC；基础设施错误也不能被归为模型的
算法错误。所有远程 attempt 发送前预占预算，结果、partial 和 failure 都按 create-only
方式保存，避免事后覆盖失败记录。

## 2. 推理表示、定位与评分

`SolutionTrace` 把解题过程表示为带依赖边的步骤 DAG，阶段固定为：

| 阶段 | 权重 | 典型检查 |
| --- | ---: | --- |
| problem_understanding | 20 | 是否读对任务、目标与输入输出 |
| algorithm_design | 25 | 算法、状态、转移或贪心选择是否成立 |
| correctness_argument | 20 | 必要性/充分性、归纳或不变量是否闭合 |
| complexity_analysis | 10 | 时间/空间结论是否符合实现与约束 |
| implementation | 10 | 实现是否忠实于算法且无语言级错误 |
| edge_cases | 15 | 边界、溢出、空集与极端规模是否覆盖 |

定位器先收集规则与 Reviewer 给出的实质错误候选，再删除所有存在更早错误祖先的候选，
最后按步骤号选择最早根错误。过程分数从 100 开始，每个受影响阶段只扣一次对应权重；
它是规则化诊断分数，不应解释为概率。

## 3. 错误分类体系

| taxonomy | 含义 | 示例边界 |
| --- | --- | --- |
| `problem_misread` | 误解任务目标或语义 | 把刷新伤害理解为叠加伤害 |
| `constraint_omission` | 漏掉决定算法可行性的约束 | 忽略总输入规模或整数范围 |
| `algorithm_logic` | 核心算法、状态或转移错误 | 错误的二分可行性函数 |
| `proof_gap_circularity` | 证明缺口、循环论证或结论先行 | 代码正确但关键充分性未证明 |
| `complexity_error` | 复杂度判断错误 | 实际二次却声称线性 |
| `boundary_error` | 极端输入、端点、溢出等错误 | 单元素、最大值或 off-by-one |
| `implementation_error` | 算法正确但代码实现偏离 | 索引、类型或更新顺序错误 |
| `hallucination` | 引用不存在的性质、定理或接口 | 虚构题目保证 |
| `format_schema` | 结构化输出不符合契约 | 空必填字段、未知 step ID |

当前公开受控语料的 75 个过程错误标签分布为：`algorithm_logic` 22、
`boundary_error` 20、`proof_gap_circularity` 15、`constraint_omission` 9、
`problem_misread` 8、`implementation_error` 1。其余三类本版语料没有支持度，因此不能从
该分布推断模型在九类上的宏平均能力。

## 4. 分层题集与验证结果

题集按 5 个主题与 3 个 Codeforces rating band 分层，每个单元格 2 题：

- 主题：construction/simulation、greedy、binary search、dynamic programming、graph；
- 难度：1200–1500、1600–1900、2000–2400；
- 30 题均有 gold 与两个 controlled-wrong；每个单元格再选 1 题构造 paradox。

由此得到 30 gold + 60 controlled-wrong + 15 paradox = 105 个项目自编样本。外部保留的
Judge 证据覆盖 22,839 个测试，105/105 均符合类别语义：gold/paradox 代码应 AC；
controlled-wrong 应编译成功且被测试检出。最终索引含 4 份受比较语义影响的重新执行证据
和 101 份逐哈希复核的既有证据，因此是 **impact-bounded reuse**，不是同一最终源码下
105 份全新执行。该结果验证语料与 Judge，不是模型准确率。

## 5. 真实模型结果

### 5.1 三题 MVP

三题均为真实 GA `hy3` 自然输出：

| 题目 | 难度 | Judge | 过程评估 | 状态 |
| --- | --- | --- | --- | --- |
| cf-1613-c | 1200 | AC，204 tests | final=true、process=true、双审查一致 | 完成 |
| cf-1556-b | 1300 | AC，203 tests | final=true、process=true、双审查一致 | 完成 |
| cf-1554-b | 1700 | AC，202 tests | 逻辑审查校验失败后预算耗尽 | partial |

只看两个完成样本，最终答案准确率与过程有效率均为 2/2；但这是极小且按“是否完成”选择
后的分母，不能外推为模型总体能力。第三题证明了 Judge AC 不等于过程评估已经完成。

### 5.2 75 样本 balanced pilot

后续 pilot 在 1/75 个融合结果后失败关闭。第一个受控 gold 样本 cf-1613-c Judge AC、
过程有效，但两个主 Reviewer 有实质分歧，因此调用 arbiter 后才形成结论。第二个
controlled-wrong 样本的 logic review 首次 schema 校验失败，一次 repair 后仍引用未知
step ID；运行保留 1 result、1 failure，并停止在总计 9/220 attempts。

这说明结构化 Reviewer 接口在极小规模上已经出现可靠性临界点：错误不在 C++ 执行，而在
“输出必须绑定精确 step ID 并完整覆盖步骤集合”的协议层。一次 repair 上限能限制预算，
却不能保证吞吐。当前实现已记录白名单诊断和逐 attempt token/RMB 结算，但该失败尚未通过
新身份重新运行验证修复。

## 6. 典型案例

### cf-1556-b：完整成功链

模型把数组映射为奇偶序列，检查偶数/奇数数量差不超过 1，再把有序偶数位置匹配到合法的
交替槽位，以位移绝对值和计算最小相邻交换次数。代码 203/203 AC；9 个步骤均被两个
Reviewer 判定正确，过程分数 100，无需仲裁。这一案例用于仓库 36 秒 GIF。

### cf-1554-b：答案正确，流程未完成

生成代码 202/202 AC，但 Reviewer 输出未通过 schema，修复前共享 attempt 预算耗尽。
因此不能把“代码 AC”补写成“过程正确”，也不能把该样本放入过程正确率分母。这是证据链
分离的直接价值。

### cf-1613-c gold：Reviewer 分歧但可仲裁

在 balanced pilot 中，代码 AC 且最终过程有效，但 logic/adversarial Reviewer 的实质签名
不同。arbiter 选择其中一个已有签名后完成融合。它显示“主审一致率”与“最终正确率”是
不同指标，不能互相代替。

### cf-1613-c wrong-1：协议层失败

logic reviewer repair 后仍给出不属于 trace 的 step ID。系统没有猜测或改写模型输出，
而是保存固定类型的 validation failure 并终止。这保护了定位指标的分母，但也暴露了当前
链路的吞吐瓶颈。

## 7. 有效性验证

定位准确率、within-one 定位率和误报率必须以人工确认的输出标签为基准。当前只有题目
checker/topic 人审和语料标签，没有对模型预测进行盲审，也没有 seeded 20% 延迟盲复审。
因此三项指标分母均为 0、状态为 `not_evaluable`；详见
[`evaluation/validation/status.json`](../evaluation/validation/status.json)。

把受控样本的预设标签直接当作“人工抽检”，或让生成同一报告的 Agent 代签，会产生循环
验证，本项目明确拒绝这两种替代。

## 8. 模型能力边界与临界点

- **难度覆盖不足**：完成的自然样本仅 1200/1300；1700 样本只有 Judge 结果，2000–2400
  没有完成自然样本，无法判断能力随难度下降的位置。
- **统计功效不足**：2 个完成自然样本无法给出可靠置信区间；75 样本 pilot 也只有 1 个
  结果，不能填充正式表格。
- **接口稳定性先于算法能力成为瓶颈**：空必填字段、空 review 列表、未知 step ID 已在
  多轮真实运行中触发失败，说明长结构化输出的合规率是扩展规模前的首要临界点。
- **同模型偏差**：生成与审查均使用同一模型家族，双 Reviewer 的隔离提示不能等同于独立
  人类验证。
- **测试与污染边界**：受控 Judge 可以验证程序行为，但公共题目历史暴露和同源数据污染
  无法通过重跑消除。
- **运行成本与墙钟时间**：静态最小链路是每个 natural 1 次生成 + 2 次审查；repair、重试
  和仲裁会增加请求。历史完整单样本曾用 5 attempts、约 16–30 分钟，不能把理论 3 次
  当作实际吞吐保证。

## 9. 可复现证据索引

- 公开评测包 manifest：`ba71264866bc57651e253e89c7d97b1c27b5bd0a993b066fce987832de6d1bcc`
- 105 样本 Judge 索引文件 SHA-256：`357c53b20bf94d6756a6afba70716429a64b7412ac3185ce78488c7786c348d6`
- cf-1613-c MVP result SHA-256：`8b84ef0f77898fcc096122da1697b3c37c09f95597802aa8e3753abe223f5369`
- cf-1556-b MVP result SHA-256：`0f20d9c1344d2eb0ad57eb432d2679380a93aa53b32f912541f4c90520108a40`
- demo GIF SHA-256：`d830b197e3d2b5651106a9318b05dc5d153a1553dd4583ea2147e8805b034851`

敏感/受保护原始证据不随仓库分发；公开摘要和哈希用于界定本报告所引用的版本，而不是
替代正式资格、第三方审计或人类签名。
