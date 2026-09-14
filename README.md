# Hy3 AlgoTrace Lab

> 个人活动实战作品，非腾讯官方发布。

Hy3 AlgoTrace Lab 是一个面向 C++17 算法题的本地、单用户研究原型。它把“答案是否
正确”和“推理过程是否可靠”拆成两条证据链：受限 Docker Judge 验证代码，两个隔离的
Reviewer 检查结构化推理，再按固定优先级融合并定位首个实质错误步骤。

![36 秒真实 MVP 解题与过程评估演示](docs/assets/demo.gif)

该 GIF 来自 GA `hy3` 的真实非正式 MVP 样本 `cf-1556-b`：模型生成结构化解答，C++17
Judge 203/203 AC，双 Reviewer 一致判定过程有效。GIF 只呈现公开摘要，不包含提示词、
凭据、hidden tests 或 oracle。详见[演示说明](docs/demo.md)。

## 当前开源交付

| 交付项 | 位置 | 当前状态 |
| --- | --- | --- |
| 应用源码与过程评估 | [`src/hy3_algotrace/`](src/hy3_algotrace/) | FastAPI、Streamlit、Judge、双审查/仲裁、指标、不可变工件与预算闸门 |
| 环境样例与运行说明 | [`.env.example`](.env.example)、本 README | 凭据只从运行时环境读取；默认仅监听本机 |
| 分层题集与标准答案 | [`evaluation/materials/`](evaluation/materials/) | 5 主题 × 3 难度层 × 每格 2 题，共 30 题；105 个项目自编样本 |
| 答案与过程校验 | [`public_release.py`](src/hy3_algotrace/public_release.py)、[`docker_judge.py`](src/hy3_algotrace/docker_judge.py)、[`evaluator.py`](src/hy3_algotrace/evaluator.py) | 公开包完整性校验、C++17 执行证据、过程评分/定位/分类 |
| 结果与有效性状态 | [`evaluation/results/`](evaluation/results/)、[`evaluation/validation/`](evaluation/validation/) | 受控 Judge 结果完整；真实模型结果为小样本/partial；人工有效性验证尚未完成 |
| 方法与案例分析 | [`docs/ANALYSIS_REPORT.md`](docs/ANALYSIS_REPORT.md) | 方法依据、错误体系、典型案例、能力边界与临界点 |
| ≤2 分钟演示 | [`docs/assets/demo.gif`](docs/assets/demo.gif) | 1280×720、6 帧、36 秒，真实非正式 MVP 结果的脱敏演示 |

## 结果快照（截至 2026-09-14）

这些数字不能混成一个“模型总准确率”：它们的样本来源和证据含义不同。

| 结果集 | 最终答案 | 过程 | 说明 |
| --- | ---: | ---: | --- |
| 105 个受控样本 | 105/105 符合各自类别预期 | 标签完备 | 30 gold、60 controlled-wrong、15 paradox；共 22,839 个 Judge 测试。它验证语料/Judge，不是模型能力准确率 |
| 三题真实自然样本 MVP | 已完成样本 2/2 AC；第 3 个也 202/202 AC | 已完成样本 2/2 有效；第 3 个审查未完成 | `formal=false`，分母极小且有完成样本选择偏倚，不可外推 |
| 75 样本 balanced pilot | 1/75 形成融合结果 | 第 2 个样本在 repair 后仍返回未知 step ID，运行失败关闭 | `formal=false`；总 9/220 attempts，不能称为完整结果 |
| 定位准确率 / 误报率 | 不可计算 | 人工标签分母为 0 | 尚无盲审结果和 20% 延迟复审，项目不会用 fixture 或 Agent 代签补数 |

机器可读分子、分母、哈希与难度分层见
[`evaluation/results/current-results.json`](evaluation/results/current-results.json)。

## 快速开始

要求 Python 3.12。静态检查、单元测试和公开评测包校验不需要 API key、外部数据、
Docker 或网络。

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'

