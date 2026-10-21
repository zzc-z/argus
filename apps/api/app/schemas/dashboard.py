"""Dashboard 与系统状态的响应模型。

## 为什么有这两个

前端 `/dashboard` 与 `/settings` 原先是整页 mock——KPI、活动流、供应商
状态、向量索引诊断全是编的。后端当时没有对应接口，于是那些数字看起来
像真的。

这两个接口把**真能从库里读出来的**那部分接回去：

- `/api/v1/dashboard` —— 报告数、资料数、切片数、token 用量、最近报告。
  全部来自 `reports` / `sources` / `document_chunks` 三张表的聚合。
- `/api/v1/settings/status` —— 外部能力的配置状态与向量索引规模。

**读不到的东西不给**：没有 topics 表就没有「订阅数」，没有 notifications
表就没有「未读通知数」。这些数字不会出现在响应里——宁可少一个 KPI，
也不要一个编的。
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.report import ReportSummaryV


class DashboardResponse(BaseModel):
    """Dashboard 概览。

    全部字段都来自真实的表聚合——前端拿到的每个数字都能在库里对上。
    """

    model_config = {"from_attributes": True}

    # 我的报告数。
    report_count: int = Field(description="当前用户的报告总数")
    # 我上传的资料数。
    source_count: int = Field(description="当前用户的资料总数")
    # 资料切出来的切片总数。
    chunk_count: int = Field(description="当前用户资料的切片总数")
    # 累计 token 用量。分输入输出——只看总数看不出是检索还是成稿烧的。
    total_input_tokens: int = Field(description="所有报告的累计输入 token")
    total_output_tokens: int = Field(description="所有报告的累计输出 token")
    # 最近几篇报告，用于「继续研究」列表。
    recent_reports: list[ReportSummaryV] = Field(description="最近生成的报告，按时间倒序")
    # 最后一篇报告的生成时间；一篇都没有时为 null。
    latest_report_at: datetime | None = Field(default=None, description="最近一篇报告的生成时间")


class ProviderStatusV(BaseModel):
    """一个外部能力的配置状态。

    **只说「配了没有」，不泄露密钥。** configured 是布尔，detail 是
    给人看的一句话。
    """

    id: str = Field(description="能力标识，如 'anthropic' / 'tavily' / 'embedding'")
    name: str = Field(description="展示名")
    configured: bool = Field(description="配置是否就绪")
    detail: str = Field(description="一句话说明，如「未配置 API 密钥」")


class VectorIndexV(BaseModel):
    """向量索引规模。

    ``embedded_chunk_count`` 与 ``chunk_count`` 的差值就是「还没嵌入的
    切片数」——摄取失败或异步嵌入还没跑完时会是正数。
    """

    source_count: int = Field(description="资料数")
    chunk_count: int = Field(description="切片总数")
    embedded_chunk_count: int = Field(description="已完成向量化的切片数")


class SettingsStatusResponse(BaseModel):
    """系统设置页的状态区块。"""

    providers: list[ProviderStatusV] = Field(description="各外部能力的配置状态")
    vector_index: VectorIndexV = Field(description="向量索引规模")


__all__ = [
    "DashboardResponse",
    "ProviderStatusV",
    "SettingsStatusResponse",
    "VectorIndexV",
]
