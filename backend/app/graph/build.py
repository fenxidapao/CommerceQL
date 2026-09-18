"""图装配（07 §3.2：`graph/build.py` = "装配 + 图版本号"）。

归属窗口：W1B（`docs/08 §4.1`）。

⚠️ **本阶段（1B）只装配"桩图"**：`stub_a → stub_b → stub_c`。
真实装配（17 个节点 + 条件边 + 事件发射）归 W4（`docs/08 §3.6`，`graph/` 全部独占）。
本文件当前的职责有三个，且都**不因 W4 接管而作废**：

1. **checkpoint 装配的唯一决定点** —— 用哪个 saver 形态（单例 / per-run）、
   连接从哪来（单独连接 / 共享池）**只在这里决定**。
   这是 N-14「checkpoint 与业务查询、元数据写入各自独立」的落点，也是 **T-A1 的结论落地处**：
   T-A1 一旦裁定哪个装配可用，改的是本文件的 `CheckpointStrategy`，不是散落各处。
2. **图版本号**（07 §5.5"版本固定"）：`GRAPH_VERSION`。
3. **桩图** —— DoD①"空链路可跑通"的执行体，以及 T-A1 压测的被压对象。

--------------------------------------------------------------------------
⭐ 为什么把"四种装配"写进生产代码里，而不是只写在压测脚本里
--------------------------------------------------------------------------
T-A1 的目的是回答"**生产该用哪种装配**"，而不是"哪种装配更快"。
若压测脚本自己造 saver，那么结论对应的代码**与生产不是同一份** ——
这是一种特别隐蔽的偏差：脚本里写对了，生产里写错了，而两者都"看起来对"。
（同类事故：把测试夹具与生产装配分开写，最后测的不是要上线的东西。）

因此四种装配在**同一个枚举 + 同一个工厂**里，压测脚本与将来的生产代码共用它。

⚠️ **诚实边界（必须写在代码里，否则结论会被误读）**：

| 事项 | 现状 |
|---|---|
| 桩节点**不含真实 SQL** | 故 `analytics` / `metadata` 池不参与 T-A1，本轮结论**只对 checkpoint 池有效** |
| 桩节点**不调 LLM** | 节点内的 `sleep` 是对"LLM 期间"的**模拟**，不是实测延迟 |
| `pgbouncer` 未起 | 应用侧逻辑连接算术（80）已验证；pgbouncer 30 的那半**未验** |
| `langgraph` 是开放区间依赖 | 本结论**绑定** `langgraph 1.2.11` / `langgraph-checkpoint-postgres 3.1.2`（用户已裁定钉版本，登记见交付说明） |
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable, Mapping
from enum import StrEnum
from itertools import pairwise
from typing import TYPE_CHECKING, Any, Final, cast

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph

from app.core.config import Settings
from app.graph.state import GraphState
from app.repo.dsn import to_libpq_conninfo

if TYPE_CHECKING:  # pragma: no cover - 仅为类型检查
    from langgraph.graph.state import CompiledStateGraph
    from psycopg_pool import AsyncConnectionPool

__all__ = [
    "GRAPH_RECURSION_LIMIT",
    "GRAPH_VERSION",
    "PER_RUN_STRATEGIES",
    "SINGLE_CONN_STRATEGIES",
    "STUB_NODE_DELAY_S",
    "STUB_NODE_NAMES",
    "STUB_RECURSION_LIMIT",
    "CheckpointSetupOutcome",
    "CheckpointStrategy",
    "build_graph",
    "build_stub_graph",
    "ensure_checkpoint_schema",
    "graph_version",
    "make_checkpointer",
]

#: 图版本号（07 §5.5"版本固定"）。**格式**：`major.minor.patch`。
#:
#: ⚠️ 它只标识**图结构**，不标识语义包 / prompt / 模型版本 ——
#: 会话级版本固定是"三者的组合"，由 W4 在 `graph/build.py` 的装配入口完成
#: （`docs/08 §3.6`）。本阶段只落这一个常量，不假装已完成版本固定。
GRAPH_VERSION: Final[str] = "0.1.0"

#: **真图**的 `recursion_limit`（07 §5.4 逐字：**25**；NFR-2.4 的 kill switch）。
#:
#: ⚠️ 它与 `STUB_RECURSION_LIMIT` **是两个常量而不是一个**：值相同是巧合，
#: 语义不同（桩图的 25 只是"与真图同构"，真图的 25 是 G4 判据 —— 超限即 `error(INTERNAL)`
#: + P0 告警）。合成一个会让"调桩图压测参数"顺手改掉生产上限。
#: 两处都是**调用期**参数（LangGraph 只在 `config` 里读它）。
GRAPH_RECURSION_LIMIT: Final[int] = 25

#: 桩节点每步的模拟耗时。
#:
#: ⚠️ **它不是"随便挑的一个数"**：T-A1 要观测的是"**节点之间**连接还持不持有"，
#: 因此这个值必须**大于采样周期**（否则整 run 只有 1–2 个采样点，结论不可信）。
#: 生产值 0.05s 用于 DoD① 快速跑通；T-A1 用 0.25s（见 `scripts/probe_checkpoint_pool.py`）。
STUB_NODE_DELAY_S: Final[float] = 0.05

#: 桩节点名（顺序 = 执行顺序）。**T-A1 的每个节点都会写一次检查点** —— 这正是被观测的行为。
STUB_NODE_NAMES: Final[tuple[str, str, str]] = ("stub_a", "stub_b", "stub_c")

#: `ainvoke` 时的 `recursion_limit`（07 §5.5 定案 25）。
#:
#: ⚠️ 它是**调用期**参数而不是装配期参数（LangGraph 只在 `config` 里读它）。
#: 桩图只有 3 个节点，远低于上限 —— 本常量存在的意义是让"桩图与真图在这一点上同构"，
#: 避免将来把桩图的行为当作真图的行为。
STUB_RECURSION_LIMIT: Final[int] = 25


# ============================================================================
# checkpoint 装配（★ T-A1 的结论落在这里）
# ============================================================================


class CheckpointStrategy(StrEnum):
    """checkpoint 的四种装配形态（T-A1 的四个实验臂）。

    ⚠️ 四种**不是"四个优化档位"，而是四条互斥的架构路线**：
    它们对连接池的影响相差一个数量级，选错一条会让 50 并发要么打满池、要么被锁串行。

    | 值 | saver 数 | saver 的连接来源 | 07 §16.3 的说法 |
    |---|---|---|---|
    | `SINGLE_SAVER_SHARED_POOL` | 1 | 共享 `AsyncConnectionPool` | 未讨论 |
    | `SINGLE_SAVER_SINGLE_CONN` | 1 | 单条 `AsyncConnection` | "每节点写完即还"（推断，**待验**） |
    | `PER_RUN_OWN_CONN` | N（每 run 一个） | 每个 saver 自己的连接 | "整 run 长持"（担心，**待验**） |
    | `PER_RUN_SHARED_POOL` | N | 全部共享一个池 | 07 §16.3 **完全没考虑**这一种 |

    ⭐ 第 4 种不是凑数的：它可能**同时**拿到"并发"（N 个 saver，没有单 saver 的锁串行）
    与"受控连接数"（共享池），是 §16.3 的二选一之外最可能的答案。
    这正是 T-A1 必须实测而不能靠推导的原因。
    """

    SINGLE_SAVER_SHARED_POOL = "single_saver_shared_pool"
    SINGLE_SAVER_SINGLE_CONN = "single_saver_single_conn"
    PER_RUN_OWN_CONN = "per_run_own_conn"
    PER_RUN_SHARED_POOL = "per_run_shared_pool"


#: 需要"每 run 一个 saver"的策略（变体 C / D）。
#:
#: ⚠️ 为什么"每 run 一个 saver"是**可能必需**的：每个 saver 实例持有一把
#: `asyncio.Lock` 串行化它自己的全部检查点 I/O（`langgraph/checkpoint/postgres/aio.py`
#: 的 `_cursor()`）。单 saver 的检查点吞吐上限 = 同时刻 1 个操作 —— **池开多大都无济于事**。
PER_RUN_STRATEGIES: Final[frozenset[CheckpointStrategy]] = frozenset(
    {CheckpointStrategy.PER_RUN_OWN_CONN, CheckpointStrategy.PER_RUN_SHARED_POOL}
)

#: 需要"单条连接"而非池的策略。
#:
#: ⚠️ 单条连接 = saver **整个生命周期长持 1 条**（`_cursor()` 直接 `yield conn`，不借还）：
#: · `SINGLE_SAVER_SINGLE_CONN` → 全程长持 **1** 条；
#: · `PER_RUN_OWN_CONN` → N 并发 = **N 条长持** —— 这正是 07 §16.3 担心而无法推导的情形。
SINGLE_CONN_STRATEGIES: Final[frozenset[CheckpointStrategy]] = frozenset(
    {CheckpointStrategy.SINGLE_SAVER_SINGLE_CONN, CheckpointStrategy.PER_RUN_OWN_CONN}
)


async def make_checkpointer(
    strategy: CheckpointStrategy,
    settings: Settings,
    *,
    pool: AsyncConnectionPool | None = None,
    setup: bool = True,
) -> AsyncPostgresSaver:
    """按策略造一个 `AsyncPostgresSaver` 并（可选）建表。

    ⚠️ **`setup=True` 会执行 DDL**（`CREATE SCHEMA IF NOT EXISTS lg` + 建表）。
    它由 `app_rw` 执行，因此迁移 `0001` 必须先给 `app_rw` 授予 `lg` schema 的
    `USAGE, CREATE`（已授）。**不要**在每次请求路径上调 `setup()`：
    它在 PostgreSQL 上取 `pg_advisory_xact_lock`，并发调用会串行等待 ——
    而那会被 T-A1 误读成"checkpoint 是长持的"（一个纯粹由探针自身引入的假象）。

    ⚠️ **调用方负责关闭**：本函数只造，不接管生命周期。
    单条连接的形态必须由调用方在 `finally` 里 `await conn.close()`，
    否则进程退出时 `psycopg` 会报"connection was closed in flight"噪音警告。

    ⚠️ `application_name` **必须由池/连接带上**：T-A1 的 `pg_stat_activity` 观测
    靠它区分"这条连接是谁的"。它由 `app/repo/pools.py` 的 `_connect_args` 统一注入，
    本函数不重复拼字符串（否则一份常量写两处）。
    """
    from app.repo.pools import build_checkpoint_pool, checkpoint_connect_kwargs

    if strategy in SINGLE_CONN_STRATEGIES:
        import psycopg

        # ⚠️ 必须带上 `checkpoint_connect_kwargs()`（`application_name` + `search_path=lg`）：
        # 少了 `search_path`，`saver.setup()` 的第一条 DDL 会落到 `public` 并因无权限而失败。
        ckpt = checkpoint_connect_kwargs()
        conn = await psycopg.AsyncConnection.connect(
            to_libpq_conninfo(settings.DATABASE_URL),
            # ⚠️ 显式列出四个键而不是 `**ckpt`：`psycopg.AsyncConnection.connect` 的签名
            # 把可选参数写成了具名关键字（`context` / `row_factory` / …），
            # 展开一个 `dict[str, Any]` 会让 mypy 把它们全部认成类型冲突。
            # 而"为了过类型检查去改 connect 的签名"是更坏的选择。值仍取自唯一来源。
            application_name=ckpt["application_name"],
            options=ckpt["options"],
            autocommit=ckpt["autocommit"],
            prepare_threshold=ckpt["prepare_threshold"],
        )
        saver = AsyncPostgresSaver(conn)  # type: ignore[arg-type]
        if setup:
            await saver.setup()
        return saver

    own_pool = pool is None
    target_pool = pool if pool is not None else build_checkpoint_pool(settings)
    if own_pool:
        await target_pool.open()
    saver = AsyncPostgresSaver(target_pool)  # type: ignore[arg-type]
    if setup:
        await saver.setup()
    return saver


# ============================================================================
# 启动期：确保 lg 表族就绪（供 checkpointer 健康探针判定）
# ============================================================================


class CheckpointSetupOutcome(StrEnum):
    """`ensure_checkpoint_schema` 的三种结果。

    ⚠️ 为什么是枚举而不是 `bool`：`bool` 只有两格，而这里有**三种事实**。
    用 `False` 同时表示"表族本来就齐"与"连不上、查都没查成"，会让启动日志写成
    "无需建表" —— 而真实情况是"**根本没看到库**"。症状（服务起来了但 checkpointer 不健康）
    与日志（一切正常）方向相反，排查会被引到完全错误的地方。
    """

    ALREADY_PRESENT = "already_present"
    CREATED = "created"
    #: 池连不上（未部署 / DNS 不通 / 超时）→ **不建表、不抛异常**，交给 readiness 如实上报 503。
    UNREACHABLE = "unreachable"


async def ensure_checkpoint_schema(pool: AsyncConnectionPool) -> CheckpointSetupOutcome:
    """确保 `lg` 表族就绪。

    ⚠️ 为什么"先查再建"，而不是每次启动都 `await saver.setup()`：
    `setup()` 在 PostgreSQL 上取 `pg_advisory_xact_lock`（见 `make_checkpointer` 的注释），
    每次启动都跑一遍会：
    ① 在每次部署时产生一段可避免的锁等待；
    ② 更糟的是，它让"启动期有一次 DDL"变成常态 —— 于是**当它真的失败时没人会注意到**
       （报警疲劳）。只有"表族不齐"这一种真实异常才触发 DDL，才值得被看见。

    ⚠️ 表族清单取自 `app/repo/health.py`，**不在这里再写一份**：
    "lg 里该有哪些表"这个事实同时被本函数（决定要不要建）与健康探针（决定健不健康）使用，
    两处各写一遍就会分叉 —— 而分叉的表现是"探针说健康、图却跑不起来"。

    ⚠️ **连不上时不抛异常**（返回 `UNREACHABLE`）：库没起来不该让进程起不来
    （07 §18.2：readiness 摘流量、不重启）。捕获范围**只包住"查表族"这一步** ——
    过了这一步说明池是通的，此时 `setup()` 再失败就是**真错误**，必须照常抛出去。
    """
    from app.repo.health import CHECKPOINT_TABLE_FAMILY
    from app.repo.pools import CHECKPOINT_SCHEMA
    from app.repo.reachability import is_unreachable

    try:
        present = await _count_present_checkpoint_tables(
            pool, CHECKPOINT_SCHEMA, CHECKPOINT_TABLE_FAMILY
        )
    except Exception as exc:
        if not is_unreachable(exc):
            raise
        return CheckpointSetupOutcome.UNREACHABLE

    if present == len(CHECKPOINT_TABLE_FAMILY):
        return CheckpointSetupOutcome.ALREADY_PRESENT
    saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
    await saver.setup()
    return CheckpointSetupOutcome.CREATED


async def _count_present_checkpoint_tables(
    pool: AsyncConnectionPool, schema: str, tables: tuple[str, ...]
) -> int:
    """数 `lg` 里已存在的表族成员（用**不抛错**的 `to_regclass`）。

    ⚠️ **必须显式给 `timeout`**：池的默认等待是 30s，而这是**启动路径**上的一次取连接 ——
    依赖不可达时实测把启动卡住 30.65s。见 `POOL_ACQUIRE_TIMEOUT_S` 的推导与边界。
    """
    from app.repo.pools import POOL_ACQUIRE_TIMEOUT_S

    wanted = ", ".join(f"'{schema}.{t}'" for t in tables)
    async with pool.connection(timeout=POOL_ACQUIRE_TIMEOUT_S) as conn:
        cursor = await conn.execute(
            f"SELECT count(*) FROM unnest(ARRAY[{wanted}]) AS s(name) "
            f"WHERE to_regclass(s.name) IS NOT NULL"
        )
        row = await cursor.fetchone()
    return int(row[0]) if row is not None else 0


# ============================================================================
# 桩图
# ============================================================================


def _make_stub_node(name: str, delay_s: float) -> Any:
    """造一个桩节点：**只读 state → sleep → 写 state**（G-1 的三件事里没有"业务规则"）。

    ⚠️ 桩节点**绝不碰数据库**（07 §8.1 纪律 1 的同源要求）：
    若桩节点在"LLM 期间"持有 analytics 连接，那 T-A1 观测到的连接数里
    混进了**探针自己造的负载** —— 结论就不可用了。

    ⚠️ 桩节点返回**空增量 `{}`**，而不是塞一个"我跑过了"的标记字段。
    这一点值得说明，因为它看起来是"少做了什么"：
    · `GraphState` 的字段由 07 §5.2 **穷举**，往里面写第 4 个来源的字段
      就是 §5.2 与代码的**第二份真相**（U-18 的教训）；
    · "节点跑过没有"应当由**检查点**回答（每节点一次写入，07 §5.5），
      而不是由状态里的自述标记回答 —— 后者在 `resume` 时会被恢复成旧值，
      于是"跑过了"与"上次跑过了"无法区分。
    """

    async def _node(_state: GraphState) -> dict[str, Any]:
        await asyncio.sleep(delay_s)
        return {}

    _node.__name__ = name
    return _node


def build_stub_graph(
    checkpointer: AsyncPostgresSaver | None = None,
    *,
    node_delay_s: float = STUB_NODE_DELAY_S,
) -> CompiledStateGraph[GraphState, None, GraphState, GraphState]:
    """装配桩图：`stub_a → stub_b → stub_c`（**线性、无分支**）。

    ⚠️ **线性是有意的**：T-A1 要观测的是"节点之间连接持不持有"，
    任何分支都会让"每个 run 写了几个检查点"变成变量，从而无法把
    "连接数变化"归因到"持有语义"上。条件边的正确性归 W4。

    ⚠️ `recursion_limit` **不是本函数的参数** —— 它是 `ainvoke` 的 `config` 项，
    在图上"设置"它并不生效（LangGraph 只在调用时读）。为了不让调用方
    以为"装配期设过了"，这里改成一个显式常量 `STUB_RECURSION_LIMIT` 由调用方传入。

    ⚠️ 返回的是**编译后的图**，`checkpointer=None` 时**不落任何检查点**。
    `checkpointer=None` 只用于单元测试（验拓扑），T-A1 与 DoD① 都必须带 saver ——
    否则"空链路可跑通"证明的是一个**永远不会在生产出现的形态**。
    """
    builder: StateGraph[GraphState, None, GraphState, GraphState] = StateGraph(GraphState)
    for name in STUB_NODE_NAMES:
        builder.add_node(name, _make_stub_node(name, node_delay_s))
    builder.add_edge(START, STUB_NODE_NAMES[0])
    for upstream, downstream in pairwise(STUB_NODE_NAMES):
        builder.add_edge(upstream, downstream)
    builder.add_edge(STUB_NODE_NAMES[-1], END)
    return builder.compile(checkpointer=checkpointer)


def graph_version() -> str:
    """当前图版本（07 §5.5"版本固定"）。

    ⚠️ 会话级版本固定 = `GRAPH_VERSION` + 语义包版本 + prompt 版本（三者都要进审计），
    组装归 W4。本函数只暴露图结构版本这一项，避免在 W1B 就假造一个"组合版本"。
    """
    return GRAPH_VERSION


# ============================================================================
# 真图装配（W4 接管；07 §5.3 的 16 主节点 + 3 出口）
# ============================================================================


#: 每节点超时（秒；07 §5.3 契约表"超时"列的逐字落地；HANDOFF §五-5 已裁口径）。
#:
#: ⚠️ **"—" 的节点不进表**：`trusted_context` 与三个出口节点在 07 §5.3 表里的超时是
#: "—"（它们是纯内存操作 / 终态构造），给它们配超时等于发明一个文档里没有的数值。
#: ⚠️ `EXECUTE` 的 30s 是**上限**（表值"交互 8s / 上限 30s"）—— 交互级超时已由
#: `statement_timeout_ms`（`GraphDeps`，默认 8s）在 SQL 层承担，这里是兜底上限。
#: ⚠️ 超时值进入**契约**：`tests/contract/test_graph_timeout_contract.py` 钉"表键集 =
#: 16 节点里 07 给了超时值的那些"，改这里必须同步 07 §5.3。
NODE_TIMEOUT_S: Final[dict[str, float]] = {
    "normalize": 2.0,
    "intent": 1.5,
    "link": 4.0,
    "plan": 3.0,
    "bind": 0.2,
    "gen_sql": 2.5,
    "gate1_ast": 0.1,
    "gate2_policy": 0.1,
    "gate3_cost": 1.0,
    "execute": 30.0,
    "mask": 0.1,
    "audit_pre": 1.0,
    "present": 2.0,
    "audit_supp": 0.5,
    "repair": 3.0,
}


def _with_node_timeout(name: str, fn: Any, *, overrides: Mapping[str, float] | None = None) -> Any:
    """给节点套 `asyncio.timeout()`（HANDOFF §五-5：每节点超时 = asyncio.timeout 包装）。

    ⚠️ **超时 ≠ 节点内失败**：节点内部的失败转移（LLM 不可用 → degraded、EXPLAIN
    不可用 → 跳过 gate3……）在节点**跑着**时才有机会执行；超时意味着节点**没跑完**，
    那些转移逻辑没机会触发。故只有两条出路：

    | 节点 | 超时转移 | 依据 |
    |---|---|---|
    | `present` | `report_degraded(PRESENT_FAILED, TABLE_ONLY)` + 空增量（= 仅表格） | 07 §14.2 F4 的超时同形：与节点内部失败路径（`present.py` 的 report_degraded + `return {}`）**完全同形**，只是触发源不同 |
    | 其余 | 告警 + **re-raise** → `runner._drive` 兜底 `error(INTERNAL)` | 节点没跑完 = 工程故障；对着一个没产出结果的节点假装"降级成功"才是谎报 |

    🔴 `audit_supp` **不在"吞掉"之列**（虽然表里它"失败不阻断"）：那个"不阻断"说的是
    **段 2 写库失败**（节点内部已 try/except 告警），而该节点还兼发 `complete` 终态 ——
    超时时连终态都没构造出来，吞掉 = 流无终态（违反 N-08）。

    ⚠️ `overrides` 仅供**测试**放大超时（0.1s 的闸门节点在慢 CI 上会假阳性）；
    生产装配不传 —— 契约值只能有一份来源（本表）。
    """
    limit = (overrides or {}).get(name) or NODE_TIMEOUT_S.get(name)
    if limit is None:
        return fn

    from app.core.enums import ActionTaken, DegradedReason
    from app.graph.context import current_run_context_or_none
    from app.obs.logging import get_logger as _get_logger

    timeout_log = _get_logger(__name__)

    @functools.wraps(fn)
    async def _timed(state: GraphState) -> dict[str, Any]:
        try:
            async with asyncio.timeout(limit):
                return cast("dict[str, Any]", await fn(state))
        except TimeoutError:
            if name == "present":
                # F4 超时同形：降级为"仅表格"，不再构造 chart/insight（缺席 = 不发事件）。
                context = current_run_context_or_none()
                if context is not None:
                    context.report_degraded(
                        DegradedReason.PRESENT_FAILED,
                        ActionTaken.TABLE_ONLY,
                        {"stage": "present", "reason": "timeout", "limit_s": limit},
                    )
                timeout_log.error(
                    "node_timeout_degraded",
                    node=name,
                    limit_s=limit,
                    extra_fact="present 超时 → degraded(present_failed) 仅表格（§14.2 F4）",
                )
                return {}
            timeout_log.error(
                "node_timeout",
                node=name,
                limit_s=limit,
                extra_fact="节点超时未收口 → 上抛，由 runner 兜底 error(INTERNAL)（N-08 不留无终态的流）",
            )
            raise

    return _timed


def build_graph(
    checkpointer: AsyncPostgresSaver | None = None,
    *,
    node_timeout_overrides: Mapping[str, float] | None = None,
) -> CompiledStateGraph[GraphState, None, GraphState, GraphState]:
    """装配真图：19 个节点（16 主 + 3 出口）+ 07 §5.4 的 14 条条件边。

    ⚠️ **为什么可以装配成单例**（而 `PlannerEngine` 必须每请求一个）：
    节点**不持有依赖** —— 依赖经 `contextvars`（`graph/context.RunContext`）在每请求注入，
    所以同一张编译好的图可以被所有请求并发复用。反过来，把引擎挂在闭包里会让
    `PlannerEngine._pending` 跨请求串事件（`RELAY §给 W4` 的接线硬约束）。

    ⚠️ **`route_terminal` 的用法**：`edges.route_terminal` 回答"能不能结束"（返回 `END`），
    而 `edge.terminal_target` 回答"该走哪个出口节点"。本函数用的是后者 —— 因为
    出口三节点各自还要**构造终态 + 写段 1 审计**（见各节点 docstring），
    它们不能省掉直接 `END`。`route_terminal` 是那三个出口**之后**的收口：
    出口节点写终态 → 无条件边到 `END`（`route_terminal` 的幂等语义由
    `assert_terminal_is_settable` + `EventRecorder.push` 双保险承担，见 `edges.py` §三）。
    """
    from app.graph import edges
    from app.graph.nodes import (
        ALL_NODE_NAMES,
        AUDIT_PRE,
        AUDIT_SUPP,
        BIND,
        CLARIFY_OUT,
        ERROR_OUT,
        EXECUTE,
        GATE1_AST,
        GATE2_POLICY,
        GATE3_COST,
        GEN_SQL,
        INTENT,
        LINK,
        MASK,
        NORMALIZE,
        PLAN,
        PRESENT,
        REFUSE_OUT,
        REPAIR,
        TERMINAL_NODE_NAMES,
        TRUSTED_CONTEXT,
    )
    from app.graph.nodes import audit_pre as audit_pre_node
    from app.graph.nodes import audit_supp as audit_supp_node
    from app.graph.nodes import bind as bind_node
    from app.graph.nodes import clarify_out as clarify_out_node
    from app.graph.nodes import error_out as error_out_node
    from app.graph.nodes import execute as execute_node
    from app.graph.nodes import gate1_ast as gate1_node
    from app.graph.nodes import gate2_policy as gate2_node
    from app.graph.nodes import gate3_cost as gate3_node
    from app.graph.nodes import gen_sql as gen_sql_node
    from app.graph.nodes import intent as intent_node
    from app.graph.nodes import link as link_node
    from app.graph.nodes import mask as mask_node
    from app.graph.nodes import normalize as normalize_node
    from app.graph.nodes import plan as plan_node
    from app.graph.nodes import present as present_node
    from app.graph.nodes import refuse_out as refuse_out_node
    from app.graph.nodes import repair as repair_node
    from app.graph.nodes import trusted_context as trusted_context_node

    builders: dict[str, Any] = {
        TRUSTED_CONTEXT: trusted_context_node.trusted_context,
        NORMALIZE: normalize_node.normalize,
        INTENT: intent_node.intent,
        LINK: link_node.link,
        PLAN: plan_node.plan,
        BIND: bind_node.bind,
        GEN_SQL: gen_sql_node.gen_sql,
        GATE1_AST: gate1_node.gate1_ast,
        GATE2_POLICY: gate2_node.gate2_policy,
        GATE3_COST: gate3_node.gate3_cost,
        EXECUTE: execute_node.execute,
        MASK: mask_node.mask,
        AUDIT_PRE: audit_pre_node.audit_pre,
        PRESENT: present_node.present,
        AUDIT_SUPP: audit_supp_node.audit_supp,
        REPAIR: repair_node.repair,
        CLARIFY_OUT: clarify_out_node.clarify_out,
        REFUSE_OUT: refuse_out_node.refuse_out,
        ERROR_OUT: error_out_node.error_out,
    }
    assert set(builders) == set(ALL_NODE_NAMES), "节点表与 `nodes.__init__` 的常量表不一致"

    builder: StateGraph[GraphState, None, GraphState, GraphState] = StateGraph(GraphState)
    for name in ALL_NODE_NAMES:
        # T8：每节点超时包装（07 §5.3"超时"列；`NODE_TIMEOUT_S` 的 docstring 有全部口径）。
        builder.add_node(
            name, _with_node_timeout(name, builders[name], overrides=node_timeout_overrides)
        )

    #: 出口四节点：**终态优先守卫的公共去向**（见 `_guard` 的 docstring）。
    exits: tuple[str, ...] = (CLARIFY_OUT, REFUSE_OUT, ERROR_OUT, AUDIT_SUPP)

    def branch(
        router: Callable[[GraphState], str], *targets: str
    ) -> tuple[Callable[[GraphState], str], list[str]]:
        return _guard(router, targets, exits)

    # --- 入口：常量边，用 `add_edge` 而不是"恒返回同一目标的假条件边" ---
    # ⚠️ 条件边不给 `path_map` 时 LangGraph 无法内省目标，`get_graph()` 会把该边渲染成
    #    指向 `__end__` 的**占位**（早期版本实测如此）。拓扑快照是 T9 的对账依据，
    #    渲染成假的比不渲染更糟 —— 故本函数**每一条条件边都显式声明目标集**。
    builder.add_edge(START, TRUSTED_CONTEXT)
    builder.add_edge(TRUSTED_CONTEXT, NORMALIZE)

    # --- 主线（07 §5.4 的 14 条条件边逐条落位）---
    builder.add_conditional_edges(NORMALIZE, *branch(edges.route_after_normalize, INTENT))
    builder.add_conditional_edges(
        INTENT, *branch(edges.route_after_intent, REFUSE_OUT, CLARIFY_OUT, LINK)
    )
    builder.add_conditional_edges(
        LINK, *branch(edges.route_after_link, REFUSE_OUT, CLARIFY_OUT, PLAN)
    )
    builder.add_conditional_edges(
        PLAN, *branch(edges.route_after_plan, REFUSE_OUT, GEN_SQL)
    )
    builder.add_conditional_edges(
        BIND, *branch(edges.route_after_bind, CLARIFY_OUT, REFUSE_OUT, GEN_SQL)
    )
    builder.add_conditional_edges(GEN_SQL, *branch(edges.route_after_gen_sql, GATE1_AST))
    builder.add_conditional_edges(
        GATE1_AST, *branch(edges.route_after_gate1, GATE2_POLICY, ERROR_OUT)
    )
    builder.add_conditional_edges(
        GATE2_POLICY, *branch(edges.route_after_gate2, GATE3_COST)
    )
    builder.add_conditional_edges(
        GATE3_COST, *branch(edges.route_after_gate3, EXECUTE, AUDIT_SUPP)
    )
    builder.add_conditional_edges(
        EXECUTE, *branch(edges.route_after_execute, MASK, REPAIR)
    )
    builder.add_conditional_edges(MASK, *branch(edges.route_after_mask, AUDIT_PRE))
    builder.add_conditional_edges(AUDIT_PRE, *branch(edges.route_after_audit_pre, PRESENT))
    builder.add_conditional_edges(PRESENT, *branch(edges.route_after_present, AUDIT_SUPP))
    builder.add_conditional_edges(REPAIR, *branch(edges.route_after_repair, GATE1_AST))
    builder.add_edge(AUDIT_SUPP, END)

    # 出口三节点 → END（终态与段 1 审计都由它们自己收口，见各节点 docstring）。
    for name in TERMINAL_NODE_NAMES:
        builder.add_edge(name, END)

    return builder.compile(checkpointer=checkpointer)


def _guard(
    router: Callable[[GraphState], str],
    targets: tuple[str, ...],
    exits: tuple[str, ...],
) -> tuple[Callable[[GraphState], str], list[str]]:
    """给一条 §5.4 条件边套上"**终态优先**"守卫，并**显式列出合法目标集**。

    ⚠️ 为什么要一个统一包装，而不是逐条改 `edges.py`：
    `edges.py` 里 8 条路由**自己会**判 `state.terminal`（intent/link/plan/bind/mask/
    audit_pre/gate2/gate3），另 5 条**不判**（normalize/gen_sql/gate1/repair/present）。
    不判的那几条在"上游节点已设终态"的路径上会**继续往下跑**，下游节点第二次设终态
    → `assert_terminal_is_settable` 抛 `ValueError`（N-08 的正确行为）。
    那是"图缺陷"的表现，不该由**一次正常的拒答**触发（例：`gen_sql` 判 `refuse` 后
    若仍走 `gate1_ast`，就会拿空 SQL 过闸门 → 二次终态 → 崩）。
    ⇒ 判据只有一条、且与 `edges.py` 同源（`terminal_target`）：**已设终态就必须去出口**。
    包装而不是重写 `edges.py`，是因为那 14 条判据本身是纯函数、已被 `tests/contract/
    test_edges_contract.py` 覆盖，不该为这件事改语义 —— 该文件的五条"不判终态"与本节
    的补偿是**一处已登记的口径分歧**（交付件 §缺口），是否下沉到 `edges.py` 待架构裁决。

    ⚠️ `path_map` 是**第二个返回值**，不是为了好看：
    LangGraph 在 `path_map=None` 时无法内省该边的目标，`get_graph()` 会渲染出
    指向 `__end__` 的占位边（早期版本实测），于是"图快照"这个 T9 对账依据会是**假的**；
    给了 `path_map` 还会在**运行期校验**路由返回值必须落在集合内 —— 拼错节点名当场炸，
    而不是静默走到一个不存在的节点。故目标集 = 该路由自己的去向 ∪ 出口四节点。

    ⚠️ `asyncio.CancelledError` 与本包装无关：它继承 `BaseException`，节点内已保证冒泡。
    """

    allowed = list(dict.fromkeys([*targets, *exits]))

    def _routed(state: GraphState) -> str:
        if state.get("terminal") is not None:
            from app.graph.edges import terminal_target

            return terminal_target(state)
        return router(state)

    return _routed, allowed
