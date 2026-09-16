"""0002 —— 语义层物化表（07 §12.2）+ pgvector 扩展 + embed_doc 双索引

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-16

归属窗口：W2A（docs/08 §3.4 阶段 2A）。
W1B 在 `repo/startup_assertions.py` 与 DELIVERY §7 已把两项 PENDING 指名给本窗口：
「`app.embed_doc.embedding` 向量列不存在（归 W2A）」+「pgvector 扩展未安装（物化时先建）」。

**设计要点（07 §12.2 原文）**：语义层是**版本化的不可变数据** —— 新版本只 INSERT，
旧版本只读。这让"版本切换"退化为"改一个指针"（§6.2 单键指针），回滚无需数据修复。

**两处与 §12.2 字面的偏差（如实登记，待架构窗口确认，W2A 不擅自开 U 号）**：

| # | §12.2 原文 | 本迁移 | 理由 |
|---|---|---|---|
| 1 | `field_binding` PK = `(bundle_version, concept, canonical_asset)` | PK = `(bundle_version, concept)` | §12.2 同页要求「`ambiguous: true` 的条目 `canonical_asset` 为空」—— **PK 列不得为 NULL**，两句话物理上不能同时成立。取 `(bundle_version, concept)` 保住"每概念每版本一条"的关键不变量，`canonical_asset` 保留为可空列 |
| 2 | `default_predicate` PK = `(bundle_version, domain)`，列 `predicate_sql` | 同 PK，但谓词集存 **jsonb 数组** | 一个域有**多条**谓词（YAML `default_predicates[domain]` 是列表）；单列 `predicate_sql` 装不下多条。聚合成 `[{id, predicate, reason, owner}]`，语义等价 |

**GRANT/POLICY 为什么不在这里**：ADR-10 要求它们**由语义包派生、绝不手写**，
且与物化行**同一事务**执行（§6.2 步骤②）—— 那是发布期动作
（`app/semantics/materialize.py`），不是迁移期 DDL。迁移只建**容器**（表）。
业务视图（v_order_paid 等）的 PG 侧 DDL 归属未定（SQLite 版归 W1A `data/schema.sql`），
已列入 W2A RELAY 的待裁决清单。
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

#: 向量维度。与 `EMBEDDING_DIM`（=1024，ADR-06 bge-m3）一致；
#: 启动期 loader 断言配置与语义包一致（§6.1 步骤⑤）。
#: 维度变更 = 版本递增 + 重建索引（ADR-06），**不改这里** —— 改了就是第二份真相。
EMBEDDING_DIM = 1024


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 0. pgvector 扩展（W1B 交接指名：当前未安装）
    # ------------------------------------------------------------------
    # 迁移以属主身份执行（MIGRATION_DATABASE_URL），有权限建扩展；
    # `IF NOT EXISTS` 保证幂等。
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ------------------------------------------------------------------
    # 1. 版本注册表 —— `content_hash` 唯一（同内容不可重复发布，§12.2）
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.semantic_bundle (
            version       text PRIMARY KEY,
            status        text NOT NULL
                          CHECK (status IN ('draft', 'candidate', 'published', 'staged')),
            content_hash  text NOT NULL UNIQUE,
            published_at  timestamptz NOT NULL DEFAULT now(),
            published_by  text NOT NULL
        )
        """
    )

    # ------------------------------------------------------------------
    # 2. 八张物化表（全部以 bundle_version 为复合主键前缀）
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.asset (
            bundle_version  text        NOT NULL REFERENCES app.semantic_bundle (version),
            logical_name    text        NOT NULL,
            physical_asset  text        NOT NULL,
            grain           text        NOT NULL,
            domain          text        NOT NULL,
            owner           text        NOT NULL,
            certified       boolean     NOT NULL,
            quality_score   real        NOT NULL,
            tenant_scoped   boolean     NOT NULL,
            row_estimate    bigint      NOT NULL,
            description     text        NOT NULL,
            PRIMARY KEY (bundle_version, logical_name)
        )
        """
    )
    # 部分索引：检索与 gate 只查 certified 资产（§12.2）
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_asset_certified "
        "ON app.asset (bundle_version, logical_name) WHERE certified"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.metric_def (
            bundle_version       text  NOT NULL REFERENCES app.semantic_bundle (version),
            name                 text  NOT NULL,
            expression           text,
            default_aggregation  text,
            unit                 text,
            owner                text,
            definition_note      text,
            time_basis           text,
            status               text NOT NULL DEFAULT 'active',
            default_binding      jsonb,
            PRIMARY KEY (bundle_version, name)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.dimension (
            bundle_version  text   NOT NULL REFERENCES app.semantic_bundle (version),
            name            text   NOT NULL,
            binding         text,
            bindings        jsonb,
            hierarchy       text[] NOT NULL DEFAULT '{}',
            grain_levels    jsonb  NOT NULL,
            grain_level     integer NOT NULL,
            value_map       jsonb,
            note            text,
            PRIMARY KEY (bundle_version, name)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.field_binding (
            bundle_version   text NOT NULL REFERENCES app.semantic_bundle (version),
            concept          text NOT NULL,
            ambiguous        boolean NOT NULL DEFAULT false,
            canonical_asset  text,
            default_reason   text,
            time_semantics   text,
            grain_level      integer,
            payload          jsonb NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (bundle_version, concept)  -- 偏差 1，见文件头
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_field_binding_concept "
        "ON app.field_binding (bundle_version, concept)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.join_path (
            bundle_version  text   NOT NULL REFERENCES app.semantic_bundle (version),
            left_ref        text   NOT NULL,
            right_ref       text   NOT NULL,
            join_type       text   NOT NULL,
            on_columns      text[] NOT NULL DEFAULT '{}',
            certified_by    text   NOT NULL,
            note            text,
            PRIMARY KEY (bundle_version, left_ref, right_ref, join_type)
        )
        """
    )
    # 双向查询索引（§12.2：BFS 图扩展从任一端进入）
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_join_path_left ON app.join_path (bundle_version, left_ref)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_join_path_right ON app.join_path (bundle_version, right_ref)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.synonym (
            bundle_version  text NOT NULL REFERENCES app.semantic_bundle (version),
            term            text NOT NULL,
            lang            text NOT NULL,
            maps_to_kind    text NOT NULL,
            maps_to_ref     text NOT NULL,
            category        text NOT NULL,
            tsv             tsvector,
            PRIMARY KEY (bundle_version, term, lang, maps_to_kind, maps_to_ref)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_synonym_tsv ON app.synonym USING gin (tsv)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.policy (
            bundle_version    text  NOT NULL REFERENCES app.semantic_bundle (version),
            scope             text  NOT NULL,
            deny_columns      text[] NOT NULL DEFAULT '{}',
            applies_to_roles  text[] NOT NULL DEFAULT '{}',
            mask_rules        jsonb NOT NULL DEFAULT '[]'::jsonb,
            note              text,
            PRIMARY KEY (bundle_version, scope)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.default_predicate (
            bundle_version  text  NOT NULL REFERENCES app.semantic_bundle (version),
            domain          text  NOT NULL,
            predicates      jsonb NOT NULL DEFAULT '[]'::jsonb,
            PRIMARY KEY (bundle_version, domain)
        )
        """
    )

    # ------------------------------------------------------------------
    # 3. embed_doc —— 四路检索的物理载体（§12.2）
    # ------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS app.embed_doc (
            doc_id         text PRIMARY KEY,
            bundle_version text NOT NULL REFERENCES app.semantic_bundle (version),
            tenant_id      text NOT NULL DEFAULT '*',
            kind           text NOT NULL
                           CHECK (kind IN ('asset', 'column', 'metric', 'synonym', 'gold_query')),
            ref            text NOT NULL,
            text           text NOT NULL,
            tsv            tsvector,
            embedding      vector({EMBEDDING_DIM})
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_embed_doc_lookup "
        "ON app.embed_doc (bundle_version, tenant_id, kind)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_embed_doc_tsv ON app.embed_doc USING gin (tsv)"
    )
    # HNSW 向量索引：空列也能建（PG 允许全 NULL 列上的索引），
    # 向量回填后自动生效 —— 不需要"等有向量再建索引"的第二条迁移。
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_embed_doc_hnsw "
        "ON app.embed_doc USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # ------------------------------------------------------------------
    # 4. 权限（最小化，**逐表**）
    # ------------------------------------------------------------------
    # ⚠️ **禁止** `GRANT ... ON ALL TABLES IN SCHEMA app`：那会把 0001 刚显式
    # REVOKE 掉的 `audit_log` UPDATE/DELETE 又授回去 —— append-only 第①层当场失效，
    # 且不会有任何报错（权限层的失效方式就是静默）。语义层自己的表逐表授权。
    _SEMANTIC_TABLES = (
        "app.semantic_bundle", "app.asset", "app.metric_def", "app.dimension",
        "app.field_binding", "app.join_path", "app.synonym", "app.policy",
        "app.default_predicate", "app.embed_doc",
    )
    _TABLE_LIST = ", ".join(_SEMANTIC_TABLES)
    # app_rw：物化写入 + 版本管理（发布期操作）
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_TABLE_LIST} TO app_rw")
    # app_ro：检索只读（W2B 的 SQL 层查询走 analytics 池）
    op.execute(f"GRANT SELECT ON {_TABLE_LIST} TO app_ro")
    # ⚠️ 业务视图（v_order_paid 等）的 GRANT SELECT(col) 不在这里 ——
    # 它们由语义包**派生**（ADR-10），在发布事务里执行（materialize.py），绝不手写。


def downgrade() -> None:
    # 07 §12.6：只写 up，不写 down（同 0001 的裁定）。
    pass
