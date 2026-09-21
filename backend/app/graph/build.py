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


#: 非 LLM 节点的固定硬超时（秒；07 §5.3 契约表"超时"列逐字落地）。
#:
#: ⚠️ **LLM 节点不在本表**：走 DeepSeek 的 7 节点（normalize/intent/plan/gen_sql/present/repair/bind）
#: 的硬超时 = **本请求实际模型的客户端超时**（§10.2：flash 15s / pro 45s），执行期解析
#: （`_LLM_NODE_TASKS` → `_client_timeout_for` → `resolve_route` → `hard_timeout_s`）。
#: 这是 §5.3.0 规则 2 / U-107 附注①：单一超时点，LLM 节点不得自设更小的硬超时
#: （"预算当硬超时"正是本次要治的病害 —— 上游一慢就 `error(INTERNAL)` → `ok=0`）。
#: ⚠️ **"—" 的节点不进本表**：`trusted_context` 与三个出口节点在 07 §5.3 表里的超时是
#: "—"（纯内存操作 / 终态构造），给它们配超时等于发明一个文档里没有的数值。
#: ⚠️ `execute` 的 30s 是**上限**（表值"交互 8s / 上限 30s"）—— 交互级超时已由
#: `statement_timeout_ms`（`GraphDeps`，默认 8s）在 SQL 层承担，这里是兜底上限。
#: ⚠️ `link` 的 30s = `Settings.EMBEDDING_TIMEOUT_SECONDS`（`app/core/config.py`，07 §6.5，默认 30）：
#: 具名引用（U-22）—— link 内部 embedding 批量调用的客户端超时就是 30s，节点硬超时必须
#: ≥ 它，否则旧值 4.0s 先掐 ⇒ embedding 自己的超时/错误永远报不出来（U-107 附注① 同款病害第二处）。
#: ⚠️ 超时值进入**契约**：`tests/contract/test_graph_timeout_contract.py` 钉"哪些节点被计时 +
#: 逐字值"，改这里必须同步 07 §5.3。
NODE_TIMEOUT_S: Final[dict[str, float]] = {
    "link": 30.0,
    "gate1_ast": 0.1,
    "gate2_policy": 0.1,
    "gate3_cost": 1.0,
    "execute": 30.0,
    "mask": 0.1,
    "audit_pre": 1.0,
    "audit_supp": 0.5,
}

#: LLM 节点 → `LlmTask` 值：硬超时 = 该 task 路由到的模型的客户端超时（执行期解析）。
#:
#: ⚠️ **不得写死一个数**（§5.3.0 规则 2 / U-107 附注①）：U-67 后 P0 生效路由恒 flash（15s），
#: 但 pro 档一旦启用，`hard_timeout_s(resolve_route(task).model_key)` 会自动跟上 45s。
#: ⚠️ 合并档（`normalize` 实际走 `understand()` = `normalize_intent`）与 L3+ 复杂档
#: （`gen_sql_complex`）在此按**基 task** 解析：当前两档都路由 `ModelKey.FAST`，值相同；
#: 若将来某档被裁成 pro，须在 `_client_timeout_for` 按 `deps.merged_understand`/复杂度再分流。
_LLM_NODE_TASKS: Final[dict[str, str]] = {
    "normalize": "normalize",
    "intent": "intent",
    "plan": "plan",
    "gen_sql": "gen_sql",
    "present": "present",
    "repair": "repair",
    "bind": "l4_score",
}

#: 合并档分配平移（§5.3.0 规则 5 / U-107 附注③）：合并档下 `normalize` 一次调用干
#: 节点 2+3 的活（`understand()`），其**分配** = normalize 的 2.0 + intent 的 1.5 = 3.5s。
#:
#: ⚠️ **这里是"分配（budget）"，不是"硬超时（hard timeout）"**：3.5s 保留，供 §16.1 预算 /
#: §16.2 SSE 占位符判定 / `over_budget` 标记，**不再叠加进 `asyncio.timeout`**。
#: LLM 节点的硬超时统一走 `_client_timeout_for`（§10.2 客户端超时），"上游慢"从此走
#: 降级链而不是 re-raise 成 `error(INTERNAL)`—— 这才是 w7 🔴-0 的正解。
#: ⚠️ `2.0`/`1.5` 是旧 `NODE_TIMEOUT_S` 行值（那时是"预算当硬超时"的病害数字）沿用为分配口径，
#: 与 §16.1 路由表 `budget_s`（normalize_intent=1.2）是两条不同口径的预算，已在 RELAY 登记该分歧。
_MERGED_NORMALIZE_EXTRA_S: Final[float] = 1.5


