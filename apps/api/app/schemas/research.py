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
