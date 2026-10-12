"""embedder 的测试。

全部用假 client，不打真实网络——外部服务慢且收费。
重点保护两个「错了不会报错、只会悄悄给出错误结果」的行为：
1. 响应乱序时不排序 → 向量与文本错位 → 检索出无关内容
2. 维度不校验 → 写入索引失败或检索全乱
"""

from typing import Any

import pytest

from app.config import Settings, get_settings
from app.services import embedder
from app.services.embedder import (
    DimensionMismatchError,
    EmbeddingError,
    EmbeddingNotConfiguredError,
    clear_client_cache,
    embed_or_none,
    embed_texts,
    get_embedding_client,
)


class FakeItem:
    def __init__(self, index: int, embedding: list[float]) -> None:
        self.index = index
        self.embedding = embedding


class FakeResponse:
    def __init__(self, data: list[FakeItem]) -> None:
        self.data = data


class FakeEmbeddings:
    """记录每次调用。

    ``make`` 给的是「按输入条数造结果」的函数——真实 API 返回的条数
    永远等于请求条数，用固定列表会让分批测试算错。
    """

    def __init__(self, make: Any) -> None:
        self._make = make
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        return FakeResponse(self._make(kwargs["input"]))


class FixedEmbeddings(FakeEmbeddings):
    """总是返回同一组固定结果——用于测排序与维度。"""

    def __init__(self, data: list[FakeItem]) -> None:
        super().__init__(lambda _input: list(data))


class FakeClient:
    """``data`` 给固定结果集（用于排序/维度测试），
    ``make`` 给一个「按输入造结果」的函数（用于分批测试）。"""

    def __init__(self, *, data: list[FakeItem] | None = None, make: Any = None) -> None:
        if make is not None:
            self.embeddings: FakeEmbeddings = FakeEmbeddings(make)
        elif data is not None:
            self.embeddings = FixedEmbeddings(data)
        else:  # pragma: no cover — 调用方必须给一个
            raise ValueError("FakeClient 需要 data 或 make")


def _fixed(items: list[FakeItem]) -> FakeClient:
    return FakeClient(data=items)


def _vec(dim: int, seed: float = 1.0) -> list[float]:
    return [seed] * dim


