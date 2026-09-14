# P1 真实本地语料与 Docker 验证记录（R004）

R004 完成了真实构建与完整执行，收尾候选有 98/105 个样本通过 Judge 校验；R006 修复运行时截止竞态后达到 103/105；R007 取得真人补充决定并完成新版本链后，**P1-1/P1-2 已按 105/105 受控样本验收**。没有正式 165 样本 benchmark、natural、A/B 或正式发布结果；持续状态以根目录唯一 TODO.md 为准。

## R006 后续：运行时截止竞态已修复，当前 103/105

R006 保留了上述 R004 全部失败与 partial，并在新的 create-only 目录继续验证。保存的 22,944 份旧进程 metadata（22,839 次测试加 105 次编译）显示：`timed_out=true` 只出现在五个阻塞样本，共 13 次，且全部是容器最终正常 `exit 0`；宿主在 deadline 分支先尝试 kill，之后才确认 `docker start --attach` 是否已经结束。新增确定性回归先观察到“已退出 attach 被事后标成 timeout”失败，再把 deadline 分支改为仅在 `process.poll() is None` 时停止进程。1 秒测试时限、CID-only kill、inspect/cleanup 与 metadata 一致性检查均未放宽。

- 新源码身份（`src/`、`scripts/`、`docker/`、`pyproject.toml`）：`1fce8b404cf90b94ba209d4bd6cd090bbb65f9d9254f22d31b37fbe5ae36b319`。相对 v5/judge-v3 另含 R004 后期 ArtifactStore 枚举竞态修正；组合器逐 AST 核对 Judge 使用的三个 artifact hash 函数未变，并明确记录两项源码差异。
- `runtime-conflict-diagnostic-v2` 对五个受影响样本完整新跑 1062/1062 测试：四个 mutant 均编译 AC 且分别触发 102、206、127、97 个 WA；`cf-1556-b-paradox` 为 203/203 AC；基础设施错误为 0。结果 hash `cfe9a1d5a973d367bfec71038501edf8776b6357cb77fb1f268fcec9594b2d92`，明确 `formal_eligibility=false`。
- `judge-v6/evidence-index.json` 用 `samples` 标准键记录 5 份完整新证据与 100 份未进入被修改 deadline 分支的逐 hash 引用，覆盖 105 样本/22839 测试；当前 103/105 通过，仅 `cf-1553-d-gold` 与 `cf-1553-d-paradox` 因既有 exact/case-insensitive 人工决定冲突失败。索引 hash `98cf78b7e6c6b52fdeefa973babefdad180ced51135ea29305b9c77b4595ab9a`，仍非 formal，不冒充新源码下 105 份全新执行。
- `judge-v4` 在发现未预期的 ArtifactStore 源码差异后停止，仅留下 composer/source/probe；`judge-v5` 完成相同组合但误用非标准顶层键 `rows`。两者均原样保留并由 judge-v6 的 `supersedes` 说明，不作为当前索引。
- 固定 Debian 原 digest 已在本机，但 BuildKit 仍会访问 Docker Hub metadata 并稳定触发 120 秒超时。R006 将该已核验镜像以新标签推入仅本机 `localhost:15088` registry，回读后使用不可变单平台 manifest `localhost:15088/hy3-algotrace-validator@sha256:ed0ea7221f9bbc142d5f33e37bc4d4cff1032abbb459059c97e0d0b44c523cf3`；原失败测试在该输入下 1 passed（123.46s）。这只是本地构建输入修复，未替换运行 Judge 镜像 digest。

R006 仍未取得 cf-1553-d 的真人补充决定，原人工文件、qualification 与 raw parquet 未改；P1-1/P1-2、A、natural、付费 benchmark 和正式发布均保持未完成。后续最终门禁与本轮 Docker 9 项完整复核以唯一 TODO 的 R006 记录为准。

## R007 后续：真人比较决定与 105/105 验收

