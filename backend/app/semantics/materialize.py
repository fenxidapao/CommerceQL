"""语义层物化与版本切换（07 §6.2 / §12.2 / ADR-10）—— DoD②③ 的实现体。

归属窗口：W2A（docs/08 §4.1）。

**发布流程（§6.2 六步，本模块实现其全部机器动作）**：

| 步 | 动作 | 本模块 |
|---|---|---|
| ① | 单事务写入新版本全部物化行 + 计算 tsv + 写入向量 | `materialize()` |
| ② | 同事务：派生并执行 GRANT/POLICY（**绝不手写**，ADR-10） | `derive_policy_statements()` + `with_policy=True` |
| ③ | 提交 → status=staged | 同上（`semantic_bundle.status`） |
| ④ | 建向量/GIN 索引 | 迁移 0002 已建（空列可建索引，回填后自动生效） |
| ⑤ | **原子切换**：Redis 单键 `semantic:active_version` 一次 SET | `switch_version()`（键由调用方传 `cache.keys.active_version()`，R-DEP-1 禁 semantics→cache） |
| ⑥ | 旧版本保留 7 天可回滚 | `rollback_to()`（清理 job 归 W7） |

**确定性纪律**：`derive_policy_statements()` 是**纯函数**（N-03）—— 同一语义包
恒产出同一语句集，逐字节可 diff。这是 DoD③ 一致性测试的前提。

**诚实边界（不得当作已完成）**：
- `tokenizer=None` → tsv 列 NULL + 警告（稀疏检索不可用，**如实降级**，
  不写空串冒充已分词）；`embedder=None` → embedding NULL + 警告。
  两者分别由 W2B（tokenizer）与 W2B/W7（embedding 客户端）交付后注入。
- **RLS 落点缺口（待架构裁决）**：§13.3 模板对 `v_*` 视图 `ALTER TABLE ... ENABLE
  ROW LEVEL SECURITY`，但 PG 的 RLS **只适用于表，不适用于视图**（视图靠
  SECURITY INVOKER 透传底层表的 RLS）。本模块按模板**逐字派生**语句；
  真实落点（底层基表 or 认证物化表）须架构窗口裁定后调整派生规则 ——
  已列入 W2A RELAY 待裁决清单。
- **`embed_doc.tenant_id` 语义**：全局语义文档写 `'*'`；租户私有 gold_query
  文档的分区方式由 W2B 落检索 SQL 时定（本模块不发明）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import psycopg

from app.semantics.loader import LoadedBundle
from app.semantics.models import Asset

__all__ = [
    "MaterializeReport",
    "PolicyStatementSet",
    "assert_grant_policy_consistency",
    "content_sha256",
    "derive_policy_statements",
    "get_active_version",
    "materialize",
    "rollback_to",
    "switch_version",
]

#: 全局文档的租户占位（见文件头"诚实边界"）。
_GLOBAL_TENANT: Final[str] = "*"

#: 发布者署名（版本注册表 `published_by`）。
_PUBLISHED_BY: Final[str] = "w2a-materialize"

#: 业务对象的 schema 名（0001/0002/0003 迁移与 `repo/health.py` 均用 `app`）。
#: ⚠️ 目前无共享单一真相（`app/core/**` 未定义该常量）—— 本模块自持一份并把它用于
#: **所有**派生语句的 schema 限定（2026-09-17 根修，见 `_qualify()`）。
#: 已在 `reports/w2a/RELAY.md` §8 提请 W0 立共享常量；届时此处改指它，不新增第二份。
_SCHEMA: Final[str] = "app"


# ============================================================================
# 内容指纹
# ============================================================================

def content_sha256(path: str | Path) -> str:
    """语义包文件的 sha256（版本注册表 `content_hash` —— 同内容不可重复发布）。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ============================================================================
# ADR-10：策略语句**由语义包派生**（纯函数，绝不手写）
# ============================================================================

def _q_ident(name: str) -> str:
    """标识符加引号（列名/表名来自语义包，防御性引注 —— 不做值注入面）。"""
    return '"' + name.replace('"', '""') + '"'


