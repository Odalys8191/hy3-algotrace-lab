# 真实数据预检与 30 题审核草案（2026-09-07）

个人活动实战作品，非腾讯官方发布。

本报告基于用户提供的真实 Parquet。它是待人工审核的选题草案，不是正式冻结题集。
审核必须判断实际输出是否唯一/可用标准判题、题目主主题是否合理；题面关键词筛查不能替代人工审核。

## 本轮实际结果

- validation：117 题；test：165 题。
- 结构候选：84 题；自动排除：198 题。
- 25 个候选触发多解、交互或误差判题提示；其余 59 个没有触发提示，但仍需审核。
- 不重复题目最大匹配：30/30；未触发提示的候选最大匹配：30/30。
- 人工确认：0；正式资格：false；没有运行 Hy3 或 Docker Judge。
- 导入器已修复字节限制兼容性：256000000 bytes → 244 MiB，512000000 bytes → 488 MiB，向下取整且不修改原始文件。
- 本地哈希只证明当前文件一致性。下载 URL 根据文件名和用户下载上下文记录，未能独立获取上游哈希或认证 revision（当前 DNS 失败）。

## 原始文件身份

| split | 字节数 | SHA-256 |
| --- | ---: | --- |
| validation | 51829044 | `02e8c1ccedae716f1e43cc813fcb7823c3db666ea92638820aba80e8cef451ab` |
| test | 63077400 | `aa426cbdb202bf8703b658bcb31fd1878ca7cfd33ca07d3b703dc94ca6a2b651` |

## 配额与余量

每格要求 2 题。候选数可能跨主题重叠；匹配列已强制同一题只占一个名额。

| 主主题 | 难度段 | 结构候选 | 未触发判题提示 | 匹配 |
| --- | --- | ---: | ---: | ---: |
| 构造/模拟 | 1200-1500 | 12 | 5 | 2/2 |
| 构造/模拟 | 1600-1900 | 13 | 9 | 2/2 |
| 构造/模拟 | 2000-2400 | 17 | 11 | 2/2 |
| 贪心 | 1200-1500 | 12 | 6 | 2/2 |
| 贪心 | 1600-1900 | 11 | 9 | 2/2 |
| 贪心 | 2000-2400 | 14 | 8 | 2/2 |
| 二分 | 1200-1500 | 3 | 2 | 2/2 |
| 二分 | 1600-1900 | 4 | 4 | 2/2 |
| 二分 | 2000-2400 | 8 | 4 | 2/2 |
| 动态规划 | 1200-1500 | 4 | 4 | 2/2 |
| 动态规划 | 1600-1900 | 13 | 12 | 2/2 |
| 动态规划 | 2000-2400 | 17 | 15 | 2/2 |
| 图论 | 1200-1500 | 5 | 2 | 2/2 |
| 图论 | 1600-1900 | 3 | 2 | 2/2 |
| 图论 | 2000-2400 | 6 | 5 | 2/2 |

**优先审核基础二分、基础图论、中档图论：目前未触发提示的候选各只有 2 题。** 若某题判题方式或主主题不合格，需要从风险候选中人工复核替补；无法补足时保持 not-ready，不自动放宽标准。

## 建议审核的 30 题

“标准判题确认”意味着排除交互、special judge、多解输出和浮点容差。主题是按原始标签做的候选分配，尚未被人工确认。

