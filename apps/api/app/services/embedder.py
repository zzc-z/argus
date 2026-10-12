"""嵌入层：把文本变成固定维度的向量。

嵌入模型与聊天模型是两件事——它不生成任何内容，只把「这段文字讲什么」
映射成坐标，语义相近的文字坐标也相近。这是 RAG 检索的前提：
问题和文档必须用**同一个模型**嵌入，否则两边坐标系对不上，检索结果等同随机。

## 为什么默认走阿里云百炼而不是 OpenAI 官方

OpenAI 官方只收境外信用卡，国内无法开通。百炼提供 OpenAI 兼容端点，
支付宝可付，新用户送 100 万 token（90 天有效）——走同一个 openai SDK，
只改 base_url。实测百炼的 ``text-embedding-v4`` 也能输出 1536 维，
与 OpenAI 的 ``text-embedding-3-small`` 维度一致，索引表不用改。

## 缺 key 时的降级

:func:`embed_texts` 在未配置时抛 :class:`EmbeddingNotConfiguredError`，
但摄取流程由 :func:`embed_or_none` 兜底，返回 ``None`` 让流程继续——
没有向量只是检索不到，解析出来的正文仍然入库，不至于整份资料白传。
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

from openai import AsyncOpenAI

from app.config import get_settings


class EmbeddingError(Exception):
    """调用嵌入服务失败。外部问题，不是用户输入问题。"""


class EmbeddingNotConfiguredError(EmbeddingError):
    """未配置 embedding key——运维问题。"""


class DimensionMismatchError(EmbeddingError):
    """返回的向量维度与配置不符。

    单独成一类是因为它不会自己恢复：vec0 的维度写在建表 DDL 里，
    维度错了要么重建索引表，要么改配置。混在通用异常里会被当成临时故障重试。
    """


# 百炼的 text-embedding-v4 单批最多 10 条（不是 OpenAI 的 2048），
# 超了直接报 400。取两家约束的最小值最省心。
MAX_BATCH_SIZE = 10


@lru_cache(maxsize=1)
def get_embedding_client() -> AsyncOpenAI:
    """嵌入服务 client 单例。复用连接池，理由同 services/llm.py。"""
    settings = get_settings()
    key = settings.embedding_api_key
    if key is None:
        raise EmbeddingNotConfiguredError("EMBEDDING_API_KEY 未配置，无法生成向量")

    kwargs: dict[str, object] = {"api_key": key.get_secret_value(), "max_retries": 2}
    if settings.embedding_base_url:
        kwargs["base_url"] = settings.embedding_base_url
    return AsyncOpenAI(**kwargs)  # type: ignore[arg-type]


def clear_client_cache() -> None:
    """测试重置用。与 services/llm.py 同名函数各自独立。"""
    get_embedding_client.cache_clear()


async def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """把一批文本转成向量，按输入顺序返回。

    内部按 :data:`MAX_BATCH_SIZE` 切片并发请求——百炼单批只收 10 条，
    一份 500 片的研报要发 50 次请求。
    """
    if not texts:
        return []

    client = get_embedding_client()
    settings = get_settings()
    expected = settings.embedding_dimensions

    batches = [texts[i : i + MAX_BATCH_SIZE] for i in range(0, len(texts), MAX_BATCH_SIZE)]
    results: list[list[float]] = []
    for batch in batches:
        results.extend(await _embed_one_batch(client, batch, expected))
    return results


async def _embed_one_batch(
    client: AsyncOpenAI,
    batch: Sequence[str],
    expected_dim: int,
) -> list[list[float]]:
    """发一批请求并校验维度。"""
    try:
        response = await client.embeddings.create(
            model=get_settings().embedding_model,
            input=list(batch),
            # 百炼的 text-embedding-v4 默认 1024 维，实测支持显式指定
            # （2026-10-12：1536 / 1024 都返回对应维度）。
            # 不传就会撞上 DimensionMismatchError——那道校验正是为了拦这个。
            dimensions=expected_dim,
        )
    except Exception as exc:
        raise EmbeddingError(f"调用嵌入服务失败：{type(exc).__name__}") from exc

    # 按 index 排序：OpenAI 规范允许乱序返回，不排序会与输入错位，
    # 而错位的向量写进索引后检索出来的全是无关内容，且极难察觉。
    ordered = sorted(response.data, key=lambda item: item.index)

    vectors = [item.embedding for item in ordered]
    actual = len(vectors[0]) if vectors else 0
    if actual != expected_dim:
        raise DimensionMismatchError(
            f"模型返回 {actual} 维，配置期望 {expected_dim} 维。"
            f"维度写在向量表建表 DDL 里，改了要重建索引。"
        )
    return vectors


async def embed_or_none(texts: Sequence[str]) -> list[list[float]] | None:
    """降级入口：未配置 key 时返回 None，让摄取流程继续。

    不吞掉 :class:`DimensionMismatchError`——那是真错误，重试无用。
    """
    try:
        return await embed_texts(texts)
    except EmbeddingNotConfiguredError:
        return None