@dataclass(frozen=True, slots=True)
class PolicyStatementSet:
    """派生出的语句集（执行顺序 = 字段顺序，不可换）。"""

    revoke_sql: tuple[str, ...]
    grant_sql: tuple[str, ...]
    rls_sql: tuple[str, ...]      # ENABLE/FORCE RLS
    policy_sql: tuple[str, ...]   # CREATE POLICY（幂等 DO 块）

    def all_statements(self) -> tuple[str, ...]:
        return self.revoke_sql + self.grant_sql + self.rls_sql + self.policy_sql


def _policy_name(physical_asset: str) -> str:
    return f"p_{physical_asset}_tenant"


def _base_table(physical_asset: str) -> str:
    """资产物理名（认证视图 `v_X`）→ 基表名（`X`）。

    ⚠️ **v0.9（U-55 裁定 (a)）**：PG 的 RLS 只能建在**表**上（视图上建 = `42809`）。
    本项目的防线形态（§13.3 v0.9 三个硬前提）：RLS/POLICY 落**基表**；
    视图保持默认 owner 语义（**禁止 security_invoker**）+ `app_ro` 对基表**零 GRANT**
    —— 视图是唯一入口，列白名单（CLS）仍在视图上授。非 `v_` 前缀资产按原样返回
    （那类资产本身就是表，RLS 直接落它）。
    """
    return physical_asset[2:] if physical_asset.startswith("v_") else physical_asset


def _qualify(object_name: str) -> str:
    """业务对象名 → **schema 限定**名（`app."v_order_paid"`）。

    ⚠️ **2026-09-17（W1B → W2A 转述 §8.2 的根修）**：派生语句原为**非限定名**
    （`REVOKE ALL ON "v_order_paid"`），依赖连接的 `search_path` 才能解析到 `app`。
    调用侧（集成测试的 `_RW`、运维脚本）不带 `search_path` → 直接 `UndefinedTable`
    （层① 视图不存在被 U-56/迁移 0003 解除后，**这一层才暴露**——此前是 skip 盖住了）。
    两处坏在同一个原因上：**非限定名 = 把"连上来的人恰好有对的 search_path"当默认前提**。
    修法取根修而非约定调用侧（后者把同一前提散到每个调用点，漏一处就复现）。
    """
    return f"{_SCHEMA}.{_q_ident(object_name)}"


def derive_policy_statements(loaded: LoadedBundle) -> PolicyStatementSet:
    """从语义包派生 CLS（GRANT SELECT(col)）与 RLS（CREATE POLICY）语句集。

    规则来源：§13.3（**v0.9 U-55 重写版**：RLS 落基表 / 视图 owner 语义 / 基表零 GRANT）
    + 语义包 `policies[].deny_columns` / `assets[].tenant_scoped` / `assets[].columns`。
    **任何一条语句都不能脱离本函数被手写** —— 这正是 ADR-10"双保险"里
    应用侧白名单与 DB 侧 GRANT 同源的机制。

    ⚠️ 所有对象名**必须 schema 限定**（见 `_qualify()` 的注释）——单测有锁定断言。
    """
    revoke: list[str] = []
    grant: list[str] = []
    rls: list[str] = []
    policies: list[str] = []

    for asset in loaded.active_assets.values():
        cols = loaded.allowlist.get(asset.physical_asset)
        if cols is None:
            continue  # 整资产被 deny 清空（loader 已 WARN），不授任何列
        quoted = _qualify(asset.physical_asset)
        revoke.append(f"REVOKE ALL ON {quoted} FROM PUBLIC;")
        # CLS：只授允许列（deny_columns 已被 loader 剔除）—— §13.3「只授允许列」。
        # ⚠️ 授在**视图**上（视图 = app_ro 唯一入口；基表对 app_ro 零 GRANT，U-55 前提 2）。
        grant.append(
            f"GRANT SELECT ({', '.join(_q_ident(c) for c in cols)}) "
            f"ON {quoted} TO app_ro;"
        )
        if asset.tenant_scoped:
            # RLS：模板 §13.3（v0.9）。目标 = **基表**（U-55 (a)：视图上建 RLS 会 42809）。
            # 缺省 GUC = 失败关闭（current_setting 第二参 true → NULL → 行全滤）；
            # `app.shop_ids` 空串 = 不限店铺（**不能用 NULL** —— NULL 会把所有行滤光）。
            base = _qualify(_base_table(asset.physical_asset))
            rls.append(f"ALTER TABLE {base} ENABLE ROW LEVEL SECURITY;")
            rls.append(f"ALTER TABLE {base} FORCE ROW LEVEL SECURITY;")
            if asset.has_column("shop_id"):
                using = (
                    "tenant_id = current_setting('app.tenant_id', true) "
                    "AND (current_setting('app.shop_ids', true) = '' "
                    "OR shop_id = ANY (string_to_array(current_setting('app.shop_ids', true), ',')))"
                )
            else:
                using = "tenant_id = current_setting('app.tenant_id', true)"
            pname = _policy_name(_base_table(asset.physical_asset))
            policies.append(
                f"""DO $$
BEGIN
  DROP POLICY IF EXISTS {_q_ident(pname)} ON {base};
  CREATE POLICY {_q_ident(pname)} ON {base}
    USING ({using});
END $$;"""
            )
    return PolicyStatementSet(
        revoke_sql=tuple(revoke),
        grant_sql=tuple(grant),
        rls_sql=tuple(rls),
        policy_sql=tuple(policies),
    )


