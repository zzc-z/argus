"""研究提问的请求 / 响应模型。

只放 HTTP 边界该有的校验。流式相关的判断一律不在这里做——开流之后
HTTP 状态码已经发出，改不了了，报错只能走 SSE 的 error 事件。
"""

from pydantic import BaseModel, Field, field_validator

# 提问长度上限。2000 字足够写一个具体的研究问题，再长通常是误粘贴。
MAX_QUESTION_LENGTH = 2000


class AskRequest(BaseModel):
    """研究提问的请求体。"""

    question: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_LENGTH,
        description="要研究的问题。空字符串或纯空白会被拒绝。",
    )

    replace_run_id: str | None = Field(
        default=None,
        description=(
            "这一轮要**取代**的 run id（同一标签页里重问时传上一轮的 id）。"
            "服务端会取消它——不取消的话上一轮会继续烧 token 并占着并发槽位。"
        ),
    )
    """要取代的 run id。

    **为什么按 id 而不是「用户最近一轮」。** 用户可能开着两个标签页各跑
    一个研究——按「最近一轮」取消的话，第二个标签页一提问就把第一个
    标签页的生成掐掉了。前端知道**自己**这个标签页正在跑哪一轮（URL
    里的 run id），所以精确传上来，服务端只取消这一个。

    别的用户或不存在的 id 一律忽略（不报错）——那只是「没有要取消的
    东西」，不是用户的错。
    """

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        """挡掉纯空白。

        ``min_length=1`` 只看字符数，``"   "`` 和 ``"\\n\\t"`` 都能过。
        空白提问会白白触发一次完整的多轮模型调用（几十秒 + 真实 token
        花费），必须在开流前就拒掉。
        """
        if not value.strip():
            raise ValueError("问题不能为空白")
        return value