def _client_timeout_for(task: str) -> float:
    """`task` → 客户端超时（`resolve_route(task).model_key` → `hard_timeout_s`，§10.2）。

    flash 15s / pro 45s；刻意不写死 —— pro 档启用自动跟进（U-107 附注①）。
    """
    from app.llm.router import hard_timeout_s, resolve_route

    return hard_timeout_s(resolve_route(task).model_key)


def _effective_limit_for(name: str, override: float | None) -> float:
    """执行期生效硬超时（`override` 仅供测试放大/缩小，生产为 `None`）。

    LLM 节点 → 客户端超时（`resolve_route` → `hard_timeout_s`，§10.2）；非 LLM 节点 → 表值。
    刻意在执行期判而不是包装期：图是编译期单例，而客户端超时依赖路由表（`resolve_route`）
    与 §10.2 档位 —— 包装期无法保证拿到 pro/flash 的最终档（U-107 附注①：不得写死一个数）。
    """
    if override is not None:
        return override
    task = _LLM_NODE_TASKS.get(name)
    if task is not None:
        return _client_timeout_for(task)
    return NODE_TIMEOUT_S[name]


#: 超时后**保持 re-raise** 的节点（fail-closed / 终态构造责任）。
#:
#: ⚠️ 这三个节点的超时**没有** §5.3 的"失败转移"出路（§5.3.0 附注②）：
#: · `mask` / `audit_pre`：fail-closed —— 没跑完就代表"脱敏/段 1 审计未完成"，吞掉等于
#:   放行一条未脱敏的数据 / 一次缺审计的下发（N-05 / 段 1 是安全前提）；
#: · `audit_supp`：它**兼发** `complete` 终态 —— 超时时连终态都没构造出来，吞掉 = 流无终态
#:   （违反 N-08）。W4 具名裁决：保留 re-raise，即使表里它"失败不阻断"（那个"不阻断"说的是
#:   段 2 **写库失败**，不是"终态没构造"）。
#: 三者超时 → 上抛 → `runner._drive` 兜底 `error(INTERNAL)`（N-08 不留无终态的流）。
_RERAISE_TIMEOUT_NODES: Final[frozenset[str]] = frozenset({"mask", "audit_pre", "audit_supp"})


