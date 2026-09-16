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
from enum import StrEnum
from itertools import pairwise
from typing import TYPE_CHECKING, Any, Final

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph

from app.core.config import Settings
from app.graph.state import GraphState
from app.repo.dsn import to_libpq_conninfo

if TYPE_CHECKING:  # pragma: no cover - 仅为类型检查
    from langgraph.graph.state import CompiledStateGraph
    from psycopg_pool import AsyncConnectionPool

__all__ = [
    "GRAPH_VERSION",
    "PER_RUN_STRATEGIES",
    "SINGLE_CONN_STRATEGIES",
    "STUB_NODE_DELAY_S",
    "STUB_NODE_NAMES",
    "STUB_RECURSION_LIMIT",
    "CheckpointSetupOutcome",
    "CheckpointStrategy",
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