# ============================================================================
# 检索文档（embed_doc 的确定性组装）
# ============================================================================

def _doc_text_asset(asset: Asset) -> str:
    parts = [asset.logical_name, asset.description, f"粒度 {asset.grain}", f"域 {asset.domain}"]
    cols = "；".join(
        f"{c.name}({c.type})" + (f" {c.comment}" if c.comment else "") for c in asset.columns
    )
    parts.append(f"列：{cols}")
    return " ".join(p for p in parts if p)


def _doc_text_column(asset: Asset, name: str, comment: str | None, synonyms: Sequence[str]) -> str:
    parts = [f"{asset.logical_name}.{name}"]
    if comment:
        parts.append(comment)
    if synonyms:
        parts.append("同义词 " + " ".join(synonyms))
    return " ".join(parts)


def _doc_text_metric(name: str, display: str, expression: str | None, note: str | None) -> str:
    parts = [name, display]
    if expression:
        parts.append(expression)
    if note:
        parts.append(note)
    return " ".join(parts)


def _build_docs(loaded: LoadedBundle) -> list[dict[str, str]]:
    """embed_doc 行（kind ∈ asset|column|metric|synonym；gold_query 由 W2B/W6 追加）。"""
    docs: list[dict[str, str]] = []
    version = loaded.version
    for asset in loaded.active_assets.values():
        docs.append({
            "kind": "asset", "ref": asset.logical_name, "text": _doc_text_asset(asset),
        })
        for col in asset.columns:
            docs.append({
                "kind": "column", "ref": f"{asset.logical_name}.{col.name}",
                "text": _doc_text_column(asset, col.name, col.comment, col.synonyms),
            })
    for m in loaded.bundle.metrics:
        docs.append({
            "kind": "metric", "ref": m.name,
            "text": _doc_text_metric(m.name, m.display_name, m.expression, m.definition_note),
        })
    for a in loaded.bundle.aliases:
        docs.append({
            "kind": "synonym", "ref": a.term,
            "text": f"{a.term} → {a.maps_to_kind}:{a.maps_to_ref}",
        })
    for d in docs:
        d["doc_id"] = f"{version}:{d['kind']}:{d['ref']}"
    return docs


# ============================================================================
# 物化（单事务，§6.2 步骤①②③）
# ============================================================================

@dataclass(frozen=True, slots=True)
class MaterializeReport:
    """发布动作的结果（含**如实降级**记录 —— 调用方必须透出，不得吞）。"""

    version: str
    content_hash: str
    rows: dict[str, int] = field(default_factory=dict)
    doc_count: int = 0
    #: "embedded" | "pending_embedder" —— pending = embedding NULL，**不是通过**
    embedding_status: str = "pending_embedder"
    #: "tokenized" | "pending_tokenizer" —— pending = tsv NULL，稀疏检索不可用
    tsv_status: str = "pending_tokenizer"
    #: GRANT/POLICY 是否已在本事务执行（with_policy=False 时为 False，**不是跳过=通过**）
    grant_policy_executed: bool = False
    statements: PolicyStatementSet | None = None
    warnings: tuple[str, ...] = ()


