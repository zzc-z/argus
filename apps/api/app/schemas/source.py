"""资料源相关的请求/响应模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.source import SourceStatus, SourceType


class SourceCreate(BaseModel):
    """通过 URL 建源（网页）。文件上传走 multipart，不走这个模型。"""

    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2048)
    source_type: SourceType = Field(default=SourceType.HTML)

    @field_validator("title")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        """纯空白标题要拒。

        ``min_length=1`` 只看长度，「   」过得去——列表页会显示成空条目，
        用户点进去也不知道是哪份资料。
        """
        if not value.strip():
            raise ValueError("标题不能为空白")
        return value


class SourceResponse(BaseModel):
    """资料源状态。前端队列监视器靠它显示进度。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    source_type: str
    status: str
    url: str | None = None
    size_bytes: int | None = None
    credibility_score: float
    chunk_count: int
    char_count: int
    error_message: str | None = None
    created_at: datetime


class SourceListResponse(BaseModel):
    """列表端点。带 total 供前端分页。"""

    items: list[SourceResponse]
    total: int


class ChunkResponse(BaseModel):
    """切片详情。只在用户点开某片时返回，避免列表页拉全文。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    chunk_index: int
    content: str
    page: int | None = None
    start_offset: int
    end_offset: int


__all__ = [
    "ChunkResponse",
    "SourceCreate",
    "SourceListResponse",
    "SourceResponse",
    "SourceStatus",
    "SourceType",
]