def _timeout_fallback(name: str, state: GraphState, effective: float) -> dict[str, Any]:
    """逐节点超时出路表（§5.3.0 规则 2 / U-107 附注②）：**复用 §5.3 的失败转移列**。

    ⚠️ 只覆盖「文档给了出路的节点」（LLM 节点 → 降级链 / 闸门 → GATE_* 码或跳过并标注 /
    execute → EXEC_TIMEOUT）。`_RERAISE_TIMEOUT_NODES` 不在本表 —— 由 `_with_node_timeout`
    上抛（见该常量 docstring）。

    ⚠️ 每次转移都**镜像该节点自身处理同源失败的分支**（`normalize.py` 的 `PlannerError`
    → `report_degraded(LLM_UNAVAILABLE, TEMPLATE_ONLY)` + refuse；……），让"运行中超时"
    与"节点内失败"两条路径产出**同形**的终态 —— 上游一慢从此走降级链，而不是 re-raise
    成 `error(INTERNAL)` → `ok=0`（这是 w7 🔴-0 的正解）。
    """
    from app.core.enums import (
        ActionTaken,
        DegradedReason,
        ErrorCode,
        GateNo,
        Outcome,
        RefuseReason,
    )
    from app.graph.context import current_run_context_or_none
    from app.graph.nodes._shared import gate_update, terminal_update
    from app.planner.schemas import IntentKind

    context = current_run_context_or_none()

    def _degraded(reason: DegradedReason, action: ActionTaken) -> None:
        if context is not None:
            context.report_degraded(
                reason, action, {"stage": name, "reason": "timeout", "limit_s": effective}
            )

    if name == "normalize":
        # 镜像 `normalize.py` 的 `PlannerError` 分支（§5.3 行 2：模板 → 无命中 → 拒答）。
        _degraded(DegradedReason.LLM_UNAVAILABLE, ActionTaken.TEMPLATE_ONLY)
        update: dict[str, Any] = {
            "intent": IntentKind.REFUSE.value,
            "intent_detail": {
                "reason_code": "understand_unavailable",
                "refuse_kind": RefuseReason.NO_DATA_ASSET.value,
            },
        }
        update.update(
            terminal_update(
                state, event="refuse", outcome=Outcome.REFUSE,
                reason=RefuseReason.NO_DATA_ASSET.value,
            )
        )
        return update

    if name == "intent":
        # 镜像 `intent.py` 的 `PlannerError` 分支（§5.3 行 3）：单跑路径**不** report_degraded。
        update = {
            "intent": IntentKind.REFUSE.value,
            "intent_detail": {
                "reason_code": "intent_unavailable",
                "refuse_kind": RefuseReason.NO_DATA_ASSET.value,
            },
        }
        update.update(
            terminal_update(
                state, event="refuse", outcome=Outcome.REFUSE,
                reason=RefuseReason.NO_DATA_ASSET.value,
            )
        )
        return update

    if name == "plan":
        # 镜像 `plan.py` 的 `PlannerError` 分支（§5.3 行 5）。
        _degraded(DegradedReason.PLAN_GENERATION_FAILED, ActionTaken.TEMPLATE_ONLY)
        return terminal_update(
            state, event="refuse", outcome=Outcome.REFUSE,
            reason=RefuseReason.NO_DATA_ASSET.value,
        )

    if name in ("gen_sql", "repair"):
        # 镜像 `gen_sql.py` / `repair.py` 的 `PlannerError` 分支（§5.3 行 7 / 16）。
        _degraded(DegradedReason.LLM_UNAVAILABLE, ActionTaken.TEMPLATE_ONLY)
        return terminal_update(
            state, event="refuse", outcome=Outcome.REFUSE,
            reason=RefuseReason.NO_DATA_ASSET.value,
        )

    if name == "present":
        # 镜像 `present.py`（§14.2 F4）：degraded + 空增量 = 仅表格。
        _degraded(DegradedReason.PRESENT_FAILED, ActionTaken.TABLE_ONLY)
        return {}

    if name == "link":
        # §5.3 行 4：检索超时 = 稠密不可用 → sparse_only；P0 稀疏也无命中 → 拒答。
        _degraded(DegradedReason.EMBEDDING_UNAVAILABLE, ActionTaken.SPARSE_ONLY)
        return terminal_update(
            state, event="refuse", outcome=Outcome.REFUSE,
            reason=RefuseReason.NO_DATA_ASSET.value,
        )

    if name == "bind":
        # W4 具名裁决（§5.3 行 6「无绑定 → refuse」）：绑定超时 = 无绑定产物 → 拒答。
        return terminal_update(
            state, event="refuse", outcome=Outcome.REFUSE,
            reason=RefuseReason.NO_DATA_ASSET.value,
        )

    if name == "gate1_ast":
        return terminal_update(
            state, event="error", outcome=Outcome.FAILED,
            code=ErrorCode.GATE_AST_REJECTED.value,
        )

    if name == "gate2_policy":
        return terminal_update(
            state, event="error", outcome=Outcome.FAILED,
            code=ErrorCode.GATE_POLICY_REJECTED.value,
        )

    if name == "gate3_cost":
        # §5.3.0 附注②「跳过并标注」：EXPLAIN 超时视同 explain_error → WARN（不设终态，
        # 不报告为通过，D5/D6 —— 与 `gate3_cost.py` 的 EXPLAIN 异常分支同形）。
        from app.guard import run_gate3

        result = run_gate3(str(state.get("sql_text") or ""), {"explain_error": True})
        return gate_update(state, GateNo.COST, result)

    if name == "execute":
        # §5.3 行 11：写 `exec_error(timeout)`、**不定终态**，交由 `route_after_execute` /
        # `error_out` 映射成 `EXEC_TIMEOUT` —— 与本节点 `_on_failure` 的"只写摘要、不定终态"
        # 分工一致（`timeout` 是不可修类，不进 repair）。
        from app.exec.errors import MESSAGES
        from app.obs.metrics import observe_exec_failure

        observe_exec_failure("timeout")
        return {
            "exec_error": {
                "error_class": "timeout",
                "pgcode": None,
                "message": MESSAGES["timeout"],
                "llm_hint": None,
            },
        }

    # 理论不可达：所有可计时节点（`_LLM_NODE_TASKS` ∪ `NODE_TIMEOUT_S`）都已在上表列出。
    raise RuntimeError(f"_timeout_fallback 未覆盖节点: {name}")