def _insert_rows(
    cur: psycopg.Cursor[Any],
    loaded: LoadedBundle,
    *,
    content_hash: str,
    docs: list[dict[str, str]],
    tokenizer: Callable[[str], list[str]] | None,
    embedder: Callable[[list[str]], list[list[float]]] | None,
) -> tuple[dict[str, int], str, str, list[str]]:
    """事务内写入全部物化行。返回 (行数, tsv_status, embedding_status, warnings)。"""
    b = loaded.bundle
    warnings: list[str] = []
    version = loaded.version

    # 版本注册表（status=staged：数据就绪、尚未服务 —— §6.2 步骤③）
    cur.execute(
        """
        INSERT INTO app.semantic_bundle (version, status, content_hash, published_by)
        VALUES (%s, 'staged', %s, %s)
        ON CONFLICT (version) DO UPDATE
          SET status = EXCLUDED.status, content_hash = EXCLUDED.content_hash,
              published_at = now(), published_by = EXCLUDED.published_by
        """,
        (version, content_hash, _PUBLISHED_BY),
    )
    # 幂等重发布：清掉旧行再插（全在一个事务里，失败整体回滚）
    for table in ("asset", "metric_def", "dimension", "field_binding", "join_path",
                  "synonym", "policy", "default_predicate", "embed_doc"):
        cur.execute(f"DELETE FROM app.{table} WHERE bundle_version = %s", (version,))

    counts: dict[str, int] = {}
    for a in loaded.active_assets.values():
        cur.execute(
            """
            INSERT INTO app.asset (bundle_version, logical_name, physical_asset, grain,
                domain, owner, certified, quality_score, tenant_scoped, row_estimate, description)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (version, a.logical_name, a.physical_asset, a.grain, a.domain, a.owner,
             a.certified, a.quality_score, a.tenant_scoped, a.row_estimate, a.description),
        )
    counts["asset"] = len(loaded.active_assets)

    for m in b.metrics:
        cur.execute(
            """
            INSERT INTO app.metric_def (bundle_version, name, expression, default_aggregation,
                unit, owner, definition_note, time_basis, status, default_binding)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (version, m.name, m.expression, m.default_aggregation, m.unit, m.owner,
             m.definition_note, m.time_basis, m.status,
             json.dumps({"asset": m.default_binding.asset, "reason": m.default_binding.reason},
                        ensure_ascii=False) if m.default_binding else None),
        )
    counts["metric_def"] = len(b.metrics)

    for d in b.dimensions:
        cur.execute(
            """
            INSERT INTO app.dimension (bundle_version, name, binding, bindings, hierarchy,
                grain_levels, grain_level, value_map, note)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (version, d.name, d.binding,
             json.dumps(d.bindings, ensure_ascii=False) if d.bindings else None,
             list(d.hierarchy), json.dumps(d.grain_levels), d.grain_level,
             json.dumps(d.value_map, ensure_ascii=False) if d.value_map else None, d.note),
        )
    counts["dimension"] = len(b.dimensions)

    for fb in b.field_bindings:
        payload: dict[str, Any] = {
            "candidates": [c.__dict__ for c in fb.candidates],
            "alternatives": [x.__dict__ for x in fb.alternatives],
        }
        if fb.clarify_prompt:
            payload["clarify_prompt"] = fb.clarify_prompt
        cur.execute(
            """
            INSERT INTO app.field_binding (bundle_version, concept, ambiguous, canonical_asset,
                default_reason, time_semantics, grain_level, payload)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (version, fb.concept, fb.ambiguous, fb.canonical_asset, fb.default_reason,
             fb.time_semantics, fb.grain_level, json.dumps(payload, ensure_ascii=False)),
        )
    counts["field_binding"] = len(b.field_bindings)

    for j in b.joins:
        cur.execute(
            """
            INSERT INTO app.join_path (bundle_version, left_ref, right_ref, join_type,
                on_columns, certified_by, note)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,
            (version, j.left, j.right, j.type, list(j.on_columns), j.certified_by, j.note),
        )
    counts["join_path"] = len(b.joins)

    # synonym：tsv 由注入的分词器计算（N-24：写入侧与查询侧必须同源）
    for al in b.aliases:
        terms = tokenizer(al.term) if tokenizer else None
        cur.execute(
            """
            INSERT INTO app.synonym (bundle_version, term, lang, maps_to_kind, maps_to_ref,
                category, tsv)
            VALUES (%s,%s,%s,%s,%s,%s,
                    CASE WHEN %s::text IS NULL THEN NULL
                         ELSE to_tsvector('simple', %s::text) END)
            """,
            (version, al.term, al.lang, al.maps_to_kind, al.maps_to_ref, al.category,
             terms, " ".join(terms) if terms else None),
        )
    counts["synonym"] = len(b.aliases)

    for i, policy in enumerate(b.policies):
        cur.execute(
            """
            INSERT INTO app.policy (bundle_version, scope, deny_columns, applies_to_roles,
                mask_rules, note)
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (version, f"bundle_policy_{i}", list(policy.deny_columns),
             list(policy.applies_to_roles),
             json.dumps([{"column_pattern": r.column_pattern, "rule": r.rule}
                         for r in policy.mask_rules], ensure_ascii=False),
             policy.note),
        )
    counts["policy"] = len(b.policies)

    for domain, dps in b.default_predicates.items():
        cur.execute(
            """
            INSERT INTO app.default_predicate (bundle_version, domain, predicates)
            VALUES (%s,%s,%s)
            """,
            (version, domain,
             json.dumps([{"id": p.id, "predicate": p.predicate, "reason": p.reason,
                          "owner": p.owner} for p in dps], ensure_ascii=False)),
        )
    counts["default_predicate"] = len(b.default_predicates)

    # embed_doc：tsv / embedding 依赖注入（缺 → NULL + 如实降级）
    texts = [d["text"] for d in docs]
    tsv_terms: list[str | None] | None = None
    if tokenizer is not None:
        tsv_terms = [" ".join(tokenizer(t)) for t in texts]
    else:
        warnings.append("tsv 未物化（tokenizer 未注入）—— 稀疏检索不可用（如实降级，非通过）")
    embeddings: list[list[float]] | None = None
    if embedder is not None:
        embeddings = embedder(texts)
        if len(embeddings) != len(texts):
            raise SemanticMaterializeError(
                f"embedder 返回 {len(embeddings)} 条向量，与文档数 {len(texts)} 不一致"
            )
    else:
        warnings.append("embedding 未物化（embedder 未注入）—— 稠密检索不可用（如实降级，非通过）")

    for i, doc in enumerate(docs):
        tsv_text = tsv_terms[i] if tsv_terms is not None else None
        emb = embeddings[i] if embeddings is not None else None
        emb_literal = "[" + ",".join(f"{x:.8g}" for x in emb) + "]" if emb else None
        cur.execute(
            """
            INSERT INTO app.embed_doc (doc_id, bundle_version, tenant_id, kind, ref, text,
                tsv, embedding)
            VALUES (%s,%s,%s,%s,%s,%s,
                    CASE WHEN %s::text IS NULL THEN NULL
                         ELSE to_tsvector('simple', %s::text) END,
                    %s::vector)
            """,
            (doc["doc_id"], version, _GLOBAL_TENANT, doc["kind"], doc["ref"], doc["text"],
             tsv_text, tsv_text, emb_literal),
        )
    counts["embed_doc"] = len(docs)

    tsv_status = "tokenized" if tokenizer is not None else "pending_tokenizer"
    emb_status = "embedded" if embedder is not None else "pending_embedder"
    return counts, tsv_status, emb_status, warnings


