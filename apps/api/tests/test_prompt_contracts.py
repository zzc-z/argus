"""Prompt 契约测试。

## 为什么需要

Prompt 里的**指令**是模型行为的唯一来源，而 prompt 内容改��**不会有任何
测试失败**——不像代码，删掉一行逻辑会立刻报错。

这在 argus 有一个真实的例子：``_build_user_prompt`` 的 docstring 声称
「逐条独立判定，不让句子之间互相参考」，但**这句话从来没进过 prompt**——
它只存在于 Python 注释里。模型实际收到的 prompt 没有这条指令，
position bias / anchoring 的防护等于不存在。

## 测什么

不测 prompt 全文（那会变得极其脆弱，改一个字就红）。只测**真正的设计意图**
是否还写在 prompt 里 —— 这些是模型行为的根据，改掉了就该有人知道。

断言写成「必须包含某句关键指令」，而不是「等于某段文本」。
"""

from app.services.agent_turn import SYSTEM_PROMPT
from app.services.faithfulness import JUDGE_PROMPT
from app.services.stages import ANALYST_PROMPT, SUPERVISOR_PROMPT


class TestJudgePromptContract:
    """Critic 的判定 prompt —— 产品最核心的质量防线。"""

    def test_states_numeric_consistency_rule(self) -> None:
        """数字必须一致。

        嵌入相似度在「原文 2.5 倍、句子 100 倍」上得 0.9996 —— 抓不到。
        所以数字一致性**只能**靠 prompt 里的明确判据。删掉它等于
        把最致命的一类错误交给运气。
        """
        assert "数字必须一致" in JUDGE_PROMPT

    def test_forbids_direction_flip(self) -> None:
        """结论方向必须一致（「提升」不能判成「下降」）。

        嵌入相似度在方向说反时得 0.9866 —— 同样抓不到。
        """
        assert "结论方向必须一致" in JUDGE_PROMPT

    def test_forbids_entity_substitution(self) -> None:
        """专有名词不得替换（台积电 → 三星）。"""
        assert "专有名词不得替换" in JUDGE_PROMPT

    def test_requires_independent_judgement_per_item(self) -> None:
        """必须要求逐条独立判定。

        没有这条，模型在长列表里会互相参考 —— 看到「同一 chunk 的其他句子
        都被判 supported」就倾向于给剩下的也判 supported（anchoring）。
        业界实测 position bias 在 15 万次评测里稳定存在，
        position-swap 去偏能把一致性从 ~60% 提到 ~85%。
        """
        assert "逐条独立判定" in JUDGE_PROMPT

    def test_requires_strict_json_output(self) -> None:
        """必须要求纯 JSON 输出。

        模型爱给 ```json 围栏，而 ``jiter`` 容忍尾随内容——但前提是
        prompt 里确实要求了纯 JSON，否则解析失败率会显著上升。
        """
        assert "只输出 JSON" in JUDGE_PROMPT

    def test_requires_partial_judgement_for_multi_citation_sentences(self) -> None:
        """一句多角标时必须按「该句中由本段原文支撑的部分」判定。

        实测（2026-11-18 校准，golden set）：缺这条指令时，
        「Blackwell 采用 CoWoS 封装且能效提升 2.5 倍[1][2]」两个角标
        **全被判成 unsupported** —— 因为整句无法被任一篇原文完整支撑。

        加上这条指令后 κ 从 0.769 提到 0.892，误伤率从 18.8% 降到 8.3%，
        顺序敏感从 2 条降到 0 条。
        """
        assert "多份资料" in JUDGE_PROMPT or "多个角标" in JUDGE_PROMPT
        assert "支撑的那部分结论" in JUDGE_PROMPT

    def test_defines_both_verdict_vocabulary_words(self) -> None:
        """两个判定词都要在 prompt 里写明。

        ``_SUPPORTED_WORDS`` / ``_UNSUPPORTED_WORDS`` 是解析层的白名单，
        prompt 里不写这两个词，模型就可能回别的表述 —— 而未知词汇会被
        归为「无法判定」，那条判定就白费了。
        """
        assert '"supported"' in JUDGE_PROMPT
        assert '"unsupported"' in JUDGE_PROMPT


class TestAgentPromptContract:
    """主循环与两个节点角色的 prompt。"""

    def test_system_prompt_forbids_preamble_before_tool_calls(self) -> None:
        """调工具前不要写说明文字。

        主循环**无法**在代码层过滤「过程叙述」——协议里没有 progress-update
        通道，文字与正文走同一个 ``text_delta``。唯一的防线是 prompt 要求
        模型在调工具前不说话。删掉它，用户的报告里会混进「我先查一下…」
        这类过程叙述。
        """
        assert "不要在调用前写任何说明文字" in SYSTEM_PROMPT

    def test_supervisor_prompt_limits_to_subtask_planning(self) -> None:
        """Supervisor 只拆子任务，不产出正文。

        主循环的落盘逻辑假设 Supervisor 不产出正文（``agent.py`` 里有一段
        注释专门说明这点）。prompt 里的这条约束是那个假设的前提。
        """
        assert "子任务" in SUPERVISOR_PROMPT

    def test_analyst_prompt_requires_conflict_detection(self) -> None:
        """Analyst 要做冲突检测，而不是复述证据。

        Analyst 的产出进 Writer 的上下文 —— 它说「这两条矛盾」，Writer 才会
        把它们并列成两个事实。它只复述的话，这个节点就是白跑一轮模型调用。
        """
        assert "矛盾" in ANALYST_PROMPT