用户明确批准将 `cf-1553-d.output_comparison` 从 `exact` 改为 `case_insensitive`，真实字段为 reviewer `odalys`、`reviewed_at=2026-09-13T22:10:00+08:00`。决定原文保存于新的 `review-output-20260913-v1`；旧人工原件、旧 qualification、raw parquet、v4/v5/v6 Judge 证据及全部失败工件保持只读。

- 新资格链：`qualification-20260913-v2`。30 份 review artifact、13/17 validation/test 拆分、15 个配额格与题目集合不变；比较 override 仅有原 cf-1551-d1 和本次 cf-1553-d。review manifest hash `4a68233e293ab7174fd7358deeae7fffa48e5ae0788cf1b89785b6d5cd929418`，selection 内部 hash `7e11a827b3ca8adc5a8e87f3a7e4740701792034986b7dab9f8ca887c54004c0`，链证据 hash `a603c5970f43bb314ab5bcb27dac023f9216fbc1f2c8c393bf8fa128b445ca5f`。
- 新语料：`prepaid-preparation-20260913-v6/authored-v1`。30 bundle、105 controlled、60 natural 身份预留且生成数为 0；bundle hash `dfe1af47cc06512f75eec54ba36eba5f58865376ce5a157ca2bd2022acf9e3ee`，pending corpus hash `0002f46df3c5b9d23cd65a6ac27fb11b40b08c5d27a70c59c3b586f3b54ea482`。v5→v6 独立差异审计确认 105 份 sample manifest、源码、公开 trace、私有 record 均不变；只有 cf-1553-d review/checker/selection 绑定改变，审计 hash `4af6200f05c48cf459f302e4fd07e759567b0f4db708662adaa759f98d05ba24`。
- 受影响新执行：`cf1553d-comparison-rerun-v2` 在固定 Judge 镜像下新跑 4 样本/920 测试，源码身份开始和结束均为 `1fce8b404cf90b94ba209d4bd6cd090bbb65f9d9254f22d31b37fbe5ae36b319`。gold/paradox 各 230 AC；wrong-1 为 150 AC/80 WA，wrong-2 为 180 AC/50 WA；基础设施错误 0，结果 hash `d89c4ffb6978f0886c62ac0548140838149c78fd71501d6643499cf9d98e6ced`。
- 权威 105 项证据：`judge-v3/evidence-index.json` 由 4 份新执行和 101 份逐 hash 复核的未受影响证据构成，覆盖 105 样本/22839 测试，按类别 105/105 通过，失败列表为空。索引 hash `f133e15e06e6198185f1144a0c515c4c706f2aaccee970e2475a78301a8ca902`，manifest hash `d94d30e94ce61e919c1e8d7906e96337e6c4d737dd1ef3b16bbf2bbb5e0b8849`；独立复核 hash `1ae09bcef8c1568b5850ccfe4b1e3c09531fd5b788dbdbdb164e9a6b4e38e2dd`。这是诚实的影响边界引用，不冒充新源码下 105 份全新执行。
- R007 最终质量：focused 298 passed；完整非 Docker 721 passed/9 deselected/1 warning；CI 指定格式、Ruff、mypy、release validation、`git diff --check` 全部通过。固定本地 validator/base 镜像的 Docker 集成为 9 passed/721 deselected/1 warning。质量清单 hash `905da7787066cb1d700256d82cd1609d522fe4441405a0c857826247f7c3c856`，Docker 门 hash `3d092f22158b4230869c4e918d59aee91a680c1a67f7af4756391ab7789848d5`。

R007 保留了四类 create-only 失败：资格链 v1 的严格 Pydantic 构造错误、cf1553d rerun-v1 的 Docker socket 权限失败、judge-v1 的 tuple/list 构造错误、judge-v2 的嵌套 enum 构造错误；均由新目录中的成功版本显式取代而没有覆盖。此前 Docker 集成曾出现 8 passed/1 偶发 OLE metadata 失败，公开 OLE 30/30 与五轮完整 verdict 顺序 35/35 未复现；本轮 9/9 通过不构成根因解决声明。