class SemanticMaterializeError(Exception):
    """物化过程错误（事务回滚后由调用方处置 —— 不伪装成部分成功）。"""


def materialize(
    loaded: LoadedBundle,
    *,
    dsn: str,
    tokenizer: Callable[[str], list[str]] | None = None,
    embedder: Callable[[list[str]], list[list[float]]] | None = None,
    with_policy: bool = True,
    content_hash: str | None = None,
) -> MaterializeReport:
    """发布一个语义包版本（§6.2 步骤①②③：单事务 + 派生 GRANT/POLICY + staged）。

    `dsn`：**元数据 DSN**（app_rw —— 物化是元数据写，不是业务查询）。
    `with_policy=True`（默认，§6.2 步骤②）时 GRANT/POLICY 在**同一事务**内执行：
    业务视图缺失/语句失败 → 整体回滚，**绝不出现"行已写入而权限没跟上"的半态**。
    """
    stmts = derive_policy_statements(loaded)
    docs = _build_docs(loaded)
    warnings: list[str] = []

    with (
        psycopg.connect(dsn, connect_timeout=5) as conn,
        conn.transaction(),
        conn.cursor() as cur,
    ):
        counts, tsv_status, emb_status, tx_warnings = _insert_rows(
            cur, loaded, content_hash=content_hash or "", docs=docs,
            tokenizer=tokenizer, embedder=embedder,
        )
        warnings.extend(tx_warnings)
        if with_policy:
            for stmt in stmts.all_statements():
                cur.execute(stmt)
        else:
            warnings.append(
                "GRANT/POLICY 未执行（with_policy=False）—— 本版本未完成 §6.2 步骤②"
            )

    return MaterializeReport(
        version=loaded.version,
        content_hash=content_hash or "",
        rows=counts,
        doc_count=len(docs),
        embedding_status=emb_status,
        tsv_status=tsv_status,
        grant_policy_executed=with_policy,
        statements=stmts,
        warnings=tuple(warnings),
    )


