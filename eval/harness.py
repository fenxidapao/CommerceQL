"""评测装配台 —— 把**在线**代码装配成可离线跑一次的 harness（W6 / ADR-18）。

归属窗口：W6（docs/08 §4.1：`eval/**` 的**执行器**部分）。

--------------------------------------------------------------------------
一、评测跑的是真图，不是评测专用的简化流程
--------------------------------------------------------------------------
本模块的产物是一个 `GraphDeps` + `build_graph()` 的真图（19 节点、14 条条件边），
逐节点与 `app/api/deps.py::build_graph_runtime` 的装配点同构。差异只有四处，
每一处都是**沙箱能力**造成的，不是图方便：

| 装配点 | 生产 | 评测 | 为什么 |
|---|---|---|---|
| `executor` | `PgSqlExecutor(analytics 池)` | `SqliteEvalExecutor`（继承它） | 沙箱无 PG 业务数据（D2 / §17.4） |
| `semantics` | `SemanticBundleRuntime` | `GuardAllowlistBundle`（薄代理） | `asset_allowlist` 形状缺陷，见 §三 |
| `retrieval` | `RetrievalService`（pgvector + tsvector） | `BundleCatalogRetrieval`（全目录夹具） | §17.4 明文"评测不测向量检索"，见 §四 |
| `audit` / `query_plan_writer` / `result_cache` / `presenter` | PG/Redis/W3B | 内存替身 / `None` | 评测不产出生产审计行；`None` 走的是**已登记的降级路径**（同生产 P0 的 `presenter=None`） |

**不接 SSE 面**：评测驱动 `graph.astream`，读**最终 state**（`terminal` / `outcome` /
`gate_results` / `sql_text` / `result_rows` …），不构造 `EventRecorder`。
帧契约由 W4 的 `tests/contract/` 把守，评测的判定对象是"这一轮答得对不对"。

--------------------------------------------------------------------------
二、LLM 出站：匣带，不是替身
--------------------------------------------------------------------------
`live=False + cassette=` 时注入 `CassetteTransport`（`ChatClient(transport=…)`），
其余（路由、退避、熔断、计量、schema 校验、repair）全是 `app.llm` 本尊。
`live=True` 时真打上游并（可选）录制。⚠️ 密钥只从**环境**读，本模块不打印、不落盘。

--------------------------------------------------------------------------
三、闸门 allowlist 适配器（W2A↔W2C↔W4 的形状缺口，评测侧临时补齐）
--------------------------------------------------------------------------
`app/guard/ast_gate.py` 头部把 allowlist 契约写成一个**包装字典**
（`assets` / `joins` / `deny_columns` / `default_predicates` / …），
而 `SemanticBundleRuntime.asset_allowlist(ctx)` 返回的是**扁平表**且
`columns` 是元组 —— 两者不匹配。实测（`reports/w6/probe_gate_allowlist_shape.py`）：
把运行时直接交给 `run_gate1` → **任何**查询都被 R05 拒；`run_gate2` → G2-ASSET 拒。
生产装配点（`app/api/deps.py` 的 `semantics=semantic_runtime`）没有做这层转换
⇒ **闸门在生产里今天对每条查询都不生效**（不是"偶尔漏"，是"全拒"）。

🔴 而且这个端口有**两个形状互斥的消费者**，所以"改成 wrapper"并不是一个字符就能修的事：
`planner/payloads.build_semantic_summary` 与 `binding/filters._step_no_permission`
消费的是**扁平**形态（`for physical in sorted(allowlist)` + `allowlist[physical]`）——
实测把 wrapper 直接给端口会让 planner 在 `entry.get(...)` 上抛
`AttributeError: 'str' object has no attribute 'get'`（它把 `bundle_version` 当成了一张表）。

`GuardAllowlistBundle` 因此返回 `AssetAllowlistView`（**双形状视图**，见该类的表格式说明）：
迭代面 = 扁平（planner/binding 的真相不变），`.get(wrapper 键)` = wrapper（闸门可用），
键解析**先扁平后 wrapper** ⇒ 真实资产名永不被保留键遮蔽。
这条生产缺陷作为 RELAY 交给 W2A/W2C/W4/W0（**不由评测窗口去改别人的文件**）。

⚠️ 适配规则只有一条是"造"出来的：`joins[].left/right` 在语义包里是
`<资产>.<列>` 点分形态，而 gate1 要的是**逻辑资产名** → 取点号左侧。
其余键全部逐字取自运行时/`policy()`/`LoadedBundle`。

--------------------------------------------------------------------------
四、检索夹具的口径偏差（必须写进报告的"已知限制"）
--------------------------------------------------------------------------
`BundleCatalogRetrieval` 返回语义包里的**全部**认证资产与列（不带问题相关性），
因此：
· schema linking 对模型来说比生产**更容易**（生产是 hybrid Top-5 资产 / Top-30 列）；
· 由此得到的 EX / 澄清率**偏乐观**，不可外推成"生产检索质量"；
· `mode` 只能填 `SPARSE_ONLY`、`degraded_reason` 只能填 `EMBEDDING_UNAVAILABLE`
  —— `RetrievalMode` 只有 2 个值（C-11），**没有**"目录夹具"这一档。
  这不是"降级描述准确"，而是"没有准确的档可填"：已作为契约缺口登记（待架构窗口分配）。

--------------------------------------------------------------------------
五、身份
--------------------------------------------------------------------------
`role=ANALYST`（`app.core.enums.Role` 无"商家"字面值；ANALYST 在
`policies.applies_to_roles` 内 ⇒ deny 生效，与真实用户同形）、
`shop_ids=()` ⇒ gate2 走 §7.4 分支 3（`tenant_isolated`），与"按租户隔离"的产品语义一致。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import _bootstrap
import sqlglot
from sqlglot import exp

_bootstrap.bootstrap()

from app.auth.context import bind_identity, reset_identity  # noqa: E402
from app.binding.service import BindingService  # noqa: E402
from app.core.clock import Clock  # noqa: E402
from app.core.config import Settings, get_settings  # noqa: E402
from app.core.contracts import CandidateRef, IdentityContext  # noqa: E402
from app.core.enums import ActionTaken, DegradedReason, GateNo, RetrievalMode, Role  # noqa: E402
from app.graph.build import GRAPH_RECURSION_LIMIT, NODE_TIMEOUT_S, build_graph  # noqa: E402
from app.graph.context import (  # noqa: E402
    GraphDeps,
    RunContext,
    clear_run_context,
    set_run_context,
)
from app.graph.state import initial_state  # noqa: E402
from app.llm import build_gateway  # noqa: E402
from app.llm.client import ChatClient  # noqa: E402
from app.mask.engine import SemanticMaskEngine  # noqa: E402
from app.planner.engine import PlannerEngine  # noqa: E402
from app.retrieval.search import RetrievalResult  # noqa: E402
from app.semantics.loader import LoadedBundle, load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402
from cassette import CassetteMiss, CassetteTransport  # noqa: E402
from sqlite_exec import SqliteEvalExecutor  # noqa: E402

__all__ = [
    "BundleCatalogRetrieval",
    "CaseRun",
    "GuardAllowlistBundle",
    "Harness",
    "build_guard_allowlist",
    "describe_node_timeouts",
    "eval_node_timeouts",
    "identity_for_case",
]


# ============================================================================
# 一、闸门 allowlist 适配
# ============================================================================

def build_guard_allowlist(
    loaded: LoadedBundle, runtime: SemanticBundleRuntime, ctx: IdentityContext
) -> dict[str, Any]:
    """按 `ast_gate` 文档契约组装 allowlist（逐字派生自语义包，不做业务发明）。"""

    flat = runtime.asset_allowlist(ctx)  # 运行时自己按 role 裁剪过 deny
    type_by_column: dict[str, dict[str, str]] = {
        asset.physical_asset: {c.name: c.type for c in asset.columns}
        for asset in loaded.bundle.assets
    }
    policy = dict(runtime.policy() or {})

    assets: dict[str, Any] = {}
    for physical, entry in flat.items():
        columns = entry.get("columns") or ()
        known = type_by_column.get(physical, {})
        assets[physical] = {
            "logical_name": entry.get("logical_name"),
            "domain": entry.get("domain"),
            "tenant_scoped": bool(entry.get("tenant_scoped")),
            # 契约要 {列名: 类型}；运行时给的是列名元组 → 类型从资产模型补齐（W2A 未透出类型，
            # 见 reports/w6/RELAY.md：allowlist 形状缺陷的第三小条）。
            "columns": {name: known.get(name, "unknown") for name in columns},
        }

    joins = [
        {
            "left": str(j.left).split(".", 1)[0],
            "right": str(j.right).split(".", 1)[0],
            "on_columns": [str(c) for c in (j.on_columns or ())],
        }
        for j in loaded.bundle.joins
    ]

    return {
        "bundle_version": runtime.active_version(),
        "assets": assets,
        "joins": joins,
        "deny_columns": [str(x) for x in (policy.get("deny_columns") or ())],
        "default_predicates": dict(policy.get("default_predicates") or {}),
        # 语义包**没有** allowed_constants 区块（grep 实证）→ 空表，不编造。
        "allowed_constants": [],
        # `max_rows` **刻意不填**：生产也没给（运行时不透出），R04 因此用
        # `ast_gate.DEFAULT_MAX_ROWS` —— 评测与生产同形，而不是评测私自注入一个数。
    }


#: guard 侧（`ast_gate` / `policy_gate`）从 allowlist 读的**唯一**几个键。
_GUARD_WRAPPER_KEYS: tuple[str, ...] = (
    "bundle_version",
    "assets",
    "joins",
    "deny_columns",
    "default_predicates",
    "allowed_constants",
    "max_rows",
)


class AssetAllowlistView(Mapping):
    """`asset_allowlist(ctx)` 的**双形状视图**（评测侧适配，不改任何生产件）。

    🔴 为什么必须存在（这是一条**上游契约冲突**，不是评测的发明）
    ------------------------------------------------------------------
    `SemanticBundlePort.asset_allowlist(ctx)` 有**两个文档化、但形状互斥**的消费者：

    | 消费者 | 期望形状 | 读取方式 |
    |---|---|---|
    | `planner/payloads.build_semantic_summary`、`binding/filters._step_no_permission` | **扁平** `{物理名: {logical_name, columns, grain, domain, tenant_scoped}}` | `for physical in sorted(allowlist)` + `allowlist[physical]` |
    | `guard/ast_gate.run_gate1`、`guard/policy_gate.run_gate2` | **wrapper** `{assets, joins, deny_columns, default_predicates, allowed_constants, bundle_version, max_rows}`（形状写在其模块 docstring） | 只用 `.get(<wrapper 键>)`（实测全仓无迭代、无 `[]`） |

    真运行时给的是**扁平** ⇒ 生产现状是"planner 正常、gate1 因 `assets` 取不到而把
    **每张表**判 R05"（`probe_gate_allowlist_shape.py` 实证）。也就是：这条冲突不是
    评测能绕过的取舍，而是"闸门今天在生产里根本没生效"。

    本视图的做法：`__getitem__`/`get` **先查扁平再查 wrapper** ⇒ 真实资产名永不被
    保留键遮蔽；`__iter__`/`__len__` **只枚举扁平** ⇒ planner 的 `sorted(allowlist)`、
    `.items()`、`keys()` 看到的仍是"物理名 → 条目"的真相，不会把 `assets` 当成一张表。

    ⚠️ 残余风险（已登记 `reports/w6/RELAY.md`）：若语义包将来出现名为
    `assets` / `joins` / … 的**物理资产**，wrapper 键会被资产条目遮蔽（方向是安全的：
    闸门会因此拿不到判据而**拒绝**，不是放行），届时本类必须换成显式两方法端口。
    正解归属：W0 给端口加第二个方法，**或** W2C 让闸门自己从扁平派生（后者改动面更小）。
    """

    def __init__(self, flat: Mapping[str, Any], wrapper: Mapping[str, Any]) -> None:
        overlap = sorted(set(flat) & set(_GUARD_WRAPPER_KEYS))
        if overlap:
            raise ValueError(
                "物理资产名与 guard 的 wrapper 键冲突，双形状视图无法保证不遮蔽",
                f"（冲突项：{overlap}）",
            )
        self._flat = dict(flat)
        self._wrapper = {k: wrapper[k] for k in _GUARD_WRAPPER_KEYS if k in wrapper}

    def __getitem__(self, key: str) -> Any:
        if key in self._flat:
            return self._flat[key]
        return self._wrapper[key]

    def get(self, key: str, default: Any = None) -> Any:  # 与 __getitem__ 同优先级
        if key in self._flat:
            return self._flat[key]
        return self._wrapper.get(key, default)

    def __contains__(self, key: object) -> bool:
        return key in self._flat or key in self._wrapper

    def __iter__(self):  # 只枚举扁平：见 docstring 的 planner 一致性要求
        return iter(self._flat)

    def __len__(self) -> int:
        return len(self._flat)


class GuardAllowlistBundle:
    """`SemanticBundlePort` 薄代理：只把 `asset_allowlist` 换成 `AssetAllowlistView`。

    其余方法（`active_version` / `policy` / `time_semantics` / L1 查找面 …）
    一律 `__getattr__` 透传给真运行时 —— 代理不许改语义，只许改形状。
    """

    def __init__(self, runtime: SemanticBundleRuntime, loaded: LoadedBundle) -> None:
        self._runtime = runtime
        self._loaded = loaded
        self._cache: dict[str, AssetAllowlistView] = {}

    def asset_allowlist(self, ctx: IdentityContext) -> Mapping[str, Any]:
        key = ctx.role.value
        view = self._cache.get(key)
        if view is None:
            view = AssetAllowlistView(
                self._runtime.asset_allowlist(ctx),
                build_guard_allowlist(self._loaded, self._runtime, ctx),
            )
            self._cache[key] = view
        return view

    def __getattr__(self, name: str) -> Any:  # 透传（含端口未列出的富方法）
        return getattr(self._runtime, name)


def _pred_columns_by_domain(allowlist: Mapping[str, Any]) -> dict[str, set[str]]:
    """域 → 该域全部默认谓词引用的列名（解析失败的谓词 = 跳过，不放大成评测噪音）。"""
    out: dict[str, set[str]] = {}
    for domain, preds in (allowlist.get("default_predicates") or {}).items():
        cols: set[str] = set()
        for pred in preds:
            try:
                node = sqlglot.parse_one(str(pred), dialect="postgres")
            except sqlglot.errors.ParseError:
                continue
            cols.update(c.name for c in node.find_all(exp.Column))
        out[str(domain)] = cols
    return out


def detect_gate_self_defect(sql: str, allowlist: Mapping[str, Any]) -> str | None:
    """这条 SQL 会不会被 **gate1 自身的判据缺陷**（而非模型写错）杀掉。

    为什么这个判据**只能**在评测侧算：
    判定需要同时握着 ① 模型的**原始** SQL（gate1 拒绝时 `rewritten_sql` 恒空串，
    `sql_text` 里是未注入的原文）与 ② 完整 allowlist（资产列集 + 各域默认谓词）。
    生产链路上这两样从不同时出现在一个能记账的地方 —— 而闸门自己不会报告
    "我拒绝是因为我注入了一个不存在的列"。

    为什么必须单独一类：`R06` 有**两种**相反的含义 —— 模型真的编了个列名（模型的责任），
    或闸门注入出不存在的列（策略层的责任）。混计会让 §C.7 的分布把闸门缺陷算进
    `sql_generation`，然后在报告里长成"模型不行"。归因层因此**不猜**，只消费本函数的结论。

    取证：`backend/reports/w6/probe_gate_rejections.py`（F1/F2 两条路径各自隔离复现）。
    """
    text = (sql or "").strip()
    if not text:
        return None
    try:
        tree = sqlglot.parse_one(text, dialect="postgres")
    except sqlglot.errors.ParseError:
        return None  # 语法本身不成立 → 那是模型的账（`sql_generation`）

    findings: list[str] = []

    # ---- F1：排序键写的是本 scope 的投影别名 ⇒ `_resolve_column` 认不出归属 ----
    # ⚠️ 只判**无前缀**的排序列：`ORDER BY r.region_name` 走表别名解析（`_scope_tables`
    # 登记 alias），是合法形态；实测 X-MET-06 同时含两者，按裸名匹配会把锅记到错误的列上。
    aliases = {
        str(p.alias) for p in tree.find_all(exp.Alias) if getattr(p, "alias", None)
    }
    if aliases:
        hit = sorted(
            {
                column.name
                for ordered in tree.find_all(exp.Ordered)
                if isinstance((column := ordered.this), exp.Column)
                and not column.table
                and column.name
                and column.name in aliases
            }
        )
        if hit:
            findings.append(
                f"F1 排序键用了投影别名 {hit}（gate1 不登记同 scope 的投影别名 ⇒ R06）"
            )

    # ---- F2：默认谓词按域注入到"没有那几列"的资产 ⇒ 注入后必然 R06 ----
    assets: Mapping[str, Any] = allowlist.get("assets") or {}
    pred_cols = _pred_columns_by_domain(allowlist)
    poisoned: dict[str, tuple[str, list[str]]] = {}
    for table in tree.find_all(exp.Table):
        entry = assets.get(table.name)
        if entry is None:
            continue  # 未声明资产由 R05 管，不是本类的账
        missing = pred_cols.get(str(entry.get("domain")), set()) - set(
            (entry.get("columns") or {}).keys()
        )
        if missing:
            poisoned[table.name] = (
                str(entry.get("domain")),
                sorted(missing),
            )
    for name, (domain, missing) in sorted(poisoned.items()):
        findings.append(
            f"F2 域 `{domain}` 的默认谓词列 {missing} 被注入到缺列资产 `{name}`"
            "（注入后必然 R06）"
        )
    return "；".join(findings) or None


# ============================================================================
# 二、检索夹具（全目录；口径偏差见模块 docstring §四）
# ============================================================================

class BundleCatalogRetrieval:
    """`RetrievalPort` + `search_full` 的**确定性目录夹具**（不测检索本身）。

    ⚠️ 与"作弊"的界线：它**不看 gold_sql、不看用例 id**，只把语义包里所有认证资产
    与列原样端出来 —— 等价于"schema 全量塞进 prompt"。它让 schema linking 变**容易**，
    而不是把答案告诉模型。

    两条**必须与生产同形**的过滤（本会话真打批次实测出来的，不是洁癖）：
    * **deny 列不进候选**：07 §10.5 ④ + 附录 B §B.1.3"敏感列不进 schema 上下文 ⇒ 模型
      不知道存在"。初版没滤 ⇒ 75 个列候选里 9 个是 `tenant_id`/`receiver_phone`/
      `cost_price` 之类（滤后 66），模型不但看到了 deny 列，还把它们算进 L4 打分预算（见下）。
    * **指标层要给全**：契约的 `RetrievalResult.metrics` 是**相关度** Top-5；目录夹具
      **没有相关度可排** ⇒ 若按名截到 5，就会随机丢掉题面真正需要的口径（实测 active
      指标 8 条，按名只剩 aov/arpu/gmv/order_cnt/pay_cvr ⇒ `uv`/`refund_rate`/
      `repurchase_rate_90d` 三题型的定义永久缺失，届时失败会被归因成"模型不懂口径"，
      而真因是夹具）。⇒ 本夹具给**全部 active 指标**，规模落在 `last_counts` 里可复算。
      注意 `sell_through_rate` 在包内 `status='draft'` ⇒ 不计入（与生产口径一致）。

    ⚠️ 候选**规模**本身就是被测偏差：L4 打分器 `max_tokens=512`，实测每候选 ≈36.6 token
    ⇒ 一次调用只能容纳 ≈14 个候选；而契约的列级召回是 **Top-30**（`RetrievalResult.columns`
    注 / 07 §6.7）⇒ 满档召回**必然**截断（实测 3/3 次 `finish_reason=length`，只打完 14/75）。
    这条不在评测侧修（归 W3B/W2A），只把 `candidate_counts` 落在每次 run 里，让偏差可复算。
    """

    def __init__(
        self,
        loaded: LoadedBundle,
        *,
        column_top: int | None = None,
        denied_columns: tuple[str, ...] = (),
    ) -> None:
        self._assets = tuple(
            (a.physical_asset, a.logical_name, tuple(c.name for c in a.columns))
            for a in loaded.bundle.assets
            if a.logical_name in loaded.active_assets
        )
        #: `policy.deny_columns` 是 `asset.col` 形态；上下文里禁的是**列名**（与
        #: `planner/payloads._denied_basenames` 同口径），所以取 basename 集合。
        self._denied = {str(c).rsplit(".", 1)[-1] for c in denied_columns}
        self._metrics = tuple(
            sorted(str(m.name) for m in loaded.bundle.metrics if str(m.status) == "active")
        )
        self._column_top = column_top
        self.calls = 0
        #: 最近一次端出去的候选规模（L4 截断偏差的复算依据，进每条 run 的记录）。
        self.last_counts: dict[str, int] = {}

    async def search(
        self, question: str, ctx: IdentityContext, mode: RetrievalMode
    ) -> tuple[CandidateRef, ...]:
        return (await self.search_full(question, ctx, mode)).candidates

    async def search_full(
        self, question: str, ctx: IdentityContext, mode: RetrievalMode
    ) -> RetrievalResult:
        self.calls += 1
        # 资产级候选：物理名作 `asset_id`（与 W4 契约夹具同形：`CandidateRef(asset_id="fact_orders")`）
        candidates = tuple(
            CandidateRef(asset_id=physical, score=1.0) for physical, _, _ in self._assets
        )
        columns: list[tuple[str, float]] = []
        for physical, _logical, cols in self._assets:
            for col in cols:
                if col in self._denied:
                    continue  # 敏感列不进 schema 上下文（§10.5 ④ / §B.1.3）
                columns.append((f"{physical}.{col}", 1.0))
        if self._column_top is not None:
            columns = columns[: self._column_top]
        # 指标级：目录夹具给**全部** active 指标（不套契约 Top-5 —— 截断会随机丢口径，见 docstring）
        metrics = tuple((name, 1.0) for name in self._metrics)
        self.last_counts = {
            "assets": len(candidates),
            "columns": len(columns),
            "metrics": len(metrics),
            "metrics_in_catalog": len(self._metrics),
            "denied_filtered": len(self._denied),
        }
        return RetrievalResult(
            mode=RetrievalMode.SPARSE_ONLY,
            candidates=candidates,
            columns=tuple(columns),
            metrics=metrics,
            value_hits=(),
            graph_hits=(),
            degraded_reason=DegradedReason.EMBEDDING_UNAVAILABLE,
            action_taken=ActionTaken.SPARSE_ONLY,
        )


# ============================================================================
# 三、审计替身（评测不落生产审计行；但必须把两段落盘内容**留住可查**）
# ============================================================================

class InMemoryAudit:
    """`AuditSinkPort` 的内存实现（写失败不模拟 —— 评测要的是"能读到写了什么"）。"""

    def __init__(self) -> None:
        self.pre: list[dict[str, Any]] = []
        self.supp: list[dict[str, Any]] = []

    async def write_pre(self, ctx: IdentityContext, payload: Mapping[str, Any]) -> None:
        self.pre.append({"task_id": ctx.task_id, **dict(payload)})

    async def write_supp(self, ctx: IdentityContext, payload: Mapping[str, Any]) -> None:
        self.supp.append({"task_id": ctx.task_id, **dict(payload)})


# ============================================================================
# 四、一次 run 的出参
# ============================================================================

def _field(obj: Any, name: str) -> str:
    """从 dataclass 实例或 Mapping 里取一个字段（`GraphState` 里两类混存）。

    ⚠️ 取不到回空串而不是抛：这些值只用于**分组统计**（哪个闸门、哪一列），
    少一个键的代价是那条不计入分组，而不是把整批评测打断。
    ⚠️ 布尔字段别用它（`False` 会变成空串）⇒ 用 `_raw_field`。
    """
    if isinstance(obj, Mapping):
        return str(obj.get(name) or "")
    return str(getattr(obj, name, "") or "")


def _raw_field(obj: Any, name: str) -> Any:
    """同 `_field`，但**不字符串化**（`passed=False` 必须还是 False）。"""
    return obj.get(name) if isinstance(obj, Mapping) else getattr(obj, name, None)


@dataclass(slots=True)
class CaseRun:
    """一次真图 run 的**全部评测事实**（判定层只看这个，不再回头戳 state）。"""

    case_id: str
    question: str
    tenant: str
    identity: IdentityContext
    state: Mapping[str, Any] = field(default_factory=dict)
    nodes: tuple[str, ...] = ()
    infra_error: str | None = None  # 匣带 miss / 装配异常：该用例**不进分母**

    # -- 便捷视图（全部从 state 派生，不另存一份真相） ----------------------

    @property
    def terminal_event(self) -> str | None:
        terminal = self.state.get("terminal") or {}
        return str(terminal["event"]) if terminal.get("event") else None

    @property
    def outcome(self) -> str | None:
        value = self.state.get("outcome")
        return str(value) if value is not None else None

    @property
    def sql_text(self) -> str:
        return str(self.state.get("sql_text") or "")

    @property
    def sql_params(self) -> dict[str, Any]:
        return dict(self.state.get("sql_params") or {})

    @property
    def sql_dialect(self) -> str:
        return str(self.state.get("sql_dialect") or "")

    @property
    def row_count(self) -> int:
        return int(self.state.get("row_count") or 0)

    @property
    def result_columns(self) -> tuple[str, ...]:
        """输出列名（`contracts.ColumnMeta`；评测无检查点 ⇒ 不会被序列化成 dict，但两形态都读）。"""
        return tuple(_field(meta, "name") for meta in (self.state.get("result_columns") or ()))

    @property
    def result_rows(self) -> tuple[tuple[Any, ...], ...]:
        return tuple(tuple(r) for r in (self.state.get("result_rows") or ()))

    @property
    def truncated(self) -> bool:
        return bool(self.state.get("truncated"))

    @property
    def fingerprint(self) -> str:
        return str(self.state.get("result_fingerprint") or "")

    @property
    def exec_error_class(self) -> str | None:
        """执行失败的**脱敏类别**（`app.exec.errors.ExecError.error_class`；组 8 存对象本体）。"""
        error = self.state.get("exec_error")
        if error is None:
            return None
        return _field(error, "error_class") or "unknown"

    @property
    def binding_status(self) -> str | None:
        value = self.state.get("binding_status")
        return str(value) if value is not None else None

    def _gate_results(self) -> dict[int, Any]:
        """组 6 的 `gate_results` —— 实测形状是 `Mapping[GateNo, GateResult]`（`state.py:312`）。

        ⚠️ 别把它当序列：`for item in mapping` 只会拿到**枚举键**，于是
        `_field(item,"gate_no")` 恒 `None` ⇒ 三个判据静默为空（本会话真打过一次
        gate1 拒绝的用例，记录里 `gate_decisions={}`，就这么漏掉了整条归因信号）。
        序列形态仍兼容（检查点回放后 `{gate_no, decision, rule_id}` 的 payload 列表）。
        """
        raw = self.state.get("gate_results")
        if not raw:
            return {}
        if isinstance(raw, Mapping):
            out: dict[int, Any] = {}
            for key, value in raw.items():
                num = _field(value, "gate_no") or key
                try:
                    out[int(str(num).rsplit(".", 1)[-1])] = value
                except (TypeError, ValueError):
                    continue
            return out
        result: dict[int, Any] = {}
        for item in raw:
            gate = _field(item, "gate_no") or _field(item, "gate")
            try:
                result[int(str(gate).rsplit(".", 1)[-1])] = item
            except (TypeError, ValueError):
                continue
        return result

    @property
    def gate_decisions(self) -> dict[str, str]:
        """`{闸门号: decision}`（`passed` 一并带上：`SKIPPED` 不得被读成通过）。"""
        return {
            str(no): f"{_field(item, 'decision')}/{_raw_field(item, 'passed')}"
            for no, item in sorted(self._gate_results().items())
        }

    @property
    def gate_rules_hit(self) -> tuple[str, ...]:
        return tuple(
            rule
            for item in self._gate_results().values()
            if (rule := _field(item, "rule_id"))
        )

    @property
    def gate1_reject_rule(self) -> str | None:
        """闸门一（AST）命中时的 `rule_id`，其余闸门一概不看。

        存在的意义只有一个：让 `attribution` 能把"模型写的 SQL 被**闸门自身判据缺陷**
        杀掉"（实测 `R06` 两条路径，见 `reports/w6/probe_gate_rejections.py`）
        与"模型真的写错了"分开 —— 混在一起统计会让策略层把锅甩给模型。
        """
        item = self._gate_results().get(int(GateNo.AST))
        if item is None or _field(item, "passed") in (True, "True"):
            return None
        return _field(item, "rule_id") or None

    @property
    def terminal_code(self) -> str | None:
        """终态错误码（`terminal = {event, code?, reason?}`，`state.py:336`）。

        `error` 出口的**归因信息只在 `code` 里**（`reason` 是拒答/澄清用的），
        没有这一列就等于把"闸门拒绝"和"内部故障"压成同一个 `terminal=error`。
        """
        terminal = self.state.get("terminal") or {}
        code = terminal.get("code") if isinstance(terminal, Mapping) else _field(terminal, "code")
        return str(code) if code else None

    @property
    def degradations(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(d) for d in (self.state.get("degradations") or ()))

    @property
    def refusal_reason(self) -> str | None:
        terminal = self.state.get("terminal") or {}
        return str(terminal["reason"]) if terminal.get("reason") else None

    @property
    def latency_ms(self) -> dict[str, Any]:
        return dict(self.state.get("latency_ms") or {})

    @property
    def tokens(self) -> dict[str, Any]:
        return dict(self.state.get("tokens") or {})

    @property
    def cost_cny(self) -> float:
        try:
            return float(self.state.get("cost_cny") or 0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def limit_injected(self) -> Any:
        return self.state.get("limit_injected")

    @property
    def applied_predicates(self) -> tuple[str, ...]:
        return tuple(str(p) for p in (self.state.get("applied_predicates") or ()))


def identity_for_case(case_id: str, tenant: str, *, role: Role = Role.ANALYST) -> IdentityContext:
    """评测身份（**每用例一份**：`task_id` 唯一，避免跨用例的登记表/缓存串号）。"""
    return IdentityContext(
        trace_id=f"tr-eval-{case_id}",
        task_id=f"tk-eval-{case_id}",
        session_id=f"se-eval-{case_id}",
        tenant_id=tenant,
        user_id=f"u-eval-{case_id}",
        role=role,
        scope_claims=(),
        shop_ids=(),
    )


# ============================================================================
# 五、节点超时：真打时必须显式放大（走 `build_graph` 的官方测试缝）
# ============================================================================
"""07 §5.3 的超时表按**生产**口径设定。实测（本会话 5 条 live 批次）：正常链路会在校内一次
真实 LLM 出站上被节点硬超时打断 → `TimeoutError`、`terminal=None` —— 即"链路没坏，但契约值
容不下一次真实 LLM 出站"。这是**契约冲突**，已上呈（RELAY）。