def _patch(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> FakeEmbeddings:
    monkeypatch.setattr(embedder, "get_embedding_client", lambda: client)
    return client.embeddings


# ── 基本行为 ───────────────────────────────────────────────
async def test_returns_vector_per_input(monkeypatch: pytest.MonkeyPatch) -> None:
    dim = get_settings().embedding_dimensions
    _patch(monkeypatch, _fixed([FakeItem(0, _vec(dim))]))

    out = await embed_texts(["一段中文"])

    assert len(out) == 1
    assert len(out[0]) == dim


async def test_empty_input_skips_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """空输入不该发请求——省一次网络往返，也避免 0 条批次报错。"""
    fake = _patch(monkeypatch, _fixed([]))

    assert await embed_texts([]) == []
    assert fake.calls == []


async def test_sends_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    dim = get_settings().embedding_dimensions
    fake = _patch(monkeypatch, _fixed([FakeItem(0, _vec(dim))]))

    await embed_texts(["x"])

    assert fake.calls[0]["model"] == get_settings().embedding_model


async def test_sends_explicit_dimensions(monkeypatch: pytest.MonkeyPatch) -> None:
    """必须显式传 dimensions。

    实测百炼的 text-embedding-v4 不传时默认返回 1024 维，
    与索引表的 1536 不符——会被 DimensionMismatchError 拦下，
    但那时已经白跑了一次网络请求。显式传省掉这次往返。
    """
    dim = get_settings().embedding_dimensions
    fake = _patch(monkeypatch, _fixed([FakeItem(0, _vec(dim))]))

    await embed_texts(["x"])

    assert fake.calls[0]["dimensions"] == dim


# ── 顺序保证（最重要的一条）──────────────────────────────────
async def test_sorts_response_by_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """响应乱序必须按 index 排。

    乱序写入索引的后果是静默的：向量能存进去，检索也能跑，
    只是检索出来的全是无关内容——极难察觉。
    """
    dim = get_settings().embedding_dimensions
    _patch(
        monkeypatch,
        _fixed(
            [
                FakeItem(0, [0.0] * dim),
                FakeItem(1, [1.0] * dim),
                FakeItem(2, [2.0] * dim),
            ]
        ),
    )

    out = await embed_texts(["a", "b", "c"])

    assert [v[0] for v in out] == [0.0, 1.0, 2.0]


async def test_sorts_actually_reorders_shuffled_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """乱序输入的场景——这是上面那条的真实用例。"""
    dim = get_settings().embedding_dimensions
    fake = _patch(
        monkeypatch,
        _fixed([FakeItem(2, [2.0] * dim), FakeItem(0, [0.0] * dim), FakeItem(1, [1.0] * dim)]),
    )

    out = await embed_texts(["a", "b", "c"])

    assert [v[0] for v in out] == [0.0, 1.0, 2.0]
    assert fake.calls  # 确认真的发了请求


# ── 批处理 ─────────────────────────────────────────────────
async def test_splits_large_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    """百炼单批只收 10 条，超过会被 400 拒。"""
    dim = get_settings().embedding_dimensions
    batch_size = embedder.MAX_BATCH_SIZE
    count = batch_size * 2 + 3

    # 每个向量首元素编码自己的全局序号，用来验证跨批拼接后顺序不乱
    def _make(items: list[str]) -> list[FakeItem]:
        return [FakeItem(i, _vec(dim, float(i))) for i in range(len(items))]

    fake = _patch(monkeypatch, FakeClient(make=_make))

    out = await embed_texts([f"文本 {i}" for i in range(count)])

    assert len(out) == count
    assert len(fake.calls) == 3  # 10 + 10 + 3
    assert all(len(c["input"]) <= batch_size for c in fake.calls)


async def test_batches_preserve_global_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """分批后整体顺序必须与输入一致——跨批错位同样静默出错。"""
    dim = get_settings().embedding_dimensions
    count = embedder.MAX_BATCH_SIZE * 3

    def _make(items: list[str]) -> list[FakeItem]:
        # 首元素直接来自输入文本里的编号，跨批也能对上
        return [FakeItem(i, _vec(dim, float(item.split()[-1]))) for i, item in enumerate(items)]

    _patch(monkeypatch, FakeClient(make=_make))

    out = await embed_texts([f"文本 {i}" for i in range(count)])

    assert [v[0] for v in out] == [float(i) for i in range(count)]


# ── 维度校验 ───────────────────────────────────────────────
async def test_rejects_wrong_dimension(monkeypatch: pytest.MonkeyPatch) -> None:
    """维度错了要立刻报——vec0 的建表 DDL 锁死了维度。"""
    fake = _patch(monkeypatch, _fixed([FakeItem(0, [0.1] * 42)]))

    with pytest.raises(DimensionMismatchError, match="维度"):
        await embed_texts(["x"])
    assert fake.calls


async def test_dimension_mismatch_is_not_retryable_error() -> None:
    """维度错必须能被单独捕获——重试它没有意义。"""
    assert issubclass(DimensionMismatchError, EmbeddingError)
    assert not issubclass(DimensionMismatchError, EmbeddingNotConfiguredError)


# ── 降级 ───────────────────────────────────────────────────
async def test_embed_or_none_returns_none_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise() -> None:
        raise EmbeddingNotConfiguredError("未配置")

    monkeypatch.setattr(embedder, "get_embedding_client", _raise)

    assert await embed_or_none(["x"]) is None


async def test_embed_or_none_still_raises_dimension_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """维度错不能被降级吞掉——那是真错误，重试无用。"""
    expected = get_settings().embedding_dimensions
    monkeypatch.setattr(
        embedder,
        "get_embedding_client",
        lambda: _fixed([FakeItem(0, [0.1] * (expected + 1))]),
    )

    with pytest.raises(DimensionMismatchError):
        await embed_or_none(["x"])


# ── client 构造 ────────────────────────────────────────────
def test_client_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_client_cache()
    monkeypatch.setattr(
        "app.services.embedder.get_settings",
        lambda: Settings(embedding_api_key=None),
    )

    with pytest.raises(EmbeddingNotConfiguredError, match="EMBEDDING_API_KEY"):
        get_embedding_client()

    clear_client_cache()


def test_client_is_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """复用连接池——每次 new 会让 TCP/TLS 握手开销超过实际收益。"""
    clear_client_cache()
    monkeypatch.setattr(
        "app.services.embedder.get_settings",
        lambda: Settings(embedding_api_key="sk-test", embedding_base_url="https://x.test/v1"),
    )

    first = get_embedding_client()
    second = get_embedding_client()

    assert first is second
    clear_client_cache()


def test_client_uses_configured_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """换服务商只改 .env，不改代码。"""
    clear_client_cache()
    monkeypatch.setattr(
        "app.services.embedder.get_settings",
        lambda: Settings(embedding_api_key="sk-test", embedding_base_url="https://bailian.test/v1"),
    )

    client = get_embedding_client()

    assert "bailian.test" in str(client.base_url)
    clear_client_cache()