R007 没有读取 `.env`/API key，没有调用 Hy3、生成 natural、运行付费 benchmark、正式 release gate 或正式发布，也没有冻结 A。所有受控语料和 Judge 产物仍明确 `formal_eligibility=false`。

## 真实输入、产物与身份

数据根：`$HY3_DATA_HOME/codecontests-v1`。当前已验收受控候选：`$HY3_DATA_HOME/codecontests-v1/prepaid-preparation-20260913-v6/authored-v1`；下面未特别标注 R007 的内容保留为 R004/R006 历史。

- 从只读 `qualification-20260911-v1/selection/conversion-{validation,test}.json` 取完整 ProblemRecord；原 review-artifacts 提供 CandidateReviewArtifact。逐题核对 record/review/raw-row hash 与人工值一致性，两份 raw parquet 字节哈希通过核对。没有把 public authoring-inputs 当完整记录，也没有重跑或修改冻结选题链。
- selection：`add81f90ac03ae2e1664c798cce55a25e20ffb96d318700028a11c4c471d5d4a`。
- 真实 30 bundle、30 gold、60 controlled_wrong、15 paradox；15 个配额格各 1 paradox。natural-reservations.json 只有 60 个身份，generated_count=0，不是 A。
- bundle：`aa471963ea18d0db8a1be8cc423cbd809111d1447630e5a7631b20ab39535ed6`。
- pending corpus：`b5f83c7143daa3f673820ee558f2fc810c3f36c9cd95e529200c0de884bc6fad`。
- HEAD：`f3e81b471f014ee63ff0441bba5a1bf659e5a736`，dirty；既有工作保留，无 commit/push/merge。
- 构建及 Judge 阶段 source hash：`f50a387ee83ed3d5df21ab00a2d011f0bb95af032bc41a37d6f7a3bbf5ee9b03`，117 份来源在 v5/source-snapshot。
- 最终质量修正后的 source hash：`fa454c236ac85145019bf53ccaf9d1571de8bb3edaa2c49746606298f81ea22d`，117 份来源在 v5/quality-v2/source-snapshot。两者不同：后者修复 ArtifactStore 临时文件枚举竞态并增加测试。DockerJudge、differential、contracts 字节及三个 canonical/hash 函数 AST 未变；**没有在该整体源码身份上重跑 Docker 矩阵**，不能将两个身份混写。A 未冻结。

## 逐题审查与先失败后修正

两份规格的 30 题参考算法、证明前提、时间/空间复杂度、60 个 mutant 和错误标注均逐题审查。记录为 agent review，不是独立人工签署。v5/logs/specification-review.json hash：`880d131c6b8c751a47125f3e645256d16faa4f527f26b524f386217668d8cc16`。

本轮修正均有先运行的失败测试：

1. 构建器原按 steps 位置贴阶段标签；改成包含真实算法、证明、复杂度等内容的六个明确阶段。
2. cf-1608-d 漏减计数 mutant 标签由 proof_gap_circularity 改为 algorithm_logic。
3. cf-1620-d 原第二 mutant 在公开 255 个非空小价格子集上未与独立暴力区分；替换为漏掉整除条件，参考解与暴力匹配，两个 mutant 均有公开语义反例。
4. cf-1553-b 参考源码拼写不符冻结公开样例；依据公开样例修正 Yes/No，人工 exact checker 未变。v4 gold 与 paradox 均实际 201/201 AC。
5. cf-1549-c-wrong-2 在 v4 全部 205 测试 AC；公开无边图回归先失败后替换为错误初始计数。v5 完整重跑 **205 WA**。
6. cf-1575-l-wrong-1 在 v4 全部 202 测试 AC；公开不可达固定点单元素回归先失败后替换为错误正下界。v5 完整重跑 **199 WA、3 AC**。
7. 最终非 Docker 全量暴露并发测试 FAILED：list_json 在过滤非 JSON 临时文件前 stat，竞争写入者可删除该临时文件。确定性回归先 1 failed/1 passed；先过滤临时文件后相关 41 passed，已发布 JSON 消失仍抛错，没有放宽完整性检查。

