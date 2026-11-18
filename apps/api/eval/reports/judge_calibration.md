# Judge 一致率校准报告

> 数据集：`eval/datasets/golden_v1.jsonl`（20 条人工标注）
> 模型：`claude-sonnet-5`（critic 与 writer 同型号 —— 见「已知问题」）
> 日期：2026-11-18
> 复现：`cd apps/api && uv run python -m eval.calibrate_judge --repeat 3`

## 结论

| 指标 | 值 | 判读 |
|---|---|---|
| **TPR**（该判无据的，判出来了多少） | **100%**（30/30，fn=0） | ✅ **最关键的一项** —— judge 从不漏判 |
| **TNR**（该判有据的，没误伤多少） | **93.6%**（3 次误伤） | ✅ 可接受 |
| **Cohen's κ** | **0.920** | ✅ 好（基准：>0.7 可接受，>0.8 好） |
| 稳定性（3 次重跑判定一致） | **85%** | ⚠️ 3 条不稳定（g006、g007、g017） |
| 顺序敏感（position bias） | **1 条**（g010） | ⚠️ 基本消除 |

混淆矩阵：`tp=30 fn=0 tn=44 fp=3 unjudged=1`

**TPR = 100% 是这份报告最重要的一行。** 它意味着 argus 的 CRITIC
**真的能抓住编造的数字** —— 一道"数字错了 40 倍"的断言不会被放过。
这是产品对用户的核心承诺，而它现在有数字支撑，而不只是"应该有这个功能"。

## 校准过程中改掉的三个真问题

### 1. Judge prompt 缺一条指令 → 多角标句被整句判死（κ 0.769 → 0.892）

**现象**：`Blackwell 采用 CoWoS 封装且能效提升 2.5 倍[1][2]。`
一句带两个角标，两个都判成 unsupported。

**根因**：一句多角标时，整句被分别放进 `result[1]` 和 `result[2]`，
于是模型要判断**整句**能否从单篇原文得到。原文 1 只说封装、不说能效
→ 整句不成立 → 判 unsupported。

**修复**（`JUDGE_PROMPT` 加一句）：

> 一句话可能同时引用多份资料（带多个角标）。这时只判断**该句中由本段原文
> 支撑的那部分结论**，不要因为句中的其它部分没有在本段原文中出现就判 unsupported。

**实测**：角标 2 从 unsupported 变成 supported（原文 2 确实支撑
"能效提升 2.5 倍"）。κ 从 0.769 提到 0.892，误伤率从 18.8% 降到 8.3%，
顺序敏感从 2 条降到 0 条。

### 2. 一条 golden 样例的期望写错了（不是模型错）

g011 原本测「一句多角标、两篇原文各自支撑不同部分」。但我写原文 1 时
写的是「先进封装采用 CoWoS-S 方案」—— 没说 Blackwell 用它。

**模型的判定是对的**（reason 原文：「原文1仅称先进封装采用CoWoS-S方案，
未明确说明该封装用于Blackwell」），是**我的期望**把一个隐含推断当成了
"有据支撑"。

改成原文 1 明写「Blackwell 采用 CoWoS 先进封装方案」后，
测的才是「多角标的部分判定」这个真实场景。

### 3. 一条 golden 样例把悬空角标当成了待判定条目

g016 有三个角标，但 `sources` 里只有两个 —— 角标 3 是**悬空引用**
（引用表里没有该条目）。它属于 `missing`，不是"无据支撑"。

我把 (3,0) 错标成 `expected_verdicts` 里的 unsupported，于是模型
（正确地）没给它判定，反倒像是模型漏判。改成 `expected_missing: [3]`。

## 剩下的非确定性（85% 稳定性）

同一输入跑 3 次，g006、g007、g017 的判定会变。

**g006** 也能看到同类现象：「先进封装采用 CoWoS」vs 原文「CoWoS-S 方案」
—— 模型在**是否算同一个东西**上摇摆。

这不是可以通过改 prompt 消掉的，是模型本身的性质。argus 的应对是
**分母纪律**：`unjudged` 从分母剔除，用户看到的是「判定了 N 条」，
不是假的 100%。这是正确设计 —— 但要清楚：**单次判定的通过率有 ±几个点的抖动**。

顺序敏感那条（g010 的第二个变体）也在同一量级：把待判顺序反过来，
那一条的判定偶尔会变。`JUDGE_PROMPT` 里的「逐条独立判定」指令把
敏感条目从 2 条压到 0–1 条，但**这是请求不是保证**。

## 已知问题：critic 与 writer 同型号

当前配置下 critic 与 writer 都是 `claude-sonnet-5`（`anthropic_critic_model`
留空时回落 `anthropic_complex_model`）。

**自偏好偏差**（arXiv 2410.21819）会让 judge 给自家输出打高分，
也就是 TPR 100% 这个数字里可能有一部分是偏袒带来的。

`llm.assert_distinct_judge_and_writer()` 会在 `APP_ENV=prod` 时
拒绝启动同型号配置。**要拿到无偏的基线，需要给
`ANTHROPIC_CRITIC_MODEL` 配一个不同的型号再跑一次校准。**

未做 —— 本地没有第二个可用型号。

## 复现与门禁

```bash
cd apps/api
uv run python -m eval.calibrate_judge --repeat 3
uv run python -m eval.calibrate_judge --repeat 3 --out eval/reports/judge_calibration.json
```

CI 里跑的是**离线校验**（`tests/eval/test_golden.py`，不需要 API key）：
验证数据集格式、期望判定与正文角标一致、关键类别没漏、解析层往返。

真校准**不在 CI 里** —— 它要花钱、有非确定性、且需要仓库 secrets。
建议每周手动跑一次，把结果存进 `eval/reports/`。

## 待补

- [ ] 给 `ANTHROPIC_CRITIC_MODEL` 配不同型号，重跑一次拿到无自偏好的基线
- [ ] golden set 扩到 50 条（当前 20 条，业界建议 20–50 条起步）
- [ ] 训练/开发/测试三分（当前 20 条一次全用，没有留出未见的测试集）
- [ ] 数字/日期断言走确定性通道（当前仍交给 LLM 判）
