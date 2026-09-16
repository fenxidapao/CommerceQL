r"""`GraphState` —— 图的**唯一**状态契约（07 §5.2 的机器化；目录树 §3.2 标注为"唯一"）。

归属窗口：W1B（`docs/08 §4.1`：`app/graph/state.py`）。

--------------------------------------------------------------------------
一、为什么这个文件必须"一次落全"，而不能"用到哪个字段加哪个"
--------------------------------------------------------------------------
07 §5.2 的 11 组字段是本项目**唯一**的跨节点数据契约。若按需增删，会出现两种病：

| 病 | 表现 |
|---|---|
| **隐式通道**（违反 G-2） | 某个字段还没加，节点就用**闭包或模块级变量**传值 —— 它能跑通、能过测试，只是在 `resume` 时那部分状态丢失 |
| **权限标注漂移**（违反 G-3） | 字段加的时候没人标注 `PROMPT`/`PII`，于是它默认进了 LLM 上下文 —— 这正是 N-12 要防的事 |

所以本文件在阶段 1B（W1B）**一次性落全 11 组**，字段名与 07 §5.2 的表**逐字对齐**，
并把 §5.2 的 `CKPT`/`PROMPT`/`PII` 三列变成**可执行断言**（见下方三个集合）。
⚠️ 这不是"提前做完 W4 的工作" —— 落的是**契约**，节点实现（`graph/nodes/`）
与条件边（`graph/edges.py`）仍归 W4（`docs/08 §3.6`）。

--------------------------------------------------------------------------
二、三列标注怎么变成断言（而不是注释）
--------------------------------------------------------------------------
07 §5.2 的每一列都在本文件里有一个**唯一**的集合承载，且集合与 `GraphState` 的键
必须**恰好覆盖**（`tests/contract/test_graph_state_contract.py` 会逐条核对）：

| 07 §5.2 的列 | 本文件的承载 | 语义 | 违反的后果 |
|---|---|---|---|
| `CKPT ❌ 体积` | `CHECKPOINT_EXCLUDED_FIELDS` | 该字段**只放摘要/引用**，全量数据在 Redis | 检查点膨胀到 MB 级 → **每次节点切换写一遍** → R-10 |
| `PROMPT ✅` | `PROMPT_ALLOWED_FIELDS` | 允许进 LLM 上下文 | — |
| `PROMPT ❌`（默认） | 不在 `PROMPT_ALLOWED_FIELDS` 里 | **默认禁止出站**（G-3 原文："默认禁止进 PROMPT，需显式授权"） | 明细/身份出站 → N-12 违规 |
| `PII` | `PII_FIELDS` | 禁止出站到 LLM | 跨租户根泄露 |

`PII_FIELDS ∩ PROMPT_ALLOWED_FIELDS == ∅`（N-12 的机器化）。
`raw_question` 是**唯一**允许出站的用户输入，且必须包裹在分隔符内（§10 注入防护）——
它是"允许出站"但不是 PII，这两件事在 07 §5.2 里本就是两列。

--------------------------------------------------------------------------
三、⚠️ 四类占位与未决项（诚实标注，不阻塞）
--------------------------------------------------------------------------
本阶段（1B）上游尚未产出具体载荷类型，故以下字段用**占位类型**，
每一条都登记了回填请求。占位一律用 `Mapping[str, Any]`（见 `OpaquePayload` 的理由）：

| 字段 | 07 §5.2 的应有类型 | 谁来定义 | 登记 |
|---|---|---|---|
| `options` | `RunOptions` | 附录 A（DTO 归 W4 的 `api/dto/`） | **U-24** |
| `time_range` | `{start, end, expr, tz}` | 语义包（附录 B）+ W2A | **U-24** |
| `resolved_terms` | `list[{surface, canonical, kind}]` | W2A（`semantics/`） | **U-24** |
| `candidates` | `CandidateSet` | W2B（`retrieval/`） | **U-24** |
| `few_shot` / `plan` / `plan_summary` / `bindings` | `GoldQuery` / `Plan` / `PlanSummary` / `Binding` | W2B / W3B | **U-24** |
| `ambiguities` / `binding_ambiguity` | `Ambiguity` | W2B | **U-24** |
| `gate_results` | `{gate1, gate2, gate3}` | **已可用**：`contracts.GateResult` + `GateNo` | — |
| `scope` | `Scope` | **已可用**：`contracts.ScopeInfo` | — |
| `result_columns` | `list[ColumnMeta]` | **已可用**：`contracts.ColumnMeta` | — |
| `chart_spec` / `insight` | `ChartSpec` / `Insight` | W3C（`present/`） | **U-24** |
| `exec_error` | `ExecError` | W2D（`exec/`） | **U-24** |
| `clarify` | `ClarifyPayload` | 附录 A §A.1.4（W4 的 DTO） | **U-24** |
| `intent` | `executable \| clarify \| refuse \| open_analysis` 四值枚举 | **`core/enums.py` 目前没有该枚举**（只有 `RefuseReason.OPEN_ANALYSIS`）→ `str` 占位 | **U-25** |

⚠️ **为什么不在这里自建这些类型**：图**不解释载荷**（G-1：节点只做"读 state → 调服务 → 写 state"）。
自建一份会在 W2/W3 定义真类型时变成**第二份真相** —— 那就是 U-18 的教训（同一事实写两遍，
合起来必然矛盾）。`Mapping[str, Any]` 是最弱的、也是唯一不抢归属权的写法。
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Final, TypedDict

from app.core.contracts import (
    ColumnMeta,
    GateResult,
    IdentityContext,
    ScopeInfo,
)
from app.core.enums import GateNo, Outcome, Role

__all__ = [
    "CHECKPOINT_EXCLUDED_FIELDS",
    "FIELD_GROUP",
    "GRAPH_STATE_FIELDS",
    "PII_FIELDS",
    "PROMPT_ALLOWED_FIELDS",
    "REQUIRED_STATE_FIELDS",
    "STATE_GROUPS",
    "GraphState",
    "OpaquePayload",
    "assert_state_field_annotations_complete",
    "assert_terminal_is_settable",
    "identity_fields",
    "initial_state",
    "is_checkpointable",
    "is_prompt_allowed",
]

# ---------------------------------------------------------------------------
# 占位类型
# ---------------------------------------------------------------------------

#: 尚未落地的载荷类型（见文件头"三、四类占位与未决项"）。
#:
#: ⚠️ 刻意**不**定义自定义 dataclass：图不解释载荷（G-1），而自建类型会在
#: W2/W3 落地真类型时成为第二份真相（U-18 的教训）。`Mapping[str, Any]`
#: 是"最弱的、不抢归属权"的写法。
#: ⚠️ 用 `Mapping` 而非 `dict`：节点只能读，不能就地改 —— 就地改会绕过
#: "所有跨节点数据必须在 `GraphState` 中有具名字段"（G-2）。
OpaquePayload = Mapping[str, Any]


# ---------------------------------------------------------------------------
# 组名（07 §5.2 的 11 组）
# ---------------------------------------------------------------------------

#: 组名 → 该组的字段（07 §5.2 逐组）。**这是分组归属的唯一真相**。
STATE_GROUPS: Final[Mapping[str, tuple[str, ...]]] = {
    "1_request_identity": (
        "trace_id",
        "task_id",
        "session_id",
        "tenant_id",
        "user_id",
        "role",
        "scope_claims",
        "shop_ids",
        "raw_question",
        "options",
        "idempotency_key",
    ),
    "2_normalize": (
        "normalized_question",
        "time_range",
        "resolved_terms",
        "unresolved_terms",
        "time_parse_ok",
    ),
    "3_intent": ("intent", "intent_detail"),
    "4_retrieval": (
        "candidates",
        "candidates_summary",
        "retrieval_mode",
        "linking_stats",
        "few_shot",
        "ambiguities",
    ),
    "5_plan_binding": (
        "plan",
        "plan_summary",
        "bindings",
        "binding_status",
        "binding_ambiguity",
    ),
    "6_gen_sql": (
        "sql_text",
        "sql_params",
        "sql_dialect",
        "sql_candidates",
        "prompt_version",
        "model_version",
        "confidence",
    ),
    "7_gate": ("gate_results", "limit_injected", "applied_predicates", "scope"),
    "8_execute": (
        "result_rows",
        "result_ref",
        "result_columns",
        "row_count",
        "truncated",
        "exec_error",
        "result_fingerprint",
    ),
    "9_repair": ("repair_round", "repair_history"),
    "10_present": ("chart_spec", "insight", "degradations"),
    "11_terminal_metering": (
        "terminal",
        "clarify",
        "outcome",
        "latency_ms",
        "tokens",
        "cost_cny",
    ),
}

#: 字段 → 组。由 `STATE_GROUPS` 派生，**不得手写**（手写就会与上面漂移）。
FIELD_GROUP: Final[Mapping[str, str]] = {
    field: group for group, fields in STATE_GROUPS.items() for field in fields
}

#: `GraphState` 的**全量**具名字段（顺序即 07 §5.2 的表序）。
GRAPH_STATE_FIELDS: Final[tuple[str, ...]] = tuple(FIELD_GROUP)


# ---------------------------------------------------------------------------
# 三个标注集合（07 §5.2 三列的机器化）
# ---------------------------------------------------------------------------

#: `CKPT ❌ 体积` 的字段（07 §5.2.1）：**只放摘要/引用**，全量在 Redis。
#:
#: ⚠️ 这不是"优化"，是**防 R-10**（LangGraph 的第一大生产事故 = 检查点写入成为瓶颈）。
#: 一次 5000 行 × 20 列的结果集会让检查点膨胀到 MB 级，**每次节点切换都写一遍**。
#:
#: ⚠️ 命名说明：集合装的是**被排除的字段名**，不是"可入检查点的字段"——
#: 因为 §5.2 的默认是"入检查点"，例外才是被点名的这几个（默认宽、例外窄，
#: 与"标注要显式授权"的方向一致：漏标一个体积字段会红，而不是静默变胖）。
CHECKPOINT_EXCLUDED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "candidates",  # 全量候选 → state 里只留 `candidates_summary`
        "sql_candidates",  # 只保留选中项 → `sql_text`
        "result_rows",  # 全量结果 → Redis `result:{tenant}:{task}`，state 里留 `result_ref`
    }
)

#: `PROMPT ✅` 的字段（07 §5.2 中显式标 ✅ / ⚠️ 的）。
#: 其余字段**默认禁止出站**（G-3 原文："默认禁止进 PROMPT，需显式授权"）。
PROMPT_ALLOWED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "raw_question",       # ⚠️ 唯一允许出站的用户输入，且必须包裹在分隔符内（§10）
        "normalized_question",
        "time_range",
        "resolved_terms",
        "few_shot",
        "plan",
        "bindings",
        "repair_history",     # ✅ 仅脱敏摘要（07 §5.2 组 9 逐字）
    }
)

#: `PII` 字段（07 §5.2 标 **PII** 的两个）：禁止出站到 LLM（N-12）。
#:
#: ⚠️ `raw_question` **不在**这里 —— 它是"允许出站但不是 PII"。
#: 把两者混为一谈会得出"要么全禁、要么全放"的错误结论：
#: 实际规则是**按列独立**的（可以出站 ≠ 可以无保护出站）。
PII_FIELDS: Final[frozenset[str]] = frozenset({"tenant_id", "user_id"})

#: 必须在 `initial_state()` 中就位、且**一旦写入不得被任何节点修改**的字段（组 1 全集）。
#:
#: ⚠️ 与 `07 §5.2 组 1` 的标题"之后**只读**"对应。TypedDict **不是**不可变的，
#: 所以"只读"在此是**运行时 + 测试**保证，不是类型保证：
#: · 类型层面的不可变由 `IdentityContext` 承担（`frozen=True`）——见 `identity_fields()`；
#: · `tests/contract/test_graph_state_contract.py` 断言组 1 只能由 `trusted_context` 写入。
REQUIRED_STATE_FIELDS: Final[frozenset[str]] = frozenset(STATE_GROUPS["1_request_identity"])


# ---------------------------------------------------------------------------
# GraphState
# ---------------------------------------------------------------------------


class GraphState(TypedDict, total=False):
    """图的唯一状态。⚠️ **字段名与 07 §5.2 逐字对齐**，改名前先改文档。

    `total=False` 是**刻意的**：LangGraph 的节点返回的是**增量**（`dict` 的部分键），
    而 `total=True` 会让每个返回值都要凑齐全字段 —— 那会逼实现者写出
    `{"...": state.get("...")}` 这种"把旧值抄回去"的代码，而抄漏一个键
    就是一次**静默的状态丢失**（在 `resume` 时才暴露）。
    "必须有值"的那部分由 `REQUIRED_STATE_FIELDS` + `initial_state()` 保证，可测。
    """

    # --- 组 1｜请求与身份（`trusted_context` 产出，之后只读）---
    # ⚠️ 这 8 个字段是 `core/contracts.IdentityContext` 的**扁平形态**（同一事实，无第二份定义）：
    #    `IdentityContext` 是 L0 的 frozen 值对象（类型层不可变），
    #    而 LangGraph 的状态是 dict（需要扁平键）。唯一允许做这个转换的地方是
    #    `identity_fields()` —— 不要在别处手写 `{"tenant_id": ctx.tenant_id, ...}`。
    trace_id: str
    task_id: str
    session_id: str
    tenant_id: str                     # PII
    user_id: str                       # PII
    role: Role
    scope_claims: tuple[str, ...]
    shop_ids: tuple[str, ...]          # 空 = 不限制（07 §13.2）
    raw_question: str                  # ⚠️ 唯一允许出站的用户输入
    options: OpaquePayload             # U-24：`RunOptions`
    idempotency_key: str | None

    # --- 组 2｜归一化（`normalize`）---
    normalized_question: str
    time_range: OpaquePayload | None   # U-24：`{start, end, expr, tz}`；基准只来自语义包（N-26）
    resolved_terms: tuple[OpaquePayload, ...]   # U-24：`{surface, canonical, kind}`
    unresolved_terms: tuple[str, ...]  # → 语义层待补清单（FR-11.5）
    time_parse_ok: bool                # false → 澄清，**不猜测**

    # --- 组 3｜意图（`intent`）---
    intent: str                        # U-25：四分类枚举待 `core/enums.py` 定义
    intent_detail: OpaquePayload | None   # `{refuse_kind?, reason_code}`

    # --- 组 4｜检索（`link`）---
    # ⚠️ `candidates` 是**体积字段**：只放截断后的摘要（id + score），全量在 Redis。
    candidates: tuple[OpaquePayload, ...]
    candidates_summary: OpaquePayload | None  # §6.10 监控口径（dense/sparse/graph_added/value_hits/fused_top）
    retrieval_mode: str                # `hybrid | sparse_only` → `meta.retrieval_mode`（C-11）
    linking_stats: OpaquePayload | None
    few_shot: tuple[OpaquePayload, ...]   # Top-3–5，值已脱敏
    ambiguities: tuple[OpaquePayload, ...]

    # --- 组 5｜计划与绑定（`plan` / `bind`）---
    plan: OpaquePayload | None         # 结构化计划；**不含 SQL**
    plan_summary: OpaquePayload | None # → `stage=plan_ready`（C-01）
    bindings: tuple[OpaquePayload, ...]   # 仅列名 + 资产名，**不含数据**
    binding_status: str                # `unique | ambiguous | none`
    binding_ambiguity: OpaquePayload | None

    # --- 组 6｜SQL 生成（`gen_sql`）---
    sql_text: str                      # ⚠️ **N-17：持久化供审计，但永不回灌 prompt**
    sql_params: OpaquePayload          # 参数化绑定（N-04）
    sql_dialect: str                   # P0 = `postgres`
    sql_candidates: tuple[OpaquePayload, ...]   # ⚠️ 体积字段：只留选中项入检查点
    prompt_version: str                # N-19
    model_version: str                 # N-19
    confidence: float                  # ⚠️ **P0 不下发前端**（06 §4.4：未校准概率有害）

    # --- 组 7｜闸门（`gate1/2/3`）---
    gate_results: Mapping[GateNo, GateResult]
    limit_injected: OpaquePayload | None  # `{injected, original_limit?}`（§7.3）
    applied_predicates: tuple[str, ...]   # 注入的默认谓词（审计可追溯）
    scope: ScopeInfo | None               # A.1.5 三级披露；gate2 确定性算出（§7.4）

    # --- 组 8｜执行（`execute`）---
    result_rows: tuple[tuple[Any, ...], ...]  # ⚠️ 体积字段：脱敏后存 Redis（TTL 3600s）
    result_ref: str                    # Redis 键 `result:{tenant_id}:{task_id}` —— 替代上面的体积字段
    result_columns: tuple[ColumnMeta, ...]
    row_count: int
    truncated: bool                    # **只由 LIMIT 触发**（N-06）
    exec_error: OpaquePayload | None   # ⚠️ 仅脱敏摘要；**严禁原始库错误**（N-11）
    result_fingerprint: str            # 结果集哈希（缓存/去重）

    # --- 组 9｜纠错（`repair`）---
    repair_round: int                  # 0–2（NFR-2.4）
    repair_history: tuple[OpaquePayload, ...]   # ✅ 仅脱敏摘要可出站

    # --- 组 10｜呈现（`present`）---
    chart_spec: OpaquePayload | None
    insight: OpaquePayload | None      # `{text, caveats[], citations[]}`
    degradations: tuple[OpaquePayload, ...]

    # --- 组 11｜终态与计量（出口节点）---
    terminal: OpaquePayload | None     # `{event, code?, reason?}` —— **一旦设置不可再改**（N-08）
    clarify: OpaquePayload | None      # `{clarify_id, question, options[], reason}`
    outcome: Outcome                   # 对齐 PRD §9.2 `audit_log.outcome`
    latency_ms: OpaquePayload          # 键见 C-04
    tokens: OpaquePayload              # 键见 C-03
    cost_cny: Decimal                  # ⚠️ 若 `JsonPlusSerializer` 不支持 Decimal → 改存字符串


# ---------------------------------------------------------------------------
# 契约自检
# ---------------------------------------------------------------------------


def assert_state_field_annotations_complete() -> None:
    """静态自检：每个字段都被**恰好一次**标注（分组 + 三列分类）。

    为什么要有这个函数（而不是只靠注释）：

    | 漏了什么 | 检查能不能发现 | 后果 |
    |---|---|---|
    | 字段没进任何组 | ✅ 本函数 | 它没有 `PROMPT` 归类 → 默认禁出站没问题，但**没有归属**，W4 不知道谁产出它 |
    | 字段进了两组 | ✅ 本函数 | 同一个键两份归属定义 |
    | 体积字段漏 ⊂ `CHECKPOINT_EXCLUDED_FIELDS` | ✅ 本函数（见下） | 检查点膨胀，**在压测时才暴露**（R-10） |

    ⚠️ **诚实边界**：本函数证明的是"**本文件自洽**"，证明不了"本文件 == 07 §5.2"。
    后者的唯一手段是与 07 的表逐行对照（人工评审）。这一点必须写出来，
    否则一个绿色的自检会被误读成"契约已被验证"。
    """
    declared = set(GraphState.__annotations__)
    absent = declared - set(FIELD_GROUP)
    if absent:
        raise AssertionError(f"`GraphState` 有字段未登记分组（07 §5.2 的组归属缺失）：{sorted(absent)}")

    stale = set(FIELD_GROUP) - declared
    if stale:
        raise AssertionError(
            f"`STATE_GROUPS` 里有 `GraphState` 已不存在的字段（改字段名时漏改分组）：{sorted(stale)}"
        )

    # 体积字段：07 §5.2 点名的三个，必须都在 `CHECKPOINT_EXCLUDED_FIELDS` 里
    volumetric = {"candidates", "sql_candidates", "result_rows"}
    missing_volumetric = volumetric - CHECKPOINT_EXCLUDED_FIELDS
    if missing_volumetric:
        raise AssertionError(
            f"07 §5.2.1 点名的体积字段未排除出检查点：{sorted(missing_volumetric)} → "
            f"检查点会膨胀（R-10）"
        )

    unknown = (CHECKPOINT_EXCLUDED_FIELDS | PROMPT_ALLOWED_FIELDS | PII_FIELDS) - declared
    if unknown:
        raise AssertionError(f"标注集合含不存在的字段（改名时漏改标注）：{sorted(unknown)}")

    # N-12：PII **永不**出站
    leak = PII_FIELDS & PROMPT_ALLOWED_FIELDS
    if leak:
        raise AssertionError(f"PII 字段被同时标为可进 PROMPT（违反 N-12）：{sorted(leak)}")

    # 组 1 必须与 `REQUIRED_STATE_FIELDS` 一致（组 1 是"必须有值"的那部分）
    if frozenset(STATE_GROUPS["1_request_identity"]) != REQUIRED_STATE_FIELDS:
        raise AssertionError("`REQUIRED_STATE_FIELDS` 与组 1 定义不一致")


def is_checkpointable(field: str) -> bool:
    """该字段是否入检查点。`False` 表示它只放摘要/引用（见 §5.2.1）。"""
    _require_known(field)
    return field not in CHECKPOINT_EXCLUDED_FIELDS


def is_prompt_allowed(field: str) -> bool:
    """该字段是否允许进 LLM 上下文。**默认 `False`**（G-3：需显式授权）。"""
    _require_known(field)
    return field in PROMPT_ALLOWED_FIELDS


def _require_known(field: str) -> None:
    if field not in FIELD_GROUP:
        raise KeyError(f"未知状态字段 {field!r} —— 字段名必须与 07 §5.2 逐字一致")


# ---------------------------------------------------------------------------
# 构造
# ---------------------------------------------------------------------------


def identity_fields(identity: IdentityContext) -> dict[str, Any]:
    """`IdentityContext` → `GraphState` 的组 1 扁平字段。

    **唯一允许做这个转换的地方**（G-2 / U-24 的对应措施）：
    在别处手写 `{"tenant_id": ctx.tenant_id, ...}` 就等于把"身份有哪些字段"
    写了两遍，而漏抄一个键的表现是"某个节点拿不到租户" —— 在跨租户场景下它是**安全**问题。

    ⚠️ 注意本函数**不含** `raw_question` / `options` / `idempotency_key`：
    它们来自 API 层（请求体），**不属于身份**。把请求体塞进身份构造器
    正是"身份可由客户端影响"的入口（07 §13.1 禁令 1/2）。
    """
    return {
        "trace_id": identity.trace_id,
        "task_id": identity.task_id,
        "session_id": identity.session_id,
        "tenant_id": identity.tenant_id,
        "user_id": identity.user_id,
        "role": identity.role,
        "scope_claims": identity.scope_claims,
        "shop_ids": identity.shop_ids,
    }


def initial_state(
    identity: IdentityContext,
    *,
    raw_question: str,
    options: OpaquePayload | None = None,
    idempotency_key: str | None = None,
) -> GraphState:
    """图入口的初始状态（组 1 + 组 11 的三个计量初值）。

    ⚠️ **只填组 1 与"出口才写"的字段初值**，不预先塞空值给后续各组：
    "字段存在但为 `None`"与"字段不存在"在 LangGraph 的 `resume` 语义下**不同** ——
    前者会让"这个节点跑过没有"无法判断（`state.get(k) is None` 有两种含义）。
    条件边一律用显式判定（如 `state.get("time_parse_ok") is False`），不靠 `None` 兜底。

    ⚠️ `raw_question` 的长度（1–500）与 `options` 的白名单校验**不在这里做** ——
    它们属于**请求校验**（`api/dto/`，W4）。在图上做会让"非法请求"变成
    "已进图的异常"，而那时已经产生了 checkpoint 与审计的中间态。
    """
    assert_state_field_annotations_complete()
    state: GraphState = identity_fields(identity)  # type: ignore[assignment]
    state["raw_question"] = raw_question
    if options is not None:
        state["options"] = options
    if idempotency_key is not None:
        state["idempotency_key"] = idempotency_key
    return state


def assert_terminal_is_settable(state: GraphState) -> None:
    """**N-08「有且仅有 1 个终止事件」的写入口检查**。

    07 §5.4 的 `route_terminal` 要求"任何路径重复设终态 → 拒绝并被
    `ui_contract_violation` 告警捕获"。本函数是该判据的**唯一实现点** ——
    ⚠️ 交接说明：`route_terminal` 与告警的接线归 W4（`graph/edges.py`），
    W1B 只提供判定（`docs/08 §3.6`）。
    """
    if state.get("terminal") is not None:
        raise ValueError(
            "终态已被设置（N-08）—— 一个 run 只允许 1 个终止事件。"
            "重复设置说明存在两条出口路径同时在跑，必须判为图缺陷而不是覆盖。"
        )