v4 的 30 参考解/47 组公开样例 native 诊断、60 mutant 编译及 55 个公开样例反例、另 5 个自编公开约束反例均另存为诊断，不计为正式 Docker 结果。v5 的两个替换回归另有独立记录。

v5/logs/specification-review-outcomes.json 把 105 份源码、trace、first_error_step_id、taxonomy、复杂度和实际 Judge 结果逐项对齐，绑定检查全部通过，15 格各一 paradox；Judge 结果未全通过。hash：`09c594f00eeec834a1b0304f6555d33c8a9ebd978377048a81199b57dbc41e0e`。

## Docker 实际结果

daemon 29.2.1。固定镜像及 inspect digest 均核对：
`localhost:15088/hy3-algotrace-judge@sha256:47c12489acef3ae4e6e386ae346fc4a830e39a4b1e29dd776e444391fb628db3`。

- Docker 集成第三轮 9 passed（29.68s，715 deselected 是当时收集数）。前两轮失败保留，见下文。
- 最终源码再次运行 Docker 集成：**8 passed、1 failed、720 deselected（252.95s）**。固定输入校验负例在 input-validator 构建超过120秒；随后一次30秒有界诊断停在固定 Debian digest 的元数据读取，未到校验器执行阶段。相关 argv、构建输入、日志和诊断在 quality-v2/final-docker-integration.json 与 build-failure-diagnostic.json。该次失败未覆盖较早9 passed，也未被诊断替代为通过。
- **v4/judge-v1 新执行 105/105 样本、22839/22839 hidden+generated 测试，rc=2，94 通过/11 未通过**：2 比较规则冲突，2 旧 mutant 存活，7 样本共 14 项基础设施错误。
- **v5/judge-v3 新执行 9 个完整样本/1949 测试，显式引用 96 份 v4 真实证据**。引用前核对 C++、完整记录、比较规则、Judge 实现、镜像及证据 hash；原基础设施失败和变化源码均重新执行。合计覆盖 105/22839，结果 **98 通过/7 未通过，rc=2**。不能声称 v5 全 105 是新执行。
- 有效 v4 索引：`prepaid-preparation-20260913-v4/judge-v1/evidence-index-v2.json`，hash `b1691917711653bc7e84d60f896f0b1ce4054f497eb1509aa4413e072e7f8507`。
- 当前 v5 索引：`prepaid-preparation-20260913-v5/judge-v3/evidence-index.json`，hash `9db8f2331c2e86de4506041185ad44ae77c3a7eb1c2762dd8a8e4ae2d4a56c32`。包含原始 evidence、逐测试/metadata 清单哈希、源码、输入、脚本、计划及 Docker 探测绑定；执行期间 source_changes_during_run=[]。
- v5 仍有基础设施错误：cf-1552-d-wrong-1、cf-1556-c-wrong-1、cf-1608-c-wrong-2、cf-1617-c-wrong-1、cf-1556-b-paradox，共 13 项。宿主截止时间触发后，容器正常 exit 0 与 kill/timeout 元数据不一致，现有严格校验正确拒绝。没有放宽限时、信任字段或 contracts。
- 主机两次只读观察分别约 11.6 GiB、8.4 GiB swap 已用；不能据此认定根因。独立 30 次公开空程序诊断全部 AC，未复现异常，也不证明已修复；它不是语料或正式证据。底层调度/挂载 I/O 等延迟来源仍未确定，暂停无条件重试。
- cf-1553-d gold/paradox 均 30 AC、200 WA。公开题面允许忽略大小写，当前冻结比较规则仍 exact。受保护 native 诊断 exact30/casefold230；没有同字节输入冲突重复项，不声称数学不可满足。需真实补充人工决定后另建资格版本，不能由 agent 改 checker 或代签。见 CF1553D_COMPARISON_REVIEW_REQUIRED.md（未批准建议）。