# ============================================================================
# 单键指针（§6.2 步骤⑤⑥：一次 SET 的原子性；旧版本保留可回滚）
# ============================================================================

def switch_version(redis_client: Any, version: str, *, key: str) -> None:
    """原子切换活动版本 —— Redis 单键一次 SET。

    ⚠️ `key` **必须**由调用方传 `app.cache.keys.active_version()`（W0 单一真相，
    R-DEP-1 禁止 semantics 直接 import cache —— 键定义不落地第二份）。
    ⚠️ 所有含 `bundle_version` 的缓存键靠指针变化**自然失效**（不遍历删缓存）；
    残留旧键由 TTL + 惰性清理（§6.2 的取舍，刻意如此）。
    """
    redis_client.set(key, version)


def get_active_version(redis_client: Any, *, key: str) -> str | None:
    """读当前指针（`key` 同上，调用方传 `cache_keys.active_version()`）。

    None = 尚未发布过任何版本（**如实返回，不猜**）。
    """
    val = redis_client.get(key)
    return None if val is None else str(val)


def rollback_to(redis_client: Any, dsn: str, target_version: str, *, key: str) -> None:
    """回滚指针到旧版本（§6.2 步骤⑥：旧版本保留 7 天 → 数据仍在，回滚 = 指针指回去）。

    ⚠️ 目标版本必须仍存在于版本注册表 —— 数据被清理后指针**不得**指回空版本。
    `key` 同上（调用方传 `cache_keys.active_version()`）。
    """
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        row = conn.execute(
            "SELECT 1 FROM app.semantic_bundle WHERE version = %s", (target_version,)
        ).fetchone()
    if row is None:
        raise SemanticMaterializeError(
            f"回滚目标版本 {target_version!r} 不存在（已过保留期或从未发布）"
            " —— 指针不得指向不存在的版本"
        )
    switch_version(redis_client, target_version, key=key)


# ============================================================================
# DoD③ 一致性检查：应用白名单 == DB 实际 GRANT/POLICY（ADR-10）
# ============================================================================

@dataclass(frozen=True, slots=True)
class ConsistencyReport:
    """DoD③ 检查结果。`mismatches` 非空 = 不一致（**必须红**，不得静默）。"""

    version: str
    checked_assets: int
    mismatches: tuple[str, ...] = ()

    @property
    def consistent(self) -> bool:
        return not self.mismatches