| 题目 | split | rating | 建议主主题 | 其他支持主题 | 标准判题确认 | 主主题确认 |
| --- | --- | ---: | --- | --- | --- | --- |
| [1617_C. Paprika and Permutation](https://codeforces.com/problemset/problem/1617/C) | test | 1300 | 二分 | 贪心 | 待审核 | 待审核 |
| [1613_C. Poisoned Dagger](https://codeforces.com/problemset/problem/1613/C) | test | 1200 | 二分 | — | 待审核 | 待审核 |
| [1622_C. Set or Decrease](https://codeforces.com/problemset/problem/1622/C) | test | 1600 | 二分 | 贪心 | 待审核 | 待审核 |
| [1549_D. Integers Have Friends](https://codeforces.com/problemset/problem/1549/D) | validation | 1800 | 二分 | — | 待审核 | 待审核 |
| [1552_F. Telepanting](https://codeforces.com/problemset/problem/1552/F) | validation | 2200 | 二分 | 动态规划 | 待审核 | 待审核 |
| [1551_E. Fixed Points](https://codeforces.com/problemset/problem/1551/E) | validation | 2000 | 二分 | 动态规划 | 待审核 | 待审核 |
| [1579_C. Ticks](https://codeforces.com/problemset/problem/1579/C) | test | 1500 | 构造/模拟 | 贪心 | 待审核 | 待审核 |
| [1556_B. Take Your Places!](https://codeforces.com/problemset/problem/1556/B) | validation | 1300 | 构造/模拟 | — | 待审核 | 待审核 |
| [1556_C. Compressed Bracket Sequence](https://codeforces.com/problemset/problem/1556/C) | validation | 1800 | 构造/模拟 | — | 待审核 | 待审核 |
| [1551_D1. Domino (easy version)](https://codeforces.com/problemset/problem/1551/D1) | validation | 1700 | 构造/模拟 | — | 待审核 | 待审核 |
| [1575_K. Knitting Batik](https://codeforces.com/problemset/problem/1575/K) | test | 2200 | 构造/模拟 | — | 待审核 | 待审核 |
| [1618_F. Reverse](https://codeforces.com/problemset/problem/1618/F) | test | 2000 | 构造/模拟 | — | 待审核 | 待审核 |
| [1553_B. Reverse String](https://codeforces.com/problemset/problem/1553/B) | validation | 1300 | 动态规划 | 构造/模拟 | 待审核 | 待审核 |
| [1598_C. Delete Two Elements](https://codeforces.com/problemset/problem/1598/C) | test | 1200 | 动态规划 | 构造/模拟 | 待审核 | 待审核 |
| [1557_C. Moamen and XOR](https://codeforces.com/problemset/problem/1557/C) | validation | 1700 | 动态规划 | — | 待审核 | 待审核 |
| [1567_C. Carrying Conundrum](https://codeforces.com/problemset/problem/1567/C) | validation | 1600 | 动态规划 | — | 待审核 | 待审核 |
| [1606_E. Arena](https://codeforces.com/problemset/problem/1606/E) | test | 2100 | 动态规划 | — | 待审核 | 待审核 |
| [1575_L. Longest Array Deconstruction](https://codeforces.com/problemset/problem/1575/L) | test | 2100 | 动态规划 | — | 待审核 | 待审核 |
| [1581_B. Diameter of Graph](https://codeforces.com/problemset/problem/1581/B) | test | 1200 | 图论 | 构造/模拟、贪心 | 待审核 | 待审核 |
| [1549_C. Web of Lies](https://codeforces.com/problemset/problem/1549/C) | validation | 1400 | 图论 | 贪心 | 待审核 | 待审核 |
| [1552_D. Array Differentiation](https://codeforces.com/problemset/problem/1552/D) | validation | 1800 | 图论 | 构造/模拟、动态规划 | 待审核 | 待审核 |
| [1608_C. Game Master](https://codeforces.com/problemset/problem/1608/C) | test | 1700 | 图论 | 贪心、动态规划 | 待审核 | 待审核 |
| [1608_D. Dominoes](https://codeforces.com/problemset/problem/1608/D) | test | 2400 | 图论 | — | 待审核 | 待审核 |
| [1613_E. Crazy Robot](https://codeforces.com/problemset/problem/1613/E) | test | 2000 | 图论 | — | 待审核 | 待审核 |
| [1553_D. Backspace](https://codeforces.com/problemset/problem/1553/D) | validation | 1500 | 贪心 | 动态规划 | 待审核 | 待审核 |
| [1618_D. Array and Operations](https://codeforces.com/problemset/problem/1618/D) | test | 1300 | 贪心 | 动态规划 | 待审核 | 待审核 |
| [1579_E2. Array Optimization by Deque](https://codeforces.com/problemset/problem/1579/E2) | test | 1700 | 贪心 | — | 待审核 | 待审核 |
| [1554_B. Cobb](https://codeforces.com/problemset/problem/1554/B) | validation | 1700 | 贪心 | — | 待审核 | 待审核 |
| [1620_D. Exact Change](https://codeforces.com/problemset/problem/1620/D) | test | 2000 | 贪心 | 构造/模拟 | 待审核 | 待审核 |
| [1618_G. Trader Problem](https://codeforces.com/problemset/problem/1618/G) | test | 2200 | 贪心 | — | 待审核 | 待审核 |

## 备选与判题提示

这些题保留用于替换，不自动判为合格或不合格。所有行仍未人工审核。

| 题目 | rating | 支持主题 | 自动提示 |
| --- | ---: | --- | --- |
| [1551_B2. Wonderful Coloring - 2](https://codeforces.com/problemset/problem/1551/B2) | 1400 | 构造/模拟、贪心、二分 | possible_multiple_answers |
| [1551_D2. Domino (hard version)](https://codeforces.com/problemset/problem/1551/D2) | 2100 | 构造/模拟 | possible_multiple_answers |
| [1551_F. Equidistant Vertices](https://codeforces.com/problemset/problem/1551/F) | 2200 | 动态规划 | 未触发（仍需人工审核） |
| [1552_E. Colors and Intervals](https://codeforces.com/problemset/problem/1552/E) | 2300 | 构造/模拟、贪心 | possible_multiple_answers |
| [1553_E. Permutation Shift](https://codeforces.com/problemset/problem/1553/E) | 2100 | 构造/模拟、图论 | 未触发（仍需人工审核） |
| [1554_D. Diane](https://codeforces.com/problemset/problem/1554/D) | 1800 | 构造/模拟、贪心 | possible_multiple_answers |
| [1555_D. Say No to Palindromes](https://codeforces.com/problemset/problem/1555/D) | 1600 | 构造/模拟、动态规划 | 未触发（仍需人工审核） |
| [1556_D. Take a Guess](https://codeforces.com/problemset/problem/1556/D) | 1800 | 构造/模拟 | possible_interactive |
| [1556_E. Equilibrium](https://codeforces.com/problemset/problem/1556/E) | 2200 | 贪心、动态规划 | 未触发（仍需人工审核） |
| [1557_D. Ezzat and Grid](https://codeforces.com/problemset/problem/1557/D) | 2200 | 贪心、动态规划 | possible_multiple_answers |
| [1559_C. Mocha and Hiking](https://codeforces.com/problemset/problem/1559/C) | 1200 | 构造/模拟、图论 | possible_multiple_answers |
| [1559_D1. Mocha and Diana (Easy Version)](https://codeforces.com/problemset/problem/1559/D1) | 1400 | 构造/模拟、贪心、图论 | possible_multiple_answers |
| [1559_E. Mocha and Stars](https://codeforces.com/problemset/problem/1559/E) | 2200 | 动态规划 | 未触发（仍需人工审核） |
| [1560_D. Make a Power of Two](https://codeforces.com/problemset/problem/1560/D) | 1300 | 贪心 | possible_multiple_answers |
| [1560_F1. Nearest Beautiful Number (easy version)](https://codeforces.com/problemset/problem/1560/F1) | 1900 | 构造/模拟、贪心、二分 | 未触发（仍需人工审核） |
| [1560_F2. Nearest Beautiful Number (hard version)](https://codeforces.com/problemset/problem/1560/F2) | 2100 | 构造/模拟、贪心、动态规划 | 未触发（仍需人工审核） |
| [1561_D1. Up the Strip (simplified version)](https://codeforces.com/problemset/problem/1561/D1) | 1700 | 动态规划 | 未触发（仍需人工审核） |
| [1561_D2. Up the Strip](https://codeforces.com/problemset/problem/1561/D2) | 1900 | 动态规划 | 未触发（仍需人工审核） |
| [1562_C. Rings](https://codeforces.com/problemset/problem/1562/C) | 1500 | 构造/模拟 | possible_multiple_answers |
| [1567_D. Expression Evaluation Error](https://codeforces.com/problemset/problem/1567/D) | 2000 | 构造/模拟、贪心 | possible_multiple_answers |
| [1569_D. Inconvenient Pairs](https://codeforces.com/problemset/problem/1569/D) | 1900 | 构造/模拟、二分 | 未触发（仍需人工审核） |
| [1574_D. The Strongest Build](https://codeforces.com/problemset/problem/1574/D) | 2000 | 构造/模拟、贪心、二分、图论 | possible_multiple_answers |
| [1575_B. Building an Amusement Park](https://codeforces.com/problemset/problem/1575/B) | 2300 | 二分 | possible_tolerance |
| [1575_D. Divisible by Twenty-Five](https://codeforces.com/problemset/problem/1575/D) | 1800 | 动态规划 | 未触发（仍需人工审核） |
| [1575_H. Holiday Wall Ornaments](https://codeforces.com/problemset/problem/1575/H) | 2200 | 动态规划 | 未触发（仍需人工审核） |
| [1579_D. Productive Meeting](https://codeforces.com/problemset/problem/1579/D) | 1400 | 构造/模拟、贪心、图论 | possible_multiple_answers |
| [1580_C. Train Maintenance](https://codeforces.com/problemset/problem/1580/C) | 2200 | 构造/模拟 | 未触发（仍需人工审核） |
| [1582_D. Vupsen, Pupsen and 0](https://codeforces.com/problemset/problem/1582/D) | 1600 | 构造/模拟 | possible_multiple_answers |
| [1582_E. Pchelyonok and Segments](https://codeforces.com/problemset/problem/1582/E) | 2000 | 贪心、二分、动态规划 | 未触发（仍需人工审核） |
| [1582_F1. Korney Korneevich and XOR (easy version)](https://codeforces.com/problemset/problem/1582/F1) | 1800 | 贪心、动态规划 | 未触发（仍需人工审核） |
| [1582_F2. Korney Korneevich and XOR (hard version)](https://codeforces.com/problemset/problem/1582/F2) | 2400 | 贪心、二分、动态规划 | 未触发（仍需人工审核） |
| [1586_C. Omkar and Determination](https://codeforces.com/problemset/problem/1586/C) | 1700 | 构造/模拟、贪心、动态规划 | 未触发（仍需人工审核） |
| [1586_D. Omkar and the Meaning of Life](https://codeforces.com/problemset/problem/1586/D) | 1800 | 构造/模拟、贪心 | possible_interactive |
| [1586_E. Moment of Bloom](https://codeforces.com/problemset/problem/1586/E) | 2200 | 构造/模拟、贪心、图论 | 未触发（仍需人工审核） |
| [1591_E. Frequency Queries](https://codeforces.com/problemset/problem/1591/E) | 2400 | 二分 | possible_multiple_answers |
| [1591_F. Non-equal Neighbours](https://codeforces.com/problemset/problem/1591/F) | 2400 | 动态规划 | 未触发（仍需人工审核） |
| [1594_C. Make Them Equal](https://codeforces.com/problemset/problem/1594/C) | 1200 | 贪心 | possible_multiple_answers |
| [1594_E2. Rubik's Cube Coloring (hard version)](https://codeforces.com/problemset/problem/1594/E2) | 2300 | 构造/模拟、动态规划 | 未触发（仍需人工审核） |
| [1594_F. Ideal Farm](https://codeforces.com/problemset/problem/1594/F) | 2400 | 构造/模拟 | 未触发（仍需人工审核） |
| [1598_E. Staircases](https://codeforces.com/problemset/problem/1598/E) | 2100 | 构造/模拟、动态规划 | 未触发（仍需人工审核） |
| [1598_F. RBS](https://codeforces.com/problemset/problem/1598/F) | 2400 | 二分、动态规划 | possible_multiple_answers |
| [1600_E. Array Game](https://codeforces.com/problemset/problem/1600/E) | 1900 | 贪心 | 未触发（仍需人工审核） |
| [1601_B. Frog Traveler](https://codeforces.com/problemset/problem/1601/B) | 1900 | 动态规划、图论 | possible_multiple_answers |
| [1607_H. Banquet Preparations 2](https://codeforces.com/problemset/problem/1607/H) | 2200 | 贪心 | possible_multiple_answers |
| [1608_B. Build the Permutation](https://codeforces.com/problemset/problem/1608/B) | 1200 | 构造/模拟、贪心 | possible_multiple_answers |
| [1613_D. MEX Sequences](https://codeforces.com/problemset/problem/1613/D) | 1900 | 动态规划 | 未触发（仍需人工审核） |
| [1615_E. Purple Crayon](https://codeforces.com/problemset/problem/1615/E) | 2400 | 贪心、图论 | 未触发（仍需人工审核） |
| [1617_D2. Too Many Impostors (hard version)](https://codeforces.com/problemset/problem/1617/D2) | 2400 | 构造/模拟 | possible_interactive |
| [1619_C. Wrong Addition](https://codeforces.com/problemset/problem/1619/C) | 1200 | 构造/模拟 | possible_multiple_answers |
| [1619_F. Let's Play the Hat?](https://codeforces.com/problemset/problem/1619/F) | 2000 | 构造/模拟、贪心 | possible_multiple_answers |
| [1620_C. BA-String](https://codeforces.com/problemset/problem/1620/C) | 1800 | 构造/模拟、贪心、动态规划 | 未触发（仍需人工审核） |
| [1620_E. Replace the Numbers](https://codeforces.com/problemset/problem/1620/E) | 1900 | 构造/模拟 | 未触发（仍需人工审核） |
| [1620_G. Subsequences Galore](https://codeforces.com/problemset/problem/1620/G) | 2400 | 动态规划 | 未触发（仍需人工审核） |
| [1623_D. Robot Cleaner Revisit](https://codeforces.com/problemset/problem/1623/D) | 2300 | 构造/模拟 | 未触发（仍需人工审核） |

## 审核与后续执行

1. 先审核上面三个余量最小的格子；对每题记录标准判题是否通过及最终主主题。不通过的写明原因。
2. 为确认的记录提供真实审核者标识、带时区的审核时间和题目链接；不要把工具或 AI 的预检当作人工签名。
3. 用原始 Parquet 的 split、row_number 和 raw_row_hash 定位精确原始行，再使用现有 create-review-artifact / create-review-set / pin-review-manifest。草案 JSON 不是这些命令的有效正式输入，需要明确转换并保留真实审核内容。
4. 人工确认 review manifest 的 content_hash 后，用 convert-formal → quota → freeze-selection → verify-selection-chain 生成正式选题。
5. 为少量已确认题编写参考 C++17、gold/oracle/受控错误过程，接通真实执行适配器和 Docker Judge，再扩大到 30 题。
6. API 调用前核实凭据和预算；正式预算最低 390 次，500 次上限保留 110 次仲裁/修复/重试余量。

## 本地机器可读工件

本次最终预检目录：`/Users/odalys/Documents/hy4oi-data/codecontests-v1/preflight-20260907-v3`。早期 v1/v2 工件仅用于保留探索记录，不是本次最终审核草案。

索引：`77a9b82f413fdfccb14e8172a31d8321f9c9a30e5840e28df4190385c79fd71d.json`

- acquisition: `acquisition/36b67942ceef2bdb4ae676e353dc212ba09afcfb7dd07b4a43f5f023cbf5cb72.json`
- acquisition-validation: `acquisition-validation/96818fa9a1fad8178c9f9a1312711d23608cdc180f744d0e09adb731ab97e0a4.json`
- data-preflight: `data-preflight/ef01c1814126c22f417172d77fd3e5e1bcae9b0b08a77aeb0911a5470d8cce09.json`
- human-review-draft: `human-review-draft/1b611cebf2678f0dc8687bdd0f6a0d55649bd895604d32cc071171bc9774a513.json`

工件均按内容哈希寻址且不可覆盖；不会把题面、隐藏测试或第三方提交源码复制到此报告。