没有写出“全通过”的 formal Judge manifest；上述是失败尝试的真实索引，formal_eligibility=false。原始测试、oracle、反例只留受保护数据根，不在本报告复制。

## 保留的失败历史

- v2 authored-v1 包含旧 cf-1620-d mutant；judge-v1 枚举名称转换失败（未判题），judge-v2 partial 因 mutant 问题停止。
- v3 judge-v1 并发期间有 4 个完整样本、1309 项测试及基础设施错误，已停止保留。随后公开串行 10/10 AC 只提示负载相关；本轮串行也失败，因此不能归因于并发本身。v3 judge-v2 发现 cf-1553-b 拼写后停止保留。
- Docker 集成第一轮 8 passed/1 registry timeout，第二轮 4 passed/5 failed（4 metadata 错误、1 registry timeout）。负例改为 localhost 标签并真正执行 input-validator target，断言校验器执行；第三轮通过。Judge 运行时生产代码未放宽。
- 独立索引器首次未考虑汇总清理多余 counterexample，检查失败；随后路径变量复用导致首份索引引用 metadata。错误 v4/evidence-index.json（hash 0ed80d6a…）保留并由 logs/index-supersession.json 明确废止，不能使用。修正索引独立校验 105 个 raw 路径/hash 后才引用。
- v5 judge-v1 缺索引、judge-v2 因错误索引被 Pydantic 拒绝，均 rc=1、零样本执行；失败日志和 manifest 保留。judge-v3 才实际重跑九个样本。
- 第一轮最终质量全量：1 failed、717 passed、9 deselected（75.67s），并发枚举竞态已以确定性测试修正；旧日志在 v5/logs/final-non-docker.log，旧 final-gates.json 保持失败。

## 最终质量与下一步

最终质量证据在 `$HY3_DATA_HOME/codecontests-v1/prepaid-preparation-20260913-v5/quality-v2`，均为修正后的实际运行：

- focused：297 passed in 55.88s
- 完整非 Docker：720 passed, 9 deselected, 1 warning in 64.24s (0:01:04)
- CI 指定 12 文件格式、Ruff、mypy（38 source files）通过。
- release validation passed (155 files checked)；git diff --check 通过。release validation 是静态检查，正式发布门未运行。
- 最终 Docker 集成未通过（8 passed/1 build timeout）；上述“最终质量通过”仅指列出的非 Docker、静态门。105受控矩阵未在后期ArtifactStore修正后的整体源码身份重跑。
- 当前 Git：17 个已跟踪修改、14 个未跟踪条目，保留全部既有工作。共享 contracts.py 与 HEAD 无差异。

原始命令 argv、日志和 hash 在 quality-v2/final-gates.json；准备、判题、检查脚本及本轮日志另存 logs/retained-r004-*。所有 Python 顶层命令均使用 `env -u PYTHONPATH .venv/bin/python`，pytest 使用本轮新的 /private/tmp/hy4oi-r004-20260913-* basetemp。

下一步先处理 cf-1553-d 真实人工补充决定、Docker 期限/退出竞态及固定 Debian 基镜像元数据读取超时；未取得新决定和新版本授权前，原人工文件与 qualification 只读。未完成真实 Judge 验收、运行入口与 mock 稳定前，不冻结 A。本轮未调用 Hy3、读取 .env/API key、生成 natural、运行付费 benchmark、P1 操作包 mock、正式发布门或 Git commit/push/merge；既有 P0 mock 单测属于质量回归。