python -m hy3_algotrace.public_release validate --root evaluation/materials
python -m pytest -q -m "not docker_integration"
python -m ruff check .
python -m mypy src
python -m hy3_algotrace.release_validation --root .
scripts/security-scan.sh
```

公开包 validator 会逐项检查 manifest 自哈希、210 个文件的长度/SHA-256、路径边界、
`SolutionTrace` schema，以及 JSON 内嵌代码与对应 `.cpp` 是否一致。标准答案是各题的
`*-gold.cpp` 与 `*-gold.json`；受控错误和 paradox 的首错位置/分类在
[`manifest.json`](evaluation/materials/manifest.json) 中。

## 本地应用运行

先复制占位配置，不要提交真实 `.env`，也不要在命令、日志或录屏中打印密钥：

```sh
cp .env.example .env
# 填入本机可信 catalog、不可变 Judge 镜像和已获授权的模型连接配置
```

源码方式运行 API 和 HTTP-only UI：

```sh
. .venv/bin/activate
set -a; . ./.env; set +a
uvicorn hy3_algotrace.local_app:create_app --factory --host 127.0.0.1 --port 8000
```

另开终端：

```sh
. .venv/bin/activate
HY3_API_BASE_URL=http://127.0.0.1:8000 \
  streamlit run src/hy3_algotrace/streamlit_app.py --server.address 127.0.0.1
```

UI 进程只调用四个公开 HTTP 路由，不能读取 catalog、工件根、Docker socket、hidden
tests、oracle 或凭据。API 拥有这些边界。缺少可信 catalog、模型连接或固定 Judge 镜像时，
应用会失败关闭。

Docker Compose 入口为：

```sh
docker compose --profile ui up --build
```

正式就绪检查使用独立 profile；它只读已冻结输入，缺失或篡改会失败关闭：

```sh
docker compose --profile formal-readiness run --build --rm formal-readiness
```

当前 [`docker/release-runtime-lock.json`](docker/release-runtime-lock.json) 仍是
`registry.invalid` 的发布阻塞 sentinel；在维护者提供可获取、完整 attestation 的 Python
3.12 runtime 镜像前，正式 Docker release gate 应当失败。Docker socket 等同于高权限宿主
访问，只允许受控本地单用户使用，禁止暴露到公网或多租户环境。

## 评测材料结构

公开包不复制 Codeforces 题面；[`manifest.json`](evaluation/materials/manifest.json) 为每题
提供原题链接、主题、难度层和样本 ID。所有答案/轨迹均为项目自编，不包含第三方提交代码。

```text
evaluation/
├── materials/
│   ├── manifest.json        # 30 题、105 样本、标签、路径与 SHA-256
│   └── corpus/
│       ├── gold/            # 30 份参考 C++17 + 标准推理轨迹
│       ├── controlled_wrong/# 60 份可解释错误代码/轨迹
│       └── paradox/         # 15 份答案正确但过程错误的样本
├── results/
│   └── current-results.json
└── validation/
    ├── status.json
    └── manual-audit-template.csv
```

原始 CodeContests Parquet、题面副本、hidden/generated tests、oracle、原始 Judge evidence、
模型请求/响应和人工身份工件保留在仓库外。数据获取、正式资格链和 create-only 生命周期见
[`data/README.md`](data/README.md) 与
[`docs/FORMAL_CORPUS_LIFECYCLE.md`](docs/FORMAL_CORPUS_LIFECYCLE.md)。

## 过程评估方法

每条解答被标准化为六阶段 DAG：题意理解、算法设计、正确性证明、复杂度、实现与边界
条件。过程评估顺序固定为：

1. 先检查结构、身份、步骤覆盖和确定性规则；
2. 编译并在禁网、限时/内存的 C++17 Judge 中执行；
3. 隔离运行 logic reviewer 与 adversarial reviewer；
4. 仅在实质结论不一致时调用 arbiter；
5. 从证据 DAG 中选择没有更早错误祖先的首个实质错误，并按阶段权重计算过程分数。

Judge 的编译/运行失败优先于主观审查；基础设施异常不会伪装成模型错误类型。完整设计、
九类 taxonomy 和案例见[分析报告](docs/ANALYSIS_REPORT.md)。

## 安全、可复现性与许可证

- `HY3_API_KEY` 只存在于进程环境；缓存、账本、报告、截图和 Git 历史不得含凭据。
- 远程 attempt 在发送前预占；partial、预算耗尽和失败工件不可覆盖或改写成成功。
- 正式计划为 30 题/165 样本/最多 500 次远程 attempt，并要求盲审及 seeded 20% 延迟复审；
  当前没有满足这些条件。
- CodeContests/Codeforces 材料和依赖遵循各自许可与条款；本仓库不再分发第三方提交代码或
  Codeforces 题面。详见[归属说明](docs/license-and-attribution.md)。
- 本项目代码采用 [MIT License](LICENSE)。

更多说明：[release security](docs/release-security.md)、
[reproducibility](docs/reproducibility.md)、[有效性状态](evaluation/validation/README.md)。