⚠️ 本函数的靶子随契约换过两次形状（都要按当下的代码读，别照抄旧例子）：
· U-104（合并档预算平移）把 5 个 LLM 节点从 `NODE_TIMEOUT_S` 移了出去；
· U-107（d387347，W4）把"预算当硬超时"这个病害整体改掉 —— LLM 节点的硬超时**不再写死**，
  执行期经 `_LLM_NODE_TASKS` → `resolve_route` → `hard_timeout_s` 解析为**客户端超时**
  （§10.2：flash 15s / pro 45s）。⇒ 当年"`normalize` 契约 2.0s 被打断"那一格已不成立
 （它的生效值现在是 15s）；但 `bind` **仍留在表里、仍是 0.2s**，而 `nodes/bind.py:180`
  确实触达 `deps.llm` ⇒ 生产侧这一格仍是缺口，本窗口只上呈不代修（RELAY G3）。

放大不拍脑袋：下界由文档自己的数字推出 ⇒ `EVAL_LLM_NODE_TIMEOUT_S`。
放大的代价必须写清：**真打轮的 EX 不覆盖 07 §5.3 超时契约**（进 §17.4 缺口表）——
U-107 之后这句更具体：LLM 节点生产走 15s/45s，评测兜到 162s，两者**不是同一个数**。
匣带回放轮**不放大**（回放不出网）⇒ 那一轮仍是契约/客户端超时，可用于超时回归。
"""

#: 会做出站 LLM 调用的节点（判据 = `app/graph/nodes/*.py` 里是否触达 `deps.llm`；
#: 实测命中：`normalize` `intent` `plan` `bind` `gen_sql` `repair`；
#: `link` 只走本地检索、`present` 是启发式排版，故不在此列）。
#: ⚠️ 与 app 自己的 `_LLM_NODE_TASKS`（`build.py:396`）**双向都不一致**（U-107 后实测）：
#: · `bind`：`nodes/bind.py:180` 确实经 `context.deps.llm` 走 L4 精排，却不在那份清单里
#:   ⇒ `_effective_limit_for("bind") = 0.2s`（`normalize`/`gen_sql` 都解析成 15s）。
#:   生产路径上 L4 那一跳只有 0.2s，而评测侧的下界把它兜住了 ——
#:   "评测比生产宽松"的存量一处，已上呈 RELAY G3（不在本窗口替对方改契约）。
#: · `present`：那份清单里有，而 `nodes/present.py` 全文件对 `llm` **零命中** ⇒ 对方比代码宽。
#:   对本窗口无害（多给一档客户端超时不会假绿），但结论要留下：**两份清单谁都不是权威**，
#:   判据只能是"代码是否触达 `deps.llm`"，所以本清单不改成照抄 `_LLM_NODE_TASKS`。
LLM_CALLING_NODES: frozenset[str] = frozenset(
    {"normalize", "intent", "plan", "bind", "gen_sql", "repair"}
)

#: 一次节点内 LLM 路径的**最坏合法**耗时（全部取自契约，不是经验值）：
#:   信号量排队上限 20s            —— 07 §10.1"排队等待上限 20s"
#:   + `LLM_MAX_RETRIES`(=3) × 单次上限 45s —— 07 §10.2 v4-pro 单次调用超时（思考模式）
#:   + 2 次内部退避 × 3.5s          —— 07 §14.4.1 推导链里点名的"内部已退避 3.5s 才外抛"
#: = 162s。真打批次串行、单条最多卡这一个数；再大就是让挂死的上游拖垮整批。
EVAL_LLM_NODE_TIMEOUT_S: float = 20.0 + 3 * 45.0 + 2 * 3.5

#: 非 LLM 节点的放大系数（纯 CPU / 本地状态构造）。07 自己在 `build_graph` docstring
#: 里承认"0.1s 的闸门节点在慢 CI 上会假阳性"⇒ 评测机同样适用。实测放大后落点：
#: 闸门三兄弟 0.8s、`mask` 0.8s、`audit_pre` 8s、`audit_supp` 4s —— 都远低于 LLM 档，
#: 不构成"让挂死蒙混过关"。
EVAL_CPU_FACTOR: float = 8.0

#: **不放大**的节点（逐节点给理由，不能一句"上限"概括）：
#: · `execute`：30s 是 07 §5.3 明文的"交互 8s / 上限 30s"**上限**，慢在这里 = 被测事实
#:   （沙箱跑不出来的查询，放大只会把结论藏起来），不是 CI 假阳性。
#: · `link`：U-107 之后它的契约值 = `Settings.EMBEDDING_TIMEOUT_SECONDS`（30s），已经是
#:   **出站客户端超时同档**，再 ×8 = 240s 只是放大墙钟、不放大被测事实；且评测走的是
#:   本地夹具检索 `BundleCatalogRetrieval`（§17.4"评测不测向量检索"）⇒ 永远逼近不了 30s，
#:   放大对它没有意义。
EVAL_TIMEOUT_AS_CONTRACT: frozenset[str] = frozenset({"execute", "link"})


def eval_node_timeouts() -> dict[str, float]:
    """评测用节点超时 overrides。

    ⚠️ U-104 把 5 个 LLM 节点从 `NODE_TIMEOUT_S` 移了出去，U-107（`d387347`）进一步把它们
    的硬超时改成**执行期解析**：`_LLM_NODE_TASKS`（`build.py:396-403`）→ `resolve_route` →
    `hard_timeout_s`（flash 15s / pro 45s）。只遍历契约表 ⇒ 这些节点拿不到评测下界，
    一次真 LLM 出站又把整条判成链路故障 —— 正是本函数要防的那件事，只是换了个隐身方式。
    ⇒ 遍历**并集**：契约表里的节点按契约/系数处理，只在 LLM 清单里的节点直接给下界。
    （`link` 与 `execute` 走"不放大"分支，逐节点理由写在 `EVAL_TIMEOUT_AS_CONTRACT` 上。）
    """
    out: dict[str, float] = {}
    for name in set(NODE_TIMEOUT_S) | set(LLM_CALLING_NODES):
        contract = NODE_TIMEOUT_S.get(name)
        if name in EVAL_TIMEOUT_AS_CONTRACT:
            out[name] = contract if contract is not None else EVAL_LLM_NODE_TIMEOUT_S
        elif contract is None:                     # 契约表已不再计时的 LLM 节点
            out[name] = EVAL_LLM_NODE_TIMEOUT_S
        elif name in LLM_CALLING_NODES:
            out[name] = max(contract, EVAL_LLM_NODE_TIMEOUT_S)
        else:
            out[name] = contract * EVAL_CPU_FACTOR
    return out


def describe_node_timeouts(effective: Mapping[str, float]) -> dict[str, Any]:
    """把"契约 vs 实际"写成可进报告/JSON 的形状（报告里必须能看出放大过）。

    `effective` 传空 dict = 图跑在契约值上 ⇒ 这里回填契约表，避免读者把"空"读成"没配超时"。
    ⚠️ `not_in_contract` 必须显式列出：那些节点名**不在** `NODE_TIMEOUT_S`（U-104 后 LLM 节点
    的硬超时在执行期解析），藏起来就等于让读者以为评测和契约一一对应。
    """
    eff = dict(effective) or dict(NODE_TIMEOUT_S)
    return {
        "contract": dict(NODE_TIMEOUT_S),
        "effective": eff,
        "scaled": bool(effective),
        "llm_calling_nodes": sorted(LLM_CALLING_NODES),
        "not_in_contract": sorted(LLM_CALLING_NODES - set(NODE_TIMEOUT_S)),
        "kept_as_contract": sorted(EVAL_TIMEOUT_AS_CONTRACT),
        "cpu_factor": EVAL_CPU_FACTOR,
        "llm_node_floor_s": EVAL_LLM_NODE_TIMEOUT_S,
    }


# ============================================================================
# 六、harness
# ============================================================================

class Harness:
    """一次构造、多次 run 的评测装配台。

    ⚠️ `graph` 可共享（无状态单例），`deps` **每请求一份**是 `GraphDeps` 的硬约束
    （`PlannerEngine._pending` 跨请求会串降级事件）⇒ 每次 run 重新造 `GraphDeps`，
    但共享其中的重对象（网关/绑定服务/运行时/执行器）。
    """

    def __init__(
        self,
        *,
        cassette_path: str | None = None,
        cassette_mode: str = "replay",
        live: bool = False,
        settings: Settings | None = None,
        bundle_path: str | None = None,
        db_path: str | None = None,
        column_top: int | None = None,
        node_timeout_overrides: Mapping[str, float] | None = None,
    ) -> None:
        if live and cassette_path and cassette_mode not in ("record", "replay"):
            raise ValueError(f"未知匣带模式：{cassette_mode}")
        self.settings = settings or get_settings()
        self.loaded = load_bundle(bundle_path or _bootstrap.BUNDLE_PATH)
        self.runtime = SemanticBundleRuntime(self.loaded)
        self.semantics = GuardAllowlistBundle(self.runtime, self.loaded)
        self.mask = SemanticMaskEngine()
        self.tenant_scoped_physicals = {
            a.physical_asset: "tenant_id"
            for a in self.loaded.bundle.assets
            if a.tenant_scoped and a.logical_name in self.loaded.active_assets
        }
        self.executor = SqliteEvalExecutor(
            db_path=db_path or _bootstrap.SANDBOX_DB,
            mask=self.mask,
            settings=self.settings,
            tenant_scoped_physicals=self.tenant_scoped_physicals,
            bundle=self.semantics,
        )
        self.audit = InMemoryAudit()
        self.retrieval = BundleCatalogRetrieval(
            self.loaded,
            column_top=column_top,
            denied_columns=tuple(self.runtime.policy().get("deny_columns") or ()),
        )
        self.clock = Clock(self.runtime.time_semantics())

        self.transport: CassetteTransport | None = None
        if cassette_path and not live:
            self.transport = CassetteTransport(mode=cassette_mode, path=cassette_path)  # type: ignore[arg-type]
        elif cassette_path and live:
            self.transport = CassetteTransport(mode="record", path=cassette_path)

        self.gateway = build_gateway(
            self.settings,
            degradation=None,  # 无 SSE 出口：降级只进 state/审计（`RunContext` 的既定口径）
            client=self._chat_client(),
        )
        self.graph = build_graph(node_timeout_overrides=node_timeout_overrides)
        #: 空 dict = 图跑在 07 §5.3 契约超时上（生产同形）；非空 = 走过评测放大缝。
        self.node_timeout_overrides: dict[str, float] = dict(node_timeout_overrides or {})

    def _chat_client(self) -> ChatClient | None:
        """只有需要换传输层（匣带）时才自建 client。

        ⚠️ 参数与 `app.llm.build_gateway` 的默认 client 逐字对齐（同 settings 字段）。
        两处漂移的风险登记在 `reports/w6/RELAY.md`（给 W3A：`build_gateway` 若能直接收
        `transport=`，这个镜像就可以删）。
        """
        if self.transport is None:
            return None
        s = self.settings
        return ChatClient(
            base_url=s.DEEPSEEK_BASE_URL,
            api_key=s.DEEPSEEK_API_KEY.get_secret_value(),
            model_names={"fast": s.LLM_MODEL_FAST, "strong": s.LLM_MODEL_STRONG},
            max_concurrency=s.LLM_MAX_CONCURRENCY,
            semaphore_flash=s.LLM_SEMAPHORE_FLASH,
            semaphore_pro=s.LLM_SEMAPHORE_PRO,
            max_retries=s.LLM_MAX_RETRIES,
            circuit_fails=s.LLM_CIRCUIT_FAILS,
            circuit_open_s=s.LLM_CIRCUIT_OPEN_S,
            transport=self.transport,
        )

    # -- 依赖工厂（每请求一份，与 `deps.py::new_deps` 同构） ----------------

    def new_deps(self) -> GraphDeps:
        s = self.settings
        return GraphDeps(
            llm=self.gateway,
            planner=PlannerEngine(
                llm=self.gateway,
                semantics=self.semantics,
                clock=self.clock,
                degradation=None,
                # `few_shots=None`：**与生产同形**（`deps.py` 也没传）。
                # W1A 的 `gold_query_seed_v1.json` 因此在评测里未被消费 —— 已登记（§17.4）。
            ),
            binding=BindingService.from_settings(
                reader=self.semantics, settings=s, observer=None
            ),
            semantics=self.semantics,
            retrieval=self.retrieval,
            executor=self.executor,
            mask=self.mask,
            audit=self.audit,
            clock=self.clock,
            result_cache=None,
            query_plan_writer=None,
            presenter=None,
            gate3_thresholds=self.gate3_thresholds(),
            max_rows=s.EXEC_MAX_ROWS,
            statement_timeout_ms=s.EXEC_STATEMENT_TIMEOUT_MS,
        )

    def gate3_thresholds(self) -> dict[str, Any]:
        """镜像 `deps.py::_gate3_thresholds`（Settings → `CostThresholds` 字段名）。

        ⚠️ 沙箱里 `explain()` 恒 `None` ⇒ gate3 恒 `SKIPPED`（§17.4），
        这几个阈值**本轮根本不参与判定** —— 镜像的意义只是"装配形状与生产一致"，
        不构成第二处口径来源（无消费者）。已随缺口表一起登记。
        """
        s = self.settings
        return {
            "total_cost_pass": s.GATE3_COST_WARN,
            "total_cost_reject": s.GATE3_COST_REJECT,
            "rows_pass": s.GATE3_ROWS_WARN,
            "rows_reject": s.GATE3_ROWS_REJECT,
        }

    # -- 跑一条 -------------------------------------------------------------

    async def run_case_async(
        self,
        *,
        case_id: str,
        question: str,
        tenant: str,
        extra_state: Mapping[str, Any] | None = None,
    ) -> CaseRun:
        identity = identity_for_case(case_id, tenant)
        deps = self.new_deps()
        context = RunContext(deps)  # recorder=None → 无 SSE 出口（评测面）
        state = initial_state(identity, raw_question=question)
        if extra_state:
            state.update(dict(extra_state))  # type: ignore[typeddict-item]
        config = {
            "configurable": {"thread_id": f"eval-{case_id}"},
            "recursion_limit": GRAPH_RECURSION_LIMIT,
        }
        run_token = set_run_context(context)
        identity_token = bind_identity(identity)
        nodes: list[str] = []
        final: Mapping[str, Any] = dict(state)
        infra_error: str | None = None
        try:
            # `values` = 每步**合并后的全量 state**（LangGraph 自己的 reducer 语义，评测不复算）；
            # `updates` = 每步的 `{节点名: 增量}` —— 只要节点名，用于"走到哪一步"的归因信号。
            async for mode, payload in self.graph.astream(
                state, config, stream_mode=["updates", "values"]
            ):
                if mode == "values":
                    final = payload
                elif isinstance(payload, Mapping):
                    nodes.extend(str(name) for name in payload)
        except Exception as exc:
            infra_error = (
                f"cassette_miss: {str(exc)[:200]}"
                if isinstance(exc, CassetteMiss)
                else f"{type(exc).__name__}: {str(exc)[:300]}"
            )
        finally:
            clear_run_context(run_token)
            reset_identity(identity_token)

        return CaseRun(
            case_id=case_id,
            question=question,
            tenant=tenant,
            identity=identity,
            state=dict(final),
            nodes=tuple(nodes),
            infra_error=infra_error,
        )

    def run_case(self, **kwargs: Any) -> CaseRun:
        """同步壳（Windows 下 `asyncio.run` 的惯例，见 `tests/contract/_fullchain_deps.py`）。"""
        return asyncio.run(self.run_case_async(**kwargs))

    # -- 收尾 ---------------------------------------------------------------

    def save_cassette(self) -> int:
        return self.transport.save() if self.transport is not None else 0

    async def aclose(self) -> None:
        """真打 / 匣带轮**必须**收在这里，不能用 `close()` 了事。

        `ChatClient` 在构造时建 `httpx.AsyncClient`，它绑在**创建它的** event loop 上；
        不 await 关闭就换 loop ⇒ 第二批的第一条能跑、后面某条报
        `RuntimeError: Event loop is closed`（实测：5 条 live 批次第 3 条 M-DIM-09）。
        """
        await self.gateway.aclose()
        self.close()

    def close(self) -> None:
        self.executor.close()


# ============================================================================
# 六、离线自检（不联网、不建图）：装配面是否可构造
# ============================================================================

def selfcheck() -> dict[str, Any]:
    """评测器自身的"能不能装起来"检查（报告附录用；不调 LLM、不执行 SQL）。"""
    harness = Harness()
    identity = identity_for_case("SELFCHECK", "T_A")
    allowlist = harness.semantics.asset_allowlist(identity)
    from app.guard import run_gate1

    # ⚠️ 排序键刻意写**表达式**而不是投影别名：`ORDER BY g DESC` 会被 gate1 判 R06
    # （W2C 的判据缺陷，非本适配器的故障，取证见 `reports/w6/probe_gate_rejections.py` F1）。
    # 本自检只回答一个问题："allowlist 形状适配装了没有"，所以探针必须避开已知外因。
    probe_sql = (
        "SELECT category_l1, SUM(pay_amount) FROM v_order_paid "
        "WHERE pay_status = 'paid' GROUP BY category_l1 "
        "ORDER BY SUM(pay_amount) DESC LIMIT 10"
    )
    gate1 = run_gate1(probe_sql, allowlist)
    # 目录夹具的候选规模（deny 列是否真被滤掉、指标层是否给出去）—— 纯本地，不打 LLM。
    asyncio.run(harness.retrieval.search_full("自检", identity, RetrievalMode.SPARSE_ONLY))
    result = {
        "assets": len(allowlist["assets"]),
        "joins": len(allowlist["joins"]),
        "deny_columns": len(allowlist["deny_columns"]),
        "fixture_candidate_counts": dict(harness.retrieval.last_counts),
        "tenant_scoped_physicals": sorted(harness.tenant_scoped_physicals),
        "bundle_version": harness.runtime.active_version(),
        "gate1_probe_passed": bool(gate1.gate_result.passed),
        "gate1_probe_reason": str(
            gate1.gate_result.reason or gate1.gate_result.rule_id or ""
        ),
        "gate1_rewritten": bool(gate1.rewritten_sql),
    }
    harness.close()
    return result


if __name__ == "__main__":
    print(json.dumps(selfcheck(), ensure_ascii=False, indent=2, default=str))