def assert_grant_policy_consistency(conn: psycopg.Connection[Any], loaded: LoadedBundle) -> ConsistencyReport:
    """逐资产比对：应用侧 allowlist ↔ DB 实际列级 GRANT；tenant_scoped ↔ 实际 POLICY。

    检查方式（ADR-10 验证）：以 `app_ro` 视角问 `information_schema` / `pg_policies`，
    **双向**比对 —— 少授了（检索不可用）与多授了（**越权**）都算不一致。
    """
    mismatches: list[str] = []
    for asset in loaded.active_assets.values():
        expected_cols = set(loaded.allowlist.get(asset.physical_asset, ()))
        # 实际：app_ro 在该对象上持有的**列级** SELECT 权限
        rows = conn.execute(
            """
            SELECT column_name FROM information_schema.role_column_grants
            WHERE grantee = 'app_ro' AND table_schema = 'app' AND table_name = %s
            """,
            (asset.physical_asset,),
        ).fetchall()
        granted_cols = {r[0] for r in rows}
        # 整表级 SELECT（非列级）也算"多授" —— 它绕过了 CLS
        table_wide = conn.execute(
            """
            SELECT count(*) FROM information_schema.role_table_grants
            WHERE grantee = 'app_ro' AND table_schema = 'app' AND table_name = %s
              AND privilege_type = 'SELECT'
            """,
            (asset.physical_asset,),
        ).fetchone()
        has_table_grant = bool(table_wide and table_wide[0])

        if has_table_grant:
            mismatches.append(
                f"{asset.physical_asset}: app_ro 持有**整表** SELECT（绕过列白名单，ADR-10 红线）"
            )
            continue
        missing = expected_cols - granted_cols
        extra = granted_cols - expected_cols
        if missing:
            mismatches.append(f"{asset.physical_asset}: 缺少列授权 {sorted(missing)}")
        if extra:
            mismatches.append(
                f"{asset.physical_asset}: app_ro 被多授了白名单外的列 {sorted(extra)}"
                "（deny_columns 失效 = 越权读取面）"
            )

        # ⚠️ v0.9（U-55 (a) 前提 2）：app_ro 对**基表**必须零 GRANT —— 视图是唯一入口。
        # 缺了这条检查，"手滑给基表授权"会静默绕过 CLS（RLS 仍挡行，但列白名单失效），
        # 而本检查器不会红 —— 正是 ADR-10 要拦的"两侧漂移"。基表未建时查询空返回 = 空洞放行，
        # 属"前置未就绪"而非"已验证零授权"（与 skip 纪律一致，由 U-56 迁移就绪后转为真检查）。
        base = _base_table(asset.physical_asset)
        if base != asset.physical_asset:
            base_cols = conn.execute(
                """
                SELECT column_name FROM information_schema.role_column_grants
                WHERE grantee = 'app_ro' AND table_schema = 'app' AND table_name = %s
                """,
                (base,),
            ).fetchall()
            base_tables = conn.execute(
                """
                SELECT count(*) FROM information_schema.role_table_grants
                WHERE grantee = 'app_ro' AND table_schema = 'app' AND table_name = %s
                """,
                (base,),
            ).fetchone()
            leaked = {r[0] for r in base_cols}
            if leaked or (base_tables and base_tables[0]):
                mismatches.append(
                    f"{asset.physical_asset}: app_ro 对基表 {base} 持有授权"
                    f"（列 {sorted(leaked) if leaked else '整表'}）"
                    " —— U-55(a) 前提 2 被破坏，CLS 可经基表绕过"
                )

        if asset.tenant_scoped:
            # ⚠️ v0.9（U-55 (a)）：策略在**基表**上（派生侧与检查侧必须同变，防两侧漂移）
            base = _base_table(asset.physical_asset)
            pname = _policy_name(base)
            prow = conn.execute(
                """
                SELECT count(*) FROM pg_policies
                WHERE schemaname = 'app' AND tablename = %s AND policyname = %s
                """,
                (base, pname),
            ).fetchone()
            if not prow or not prow[0]:
                mismatches.append(
                    f"{asset.physical_asset}: tenant_scoped=true 但基表 {base} 上 RLS 策略 "
                    f"{pname} 不存在（行级边界缺失 = 跨租户泄露面）"
                )
        else:
            base = _base_table(asset.physical_asset)
            pname = _policy_name(base)
            prow = conn.execute(
                """
                SELECT count(*) FROM pg_policies
                WHERE schemaname = 'app' AND tablename = %s AND policyname = %s
                """,
                (base, pname),
            ).fetchone()
            if prow and prow[0]:
                mismatches.append(
                    f"{asset.physical_asset}: tenant_scoped=false 但基表 {base} 上存在租户策略 "
                    f"{pname}（策略与声明相反）"
                )

    return ConsistencyReport(
        version=loaded.version,
        checked_assets=len(loaded.active_assets),
        mismatches=tuple(mismatches),
    )
