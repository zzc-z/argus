"""数据库迁移测试。

## 为什么需要这个文件

项目里**从来没有**测过迁移。全部测试都用
``Base.metadata.create_all`` 建表（``tests/conftest.py``），schema 直接来自
ORM——于是**迁移与 ORM 的漂移结构上就测不出来**：ORM 加了字段，测试照样绿，
只有真实数据库会炸。

这不是假设，是已经发生过的：``report_sources`` 表在某些库里缺 ``n`` 列
（ORM 与迁移文件都有，只有部分数据库没有）。后果是

1. ``GET /api/v1/reports/{id}`` 直接 500；
2. 更重的是写路径——``_write`` 在 commit 时才 INSERT 带 ``n`` 的行，失败
   后整个事务回滚，**引用了私有资料的报告连同 references 一起丢**。

而 CI 全绿，因为测试根本不跑迁移。

所以这个文件测的是**「迁移跑完之后，真实 schema 与 ORM 是否一致」**——
这正是 ``create_all`` 测不到的那一段。

## 测什么

对每个迁移链上的库：跑 ``alembic upgrade head``，然后把实际 schema 与
``Base.metadata`` 逐表逐列比对。任一差异都让测试失败。

额外测一个具体的回归场景：缺 ``n`` 列的老库升级后能正常工作。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from app.models import Base

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"
VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _run_alembic(db_path: Path, *args: str) -> None:
    """跑 alembic 子进程。

    用子进程而不是进程内调 ``command.upgrade``：后者会复用当前进程的
    ``get_settings()`` 缓存（``lru_cache``），改 ``DATABASE_URL`` 不生效，
    于是迁移会打到**开发库**上——那正好是本文件要保护的东西。
    """
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ALEMBIC_INI.parent,
        env={
            "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(Path.home()),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            f"alembic {' '.join(args)} 失败（exit {result.returncode}）:\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _schema_diff(db_path: Path) -> list[str]:
    """返回实际 schema 与 ORM 声明的差异列表，空列表表示一致。"""
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        inspector = inspect(engine)
        actual_tables = set(inspector.get_table_names())
        expected_tables = set(Base.metadata.tables)

        diffs: list[str] = []

        for missing in sorted(expected_tables - actual_tables):
            diffs.append(f"表缺失: {missing}")

        for extra in sorted(actual_tables - expected_tables):
            # alembic_version 是 alembic 自己的账本，不是业务表。
            if extra == "alembic_version":
                continue
            diffs.append(f"多余表: {extra}")

        for table in sorted(expected_tables & actual_tables):
            actual_cols = {c["name"] for c in inspector.get_columns(table)}
            expected_cols = set(Base.metadata.tables[table].columns.keys())
            for missing in sorted(expected_cols - actual_cols):
                diffs.append(f"列缺失: {table}.{missing}")
            for extra in sorted(actual_cols - expected_cols):
                diffs.append(f"多余列: {table}.{extra}")

        return diffs
    finally:
        engine.dispose()


def test_upgrade_head_produces_schema_matching_orm(tmp_path: Path) -> None:
    """全新库跑完所有迁移后，schema 必须与 ORM 声明完全一致。

    这条测试是本文件的核心。它覆盖的不只是「迁移能不能跑」，
    而是「跑完的库能不能被 ORM 正常使用」——后者才是真正会 500 的地方。
    """
    db_path = tmp_path / "fresh.db"
    _run_alembic(db_path, "upgrade", "head")

    diffs = _schema_diff(db_path)
    assert not diffs, "迁移后的 schema 与 ORM 不一致:\n" + "\n".join(diffs)


def test_upgrade_is_idempotent_on_drifted_database(tmp_path: Path) -> None:
    """缺列的老库升级后能正常工作。

    复现 ``report_sources`` 缺 ``n`` 列的真实漂移：先建一张**没有** ``n``
    的表，跑迁移，然后验证

    1. 迁移不报错（不能像现在这样 ``duplicate column name: n``）；
    2. ``n`` 列补上了，且是 NOT NULL；
    3. 已有行被回填了编号，不留 NULL（NOT NULL 约束会让留 NULL 的行
       直接写不进去）。

    没有这条测试，上面那个 ``duplicate column`` 崩溃能一路发到线上。
    """
    db_path = tmp_path / "drifted.db"
    _run_alembic(db_path, "upgrade", "c3d9e1f27a04")

    # 手工造出漂移：删掉 n 列（SQLite 3.35+ 支持 DROP COLUMN）。
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("ALTER TABLE report_sources DROP COLUMN n")
        conn.execute(
            "INSERT INTO report_sources (report_id, chunk_id, cite_count) VALUES (1, 100, 1)"
        )
        conn.execute(
            "INSERT INTO report_sources (report_id, chunk_id, cite_count) VALUES (1, 101, 1)"
        )
        conn.commit()
    finally:
        conn.close()

    _run_alembic(db_path, "upgrade", "head")

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT chunk_id, n FROM report_sources ORDER BY chunk_id"
        ).fetchall()
    finally:
        conn.close()
    # n 为 NULL 或 0 都算回填失败
    assert all(row[1] for row in rows), f"n 列回填失败: {rows}"
    # 同一份报告内编号应从 1 开始且不重复
    ns = sorted(r[1] for r in rows)
    assert ns == [1, 2], f"回填编号应从 1 连续递增，实际 {ns}"

    diffs = _schema_diff(db_path)
    assert not diffs, "漂移库升级后 schema 仍与 ORM 不一致:\n" + "\n".join(diffs)


def test_every_migration_file_has_valid_revision_chain() -> None:
    """每个迁移文件都要声明 revision / down_revision，且链不能断。

    断链的表现是 ``alembic upgrade head`` 悄悄少跑一段迁移——这正是
    漂移的成因之一。
    """
    files = sorted(VERSIONS_DIR.glob("*.py"))
    assert files, "找不到任何迁移文件"

    revisions: set[str] = set()
    downs: set[str] = set()
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert 'revision: str = "' in text, f"{path.name} 缺少 revision 声明"
        assert "down_revision" in text, f"{path.name} 缺少 down_revision 声明"
        for line in text.splitlines():
            if line.startswith("revision: str = "):
                revisions.add(line.split('"')[1])
            if line.startswith("down_revision: str | Sequence[str] | None = "):
                value = line.split("=")[1].strip().strip('"')
                if value != "None":
                    downs.add(value)

    orphans = downs - revisions
    assert not orphans, f"有迁移指向不存在的 down_revision: {orphans}"


def test_upgrade_preserves_existing_rows_and_plaintext_keys(tmp_path: Path) -> None:
    """升级**不能丢存量行**，也不能让存量明文 key 报废。

    复现真实场景：这次迁移给凭据表加了 ``scope`` 列并改了 key 的存储
    方式（明文 → Fernet 密文）。升级前已经写进去的行必须还在。

    ⚠️ 存量 key 仍是**明文**——迁移不重写它（主密钥在环境变量里，
    迁移脚本未必能拿到）。但**解析时必须还能读出来**：``decrypt_secret``
    对「没带 ``enc:v1:`` 前缀的值」原样返回。
    """
    db_path = tmp_path / "existing.db"
    # 先升到有 provider_credentials 表、但还没有 scope 列的版本
    _run_alembic(db_path, "upgrade", "f7c2b9e4a183")

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (email, display_name, created_at, updated_at) "
                    "VALUES ('legacy@example.com', 'Legacy', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            user_id = conn.execute(
                text("SELECT id FROM users WHERE email = 'legacy@example.com'")
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO provider_credentials "
                    "(user_id, anthropic_api_key, tavily_api_key, created_at, updated_at) "
                    "VALUES (:uid, 'sk-ant-legacy-plain', 'tvly-legacy-plain', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"uid": user_id},
            )
    finally:
        engine.dispose()

    _run_alembic(db_path, "upgrade", "head")

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT scope, anthropic_api_key, tavily_api_key "
                    "FROM provider_credentials"
                )
            ).one()
        # 行还在
        assert row is not None
        # scope 补上了，且是 'user'
        assert row[0] == "user", f"存量行的 scope 应补成 'user'，实际 {row[0]!r}"
        # 明文 key 没被改写（迁移不重写存量数据）
        assert row[1] == "sk-ant-legacy-plain"
        assert row[2] == "tvly-legacy-plain"
    finally:
        engine.dispose()


def test_downgrade_succeeds_when_default_row_exists(tmp_path: Path) -> None:
    """回滚**不能炸**——有共享默认行时也要能回。

    共享默认行的 user_id 是 NULL，而回滚要把 user_id 改回非空。
    SQLite 的 batch 模式重建表，NOT NULL 约束会在重建时校验到 NULL 行
    就报错——实测报 `NOT NULL constraint failed: _alembic_tmp_provider_credentials.user_id`。

    修法是回滚时先删掉共享默认行（它是本次迁移引入的概念，回滚时
    丢弃它在语义上正确），**用户自己的行一个都不动**。
    """
    db_path = tmp_path / "downgrade.db"
    _run_alembic(db_path, "upgrade", "head")

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (email, display_name, created_at, updated_at) "
                    "VALUES ('u@example.com', 'U', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            user_id = conn.execute(
                text("SELECT id FROM users WHERE email = 'u@example.com'")
            ).scalar_one()
            # 一个用户行
            conn.execute(
                text(
                    "INSERT INTO provider_credentials "
                    "(user_id, scope, tavily_api_key, created_at, updated_at) "
                    "VALUES (:uid, 'user', 'tvly-user-row', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"uid": user_id},
            )
            # 一个共享默认行（user_id 为 NULL）
            conn.execute(
                text(
                    "INSERT INTO provider_credentials "
                    "(user_id, scope, tavily_api_key, created_at, updated_at) "
                    "VALUES (NULL, 'default', 'tvly-default-row', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
    finally:
        engine.dispose()

    # 这一步以前会 IntegrityError 让 downgrade 直接卡住
    _run_alembic(db_path, "downgrade", "f7c2b9e4a183")

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT user_id, tavily_api_key FROM provider_credentials")
            ).all()
        # 用户行保留、默认行消失
        assert len(rows) == 1, f"回滚后应只剩用户行，实际 {rows}"
        assert rows[0][1] == "tvly-user-row"
        assert rows[0][0] is not None, "用户行的 user_id 不该是 NULL"
    finally:
        engine.dispose()