def _with_node_timeout(name: str, fn: Any, *, overrides: Mapping[str, float] | None = None) -> Any:
    """给节点套 `asyncio.timeout()`（HANDOFF §五-5：每节点超时 = asyncio.timeout 包装）。

    ⚠️ **包装判定**：「—」节点（`trusted_context` 与三个出口）不在任何表 → 返回**原函数对象**
    （给它们配超时 = 发明文档里没有的数值）。其余 15 节点（6 LLM + 9 固定）按下方出路表计时。

    ⚠️ **生效硬超时由 `_effective_limit_for` 执行期解析**（§5.3.0 规则 2 / U-107 附注①）：
    · LLM 节点 → `resolve_route(task).model_key` 的客户端超时（flash 15s / pro 45s，pro 档
      启用自动跟进），**不叠加** `_MERGED_NORMALIZE_EXTRA_S`（那是"分配"，归 §16.1 预算，
      见该常量 docstring）；
    · 非 LLM 节点 → `NODE_TIMEOUT_S` 表值。

    ⚠️ **超时出路表**（§5.3.0 规则 2 / U-107 附注②，逐节点复用 §5.3 失败转移列）：

    | 节点 | 超时动作 |
    |---|---|
    | normalize / plan / gen_sql / repair | `degraded(lm_unavailable / plan_generation_failed, template_only)` + `refuse(no_data_asset)` |
    | intent | `refuse(no_data_asset)`（不发 degraded，镜像节点自身） |
    | link | `degraded(embedding_unavailable, sparse_only)` + `refuse(no_data_asset)` |
    | bind | `refuse(no_data_asset)`（W4 具名裁决：无绑定 → refuse） |
    | present | `degraded(present_failed, table_only)` + 空增量（仅表格） |
    | gate1_ast / gate2_policy | `error(GATE_AST_REJECTED / GATE_POLICY_REJECTED)` |
    | gate3_cost | `run_gate3(explain_error=True)` → WARN + `gate_update`（跳过并标注，不设终态） |
    | execute | 写 `exec_error(timeout)` → `route_after_execute`/`error_out` 映射 `EXEC_TIMEOUT` |
    | mask / audit_pre / audit_supp | **re-raise**（`_RERAISE_TIMEOUT_NODES`，fail-closed / 终态构造） |

    ⚠️ `overrides` 仅供**测试**放大/缩小超时（0.1s 的闸门节点在慢 CI 上会假阳性）；
    生产装配不传 —— 契约值只能有一份来源。
    """
    if name not in _LLM_NODE_TASKS and name not in NODE_TIMEOUT_S:
        return fn

    override = (overrides or {}).get(name)

    from app.obs.logging import get_logger as _get_logger

    timeout_log = _get_logger(__name__)

    @functools.wraps(fn)
    async def _timed(state: GraphState) -> dict[str, Any]:
        effective = _effective_limit_for(name, override)
        try:
            async with asyncio.timeout(effective):
                return cast("dict[str, Any]", await fn(state))
        except TimeoutError:
            if name in _RERAISE_TIMEOUT_NODES:
                timeout_log.error(
                    "node_timeout",
                    node=name,
                    limit_s=effective,
                    extra_fact="fail-closed / 终态构造节点超时未收口 → 上抛，由 runner 兜底 error(INTERNAL)（N-08）",
                )
                raise
            timeout_log.error(
                "node_timeout_degraded",
                node=name,
                limit_s=effective,
                extra_fact="节点超时 → 走 §5.3 失败转移列（§5.3.0 规则 2 / U-107 附注②）",
            )
            return _timeout_fallback(name, state, effective)

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
        PLAN, *branch(edges.route_after_plan, REFUSE_OUT, BIND)
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
