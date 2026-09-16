"""T-A1 —— 20 并发压测确认 **checkpoint 池行为**（docs/08 §3.3 DoD③）。

归属窗口：W1B。运行方式：

    cd backend
    DATABASE_URL="postgresql+psycopg://app_rw:app_rw_pwd@localhost:5432/ecom" \\
    ANALYTICS_DB_URL="postgresql+psycopg://app_ro:app_ro_pwd@localhost:5432/ecom" \\
    ../.venv/Scripts/python.exe scripts/probe_checkpoint_pool.py --out reports/t-a1

--------------------------------------------------------------------------
一、它要回答的问题（以及为什么不能推导）
--------------------------------------------------------------------------
07 §16.3 给 checkpoint 池写的判据是「⚠️ **不确定** —— 取决于 LangGraph 实现是
"每节点写完即还"还是"整个 run 长持"，**需实测**」。这两种情形对应的架构完全不同：

| 结论 | 50 并发下的连接需求 | 后续动作 |
|---|---|---|
| **短持** | ≈ 2–5 条，`pool_size=10` 够 | 只需补"锁串行化的延迟预算" |
| **长持** | **50 条**长持客户端连接 | 任何池都不够 → 必须改装配，或上 pgbouncer（且 pgbouncer 只挡**物理**连接，**逻辑**连接照样占满） |

⚠️ **读源码得到的三个事实**（`langgraph/checkpoint/postgres/aio.py`，本机实装
`langgraph-checkpoint-postgres 3.1.2`），它们决定了本探针**必须分四个装配臂**而不是两个：

1. `_cursor()` 的实际实现是 `async with self.lock, _ainternal.get_connection(self.conn) as conn`
   → **短持/长持由构造入参决定**：入参是 `AsyncConnectionPool` → 每次操作**借还**；
   入参是单条 `AsyncConnection` → 直接 `yield`，**整个 saver 生命周期长持**。
2. `self.lock = asyncio.Lock()` → **每个 saver 实例一把锁，串行化它自己的全部检查点 I/O**。
   → 单 saver 的检查点吞吐上限 = 同时刻 1 个操作。**§16.3 从没算过这笔账**，
   而且它与池大小无关：池再大，"等待"发生在锁上，不发生在池上。
3. `self.loop = get_running_loop()` → saver **绑定创建它的 loop**（因此"模块级全局 saver"
   这种写法在多 loop 场景下会炸）。

→ 于是"短持/长持"这个二选一**漏掉了第三种**，真正的分叉是：
①单例 saver（串行、连接 ≤1）②per-run saver（并发、每 saver 一条长持）
③**per-run saver + 共享 pool**（§16.3 未考虑，可能是最优）。

--------------------------------------------------------------------------
二、四路观测（互证，缺一路都不够）
--------------------------------------------------------------------------
| 通道 | 取什么 | 为什么不能省 |
|---|---|---|
| `pool.get_stats()` | `in_use = pool_size − pool_available`（**当前借出数**） | 这是"持有"的**定义级**指标。但它只在有池时有值 → 臂 B/C 无此通道，必须靠 pg |
| `pg_stat_activity` | 按 `application_name` 分后端数与 `state` | 池侧看不到"逻辑连接 vs 物理连接"的差别；且 `application_name` 是 T-A1 唯一能把连接归因到池的锚点 |
| 操作级计时 | `aget_tuple` / `aput` / `aput_writes` 的**排队 + 执行**时长 | 只有它能把"等待"归因到**锁**还是**池**（两者的修法完全不同） |
| 单 run wall time | 纯延迟底座 | 没有它，"连接数高"可能只是"跑得久"，而不是"持有语义" |

⚠️ **判据（先写死，避免事后挑数据）**：
· **短持** → `in_use` 只在节点边界成**尖峰**、节点间回落 0；`requests_waiting` 恒 0。
· **长持** → `in_use` **整 run 恒 ≈ N**。
· **锁串行** → `in_use` 不高（≤1/实例）但 wall time 随 N **线性上升**，且操作计时里
  "等待"占绝大部分。**这一种最容易被误读成"短持且健康"** —— 所以必须有操作级计时。

--------------------------------------------------------------------------
三、诚实边界（必须与结论一起读，否则结论会被放大）
--------------------------------------------------------------------------
1. 这是 **T-A1 探针实验，不是 07 §16.5 的四场景压测**（那归 W7，需合成数据集全量）。
2. 用进程内 `asyncio.gather` 造并发，**不引 k6/locust** —— 测的是"服务端连接持有时长"，
   不是端到端 HTTP 容量（§16.5 的工具要求针对后者）。
3. 桩节点**不含真实 SQL** → `analytics` / `metadata` 池不参与，**本轮只对 checkpoint 池给结论**。
4. `pgbouncer` 未起 → §16.3 的 "80 逻辑 → 30 物理" 那半**未验**；本轮只验应用侧算术。
5. 结论**绑定版本**：`langgraph 1.2.11` / `langgraph-checkpoint-postgres 3.1.2`。
   这两个依赖在 `pyproject.toml` 里是**开放区间**（用户已裁定钉精确版本，落笔归 W0）；
   在钉死之前，换机重装即可能让本结论作废 —— **这是本报告最脆的一环**。
6. 单机单 PG，无网络抖动注入。真实环境里"长持"的代价还包括 NAT/防火墙的空闲断连。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
import sys
import time
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final

# 允许 `python scripts/probe_checkpoint_pool.py` 直接跑（免安装导入 app.*）
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import psycopg  # noqa: E402
from langgraph.checkpoint.base import empty_checkpoint  # noqa: E402

from app.core.config import Settings, get_settings  # noqa: E402
from app.graph.build import (  # noqa: E402
    PER_RUN_STRATEGIES,
    STUB_RECURSION_LIMIT,
    CheckpointStrategy,
    build_stub_graph,
    make_checkpointer,
)
from app.graph.state import initial_state  # noqa: E402
from app.repo.pools import (  # noqa: E402
    CHECKPOINT_APPLICATION_NAME,
    POOL_SPECS,
    PoolKind,
    build_checkpoint_pool,
)

#: 07 §5.5 的 `thread_id` 组成：`{tenant_id}:{user_id}:{session_id}`。
TENANT_ID = "t_001"
USER_ID = "u_001"

#: T-A1 用的节点耗时。**必须 > 采样周期**，否则整 run 只有 1–2 个采样点。
#: 0.25s × 3 节点 ≈ 0.8s/run，采样周期 0.05s → ≈ 16 个采样点。
DEFAULT_NODE_DELAY_S = 0.25
DEFAULT_SAMPLE_INTERVAL_S = 0.05

#: DoD③ 的判据并发度 = 20；50 用于验 §16.3 的风险阈值。
DEFAULT_CONCURRENCY = (1, 5, 20, 50)

#: 07 §5.2.1 的三档检查点体积（1KB / 16KB / 64KB）。64KB 是**上限**，
#: 当前它的依据是"拍的"，本探针给一个实测支撑。
CHECKPOINT_SIZE_TIERS = (1 * 1024, 16 * 1024, 64 * 1024)


# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class Sample:
    """一次采样（池侧 + pg 侧同一时刻）。"""

    t_ms: float
    pooled_in_use: int | None
    pooled_size: int | None
    pooled_available: int | None
    requests_waiting: int | None
    pg_backends: int
    pg_active: int
    pg_idle: int
    pg_idle_in_tx: int


@dataclass
class OpTiming:
    """操作级计时。

    ⚠️ **只记总时长，不谎称能拆出"等待"与"执行"**。
    排队（`asyncio.Lock` + 池借还）发生在被调方法的**内部**，从外面切不开。
    第一版我曾留一个恒为 0 的 `wait_ms` 字段 —— 那是个**假指标**：
    它在报告里会读成"没有等待"，而真相是"没测"。

    正确的用法是**跨并发度对比**：同一个操作在 N=1 与 N=50 下的时长之比，
    就是排队代价的度量（锁串行会让它随 N 线性上升）。
    """

    op: str
    duration_ms: float


@dataclass
class CaseResult:
    strategy: str
    concurrency: int
    node_delay_s: float
    sample_interval_s: float
    wall_ms: float
    run_wall_ms: list[float]
    samples: list[Sample] = field(default_factory=list)
    ops: list[OpTiming] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    # --- 派生指标（全部由原始数据算，不在采集时算）---
    @property
    def pooled_in_use_max(self) -> int | None:
        values = [s.pooled_in_use for s in self.samples if s.pooled_in_use is not None]
        return max(values) if values else None

    @property
    def pooled_in_use_median(self) -> float | None:
        values = [s.pooled_in_use for s in self.samples if s.pooled_in_use is not None]
        return statistics.median(values) if values else None

    @property
    def pg_backends_max(self) -> int:
        return max((s.pg_backends for s in self.samples), default=0)

    @property
    def pg_backends_median(self) -> float | None:
        """pg 后端数的中位数（**比 `max` 更能回答"是否持续存在"**）。

        ⚠️ 与 `in_use` 同样是"max 会被冷启动污染"的问题：
        只看 `max` 会把"刚开始建 5 条连接"读成"整个 run 持有 5 条"。
        """
        values = [s.pg_backends for s in self.samples]
        return statistics.median(values) if values else None

    @property
    def pool_max(self) -> int | None:
        """采样到的池上限（用于识别"池被打满"）。"""
        for sample in self.samples:
            if sample.pooled_size is not None:
                return sample.pooled_size
        return None

    @property
    def pg_active_max(self) -> int:
        return max((s.pg_active for s in self.samples), default=0)

    @property
    def pg_idle_in_tx_max(self) -> int:
        return max((s.pg_idle_in_tx for s in self.samples), default=0)

    @property
    def requests_waiting_max(self) -> int | None:
        values = [s.requests_waiting for s in self.samples if s.requests_waiting is not None]
        return max(values) if values else None

    @property
    def pooled_in_use_p95(self) -> float | None:
        values = sorted(s.pooled_in_use for s in self.samples if s.pooled_in_use is not None)
        if not values:
            return None
        idx = min(len(values) - 1, round(0.95 * (len(values) - 1)))
        return float(values[idx])

    @property
    def in_use_nonzero_ratio(self) -> float | None:
        """有池句柄时："借出数 > 0" 的采样点占比。

        ⚠️ 它是"短持"的**正向证据**：若持有贯穿整 run，这个比例会接近 1；
        短持下它很小（操作是毫秒级，采样很容易错过尖峰）。
        ⚠️ 但**比例小 ≠ 没持有** —— 只有"窗口足够长 + 采样足够密"时，比例小才有意义。
        所以本报告必须同时给出 `sample_count` 与 `sample_interval_s`。
        """
        values = [s.pooled_in_use for s in self.samples if s.pooled_in_use is not None]
        if not values:
            return None
        return sum(1 for v in values if v > 0) / len(values)

    @property
    def op_duration_p95_ms(self) -> float | None:
        durations = sorted(op.duration_ms for op in self.ops)
        if not durations:
            return None
        idx = min(len(durations) - 1, round(0.95 * (len(durations) - 1)))
        return durations[idx]

    @property
    def op_duration_median_ms(self) -> float | None:
        durations = [op.duration_ms for op in self.ops]
        return statistics.median(durations) if durations else None


# ============================================================================
# 桩状态与配置
# ============================================================================


def _state_for(index: int) -> dict[str, Any]:
    """一个 run 的初始状态。

    ⚠️ 用 `initial_state()`（`graph/state.py`）而不是手写 dict：
    手写就等于把"组 1 有哪些字段"写了两遍（G-2 / U-24 的对应措施）。
    """
    from datetime import UTC, datetime

    from app.core.contracts import IdentityContext
    from app.core.enums import Role

    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    identity = IdentityContext(
        trace_id=f"tr_ta1_{now}_{index}",
        task_id=f"tk_ta1_{index}",
        session_id=f"s_{index}",
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        role=Role.OPERATOR,
    )
    return dict(initial_state(identity, raw_question="T-A1 探针：桩问题"))


def _config(index: int) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": f"{TENANT_ID}:{USER_ID}:s_{index}"},
        "recursion_limit": STUB_RECURSION_LIMIT,
    }


# ============================================================================
# 操作级计时：把 saver 的三个方法包一层
# ============================================================================


def instrument_saver(saver: Any, sink: list[OpTiming]) -> None:
    """给 saver 的 `aget_tuple` / `aput` / `aput_writes` 加计时包装（实例级，不改类）。

    ⚠️ **幂等**：重复包装会让同一次调用被计两次 → 等待时长翻倍，看起来像"锁很慢"。
    用一个私有标记位挡住。
    ⚠️ 用实例属性覆写而不是子类：`build.py` 造的是官方 `AsyncPostgresSaver`，
    子类化会让"探针测的类"与"生产用的类"不是同一个（本探针最忌讳的偏差形态）。
    """
    if getattr(saver, "_ta1_instrumented", False):
        return
    saver._ta1_instrumented = True

    for name in ("aget_tuple", "aput", "aput_writes"):
        original = getattr(saver, name)

        def _wrap(orig: Any = original, op_name: str = name) -> Any:
            async def _timed(*args: Any, **kwargs: Any) -> Any:
                started = time.perf_counter()
                try:
                    return await orig(*args, **kwargs)
                finally:
                    sink.append(
                        OpTiming(op=op_name, duration_ms=(time.perf_counter() - started) * 1000.0)
                    )

            return _timed

        setattr(saver, name, _wrap())


# ============================================================================
# 采样器
# ============================================================================


class Sampler:
    """池侧 + pg 侧同步采样。"""

    def __init__(
        self,
        *,
        pool: Any | None,
        observer: psycopg.AsyncConnection[Any],
        interval_s: float,
        sink: list[Sample],
        t0: float,
    ) -> None:
        self._pool = pool
        self._observer = observer
        self._interval = interval_s
        self._sink = sink
        self._t0 = t0
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task

    async def _loop(self) -> None:
        while not self._stop.is_set():
            await self._sample_once()
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
        # 收尾再采一次：避免"最后一个尖峰刚好落在窗口外"
        await self._sample_once()

    async def _sample_once(self) -> None:
        t_ms = (time.perf_counter() - self._t0) * 1000.0
        pooled: dict[str, int | None] = {
            "pooled_in_use": None,
            "pooled_size": None,
            "pooled_available": None,
            "requests_waiting": None,
        }
        if self._pool is not None:
            stats = self._pool.get_stats()
            size = stats.get("pool_size")
            available = stats.get("pool_available")
            pooled = {
                "pooled_in_use": (size - available) if (size is not None and available is not None) else None,
                "pooled_size": size,
                "pooled_available": available,
                "requests_waiting": stats.get("requests_waiting"),
            }

        # ⚠️ psycopg 的异步路径需要**两次 await**：`execute()` 返回游标（可 await），
        # `fetchone()` 本身也是协程。少一个 await 不会报错在明显的地方 ——
        # 它会返回协程对象，然后在 `row[0]` 上炸出"不可下标"，误导性极强。
        cursor = await self._observer.execute(
            """
            SELECT count(*)                                                  AS backends,
                   count(*) FILTER (WHERE state = 'active')                  AS active,
                   count(*) FILTER (WHERE state = 'idle')                    AS idle,
                   count(*) FILTER (WHERE state = 'idle in transaction')     AS idle_in_tx
              FROM pg_stat_activity
             WHERE datname = current_database()
               AND application_name = %s
            """,
            (CHECKPOINT_APPLICATION_NAME,),
        )
        row = await cursor.fetchone()
        if row is None:  # pragma: no cover - 聚合查询必有一行，兜底只为类型收窄
            return

        self._sink.append(
            Sample(
                t_ms=round(t_ms, 2),
                pg_backends=int(row[0]),
                pg_active=int(row[1]),
                pg_idle=int(row[2]),
                pg_idle_in_tx=int(row[3]),
                **pooled,
            )
        )


# ============================================================================
# 单个测试臂 × 并发度
# ============================================================================


async def _warmup_pool(pool: Any, *, target: int) -> None:
    """把池预热到 `target` 条连接 —— **消除"连接建立风暴"对采样的污染**。

    ⚠️⚠️ 这是本探针**第三次**修正自己的测量口径，也是前两次误判的共同根因：

    `in_use = pool_size − pool_available` 在本定义下是"借出数"，但**冷启动时连接正在建立**，
    它们还没进池的可用列表 → 被算作"借出"。于是：

    | 观测 | 第一版结论（错） | 真相 |
    |---|---|---|
    | `per_run_shared_pool` N=5：`in_use` 在 0–97ms 从 1 升到 5 | `LONG_HELD_WHOLE_RUN` | 那 97ms 是**建连接** |
    | `per_run_shared_pool` N=50：`in_use` 在 0–898ms 顶在 20、`waiting` 峰值 45 | `LONG_HELD_POOL_EXHAUSTED` | 那是 50 个 run 同时申请连接、池被迫一次性开到 20 条 |
    | 之后（898ms–1115ms） | 未看 | `in_use=0, avail=20` —— **连接全回池了** |

    三次都栽在同一个地方：**把"连接建立/排队"读成"持有"**。而两者的时间尺度不同 ——
    建立是**一次性**的（几十到几百 ms），持有是**贯穿 run**的（这里是 750ms+）。
    因此只要把建立过程**提前做掉**，"持有"就无处可藏。

    ⚠️ 预热必须**到 `max_size`**（不是 `min_size`）：不把池撑满，run 期间仍会新建连接，
    污染照旧 —— 这正是前一版只设 `min_size=1` 却开了 20 条的原因。
    ⚠️ 本函数**不改变被测行为**：预热只是提前建立连接，之后这些连接的行为与
    "运行中建立"完全一样（都是 `search_path=lg`、同一 `application_name`、同一池）。
    它的代价是**测不到连接建立本身的耗时** —— 而那属于 §16.5 的容量压测，不是 T-A1 的问题。
    """

    async def _hold() -> None:
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")

    await asyncio.gather(*(_hold() for _ in range(target)))
    # 等到连接真的归还（`connection()` 退出是异步归还）
    for _ in range(100):
        stats = pool.get_stats()
        if stats.get("pool_available") == stats.get("pool_size"):
            return
        await asyncio.sleep(0.01)


async def run_case(
    strategy: CheckpointStrategy,
    concurrency: int,
    *,
    settings: Settings,
    node_delay_s: float,
    sample_interval_s: float,
    superuser_dsn: str,
) -> CaseResult:
    result = CaseResult(
        strategy=strategy.value,
        concurrency=concurrency,
        node_delay_s=node_delay_s,
        sample_interval_s=sample_interval_s,
        wall_ms=0.0,
        run_wall_ms=[],
    )

    shared_pool = None
    shared_graph = None
    per_run_resources: list[Any] = []

    if strategy in PER_RUN_STRATEGIES:
        if strategy is CheckpointStrategy.PER_RUN_SHARED_POOL:
            shared_pool = build_checkpoint_pool(settings)
            await shared_pool.open()
            # ⚠️ 预热到 max_size —— 见 `_warmup_pool` 的说明（这一步决定结论真假）
            await _warmup_pool(shared_pool, target=POOL_SPECS[PoolKind.CHECKPOINT].max_size)
    else:
        # ⚠️ 臂 A 的池必须在这里**显式**建，不能让它躲在 `make_checkpointer` 内部：
        # 池是**被观测对象**，采样器必须持有它的句柄。第一版漏了这一点，
        # 采样器拿到 `pool=None`，于是 `in_use` 全空、结论退化成"没数据"。
        if strategy is CheckpointStrategy.SINGLE_SAVER_SHARED_POOL:
            shared_pool = build_checkpoint_pool(settings)
            await shared_pool.open()
            await _warmup_pool(shared_pool, target=POOL_SPECS[PoolKind.CHECKPOINT].max_size)
            shared_saver = await make_checkpointer(strategy, settings, pool=shared_pool, setup=True)
        else:
            shared_saver = await make_checkpointer(strategy, settings, setup=True)
        # ⚠️ 顺序不能反：**先装配 saver → 再包计时 → 最后编译图**。
        # 若先编译图再包 saver，LangGraph 已经抓走了未包装的方法引用，
        # 于是单例臂（A/B）会**一条操作计时都没有** —— 而"没有数据"很容易
        # 被读成"这个臂没有等待"，正是最危险的那种假绿灯。
        instrument_saver(shared_saver, result.ops)
        shared_graph = build_stub_graph(shared_saver, node_delay_s=node_delay_s)

    async def graph_for(index: int) -> Any:
        """取本次 run 用的图。单例策略复用，per-run 策略现造。"""
        if shared_graph is not None:
            return shared_graph
        if strategy is CheckpointStrategy.PER_RUN_SHARED_POOL:
            saver = await make_checkpointer(strategy, settings, pool=shared_pool, setup=False)
        else:
            saver = await make_checkpointer(strategy, settings, setup=False)
            per_run_resources.append(saver)
        instrument_saver(saver, result.ops)
        return build_stub_graph(saver, node_delay_s=node_delay_s)

    async def one_run(index: int) -> float:
        graph = await graph_for(index)
        started = time.perf_counter()
        await graph.ainvoke(_state_for(index), _config(index))
        return (time.perf_counter() - started) * 1000.0

    observer = await psycopg.AsyncConnection.connect(superuser_dsn, autocommit=True)
    t0 = time.perf_counter()
    sampler = Sampler(
        pool=shared_pool, observer=observer, interval_s=sample_interval_s, sink=result.samples, t0=t0
    )
    sampler.start()
    try:
        result.run_wall_ms = list(await asyncio.gather(*(one_run(i) for i in range(concurrency))))
    except Exception as exc:  # 诚实记录失败，不吞
        result.errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        result.wall_ms = (time.perf_counter() - t0) * 1000.0
        await sampler.stop()
        await observer.close()
        for saver in per_run_resources:
            conn = getattr(saver, "conn", None)
            if conn is not None and hasattr(conn, "close"):
                try:
                    await conn.close()
                except Exception as exc:
                    result.errors.append(f"close: {type(exc).__name__}: {exc}")
        if shared_pool is not None:
            await shared_pool.close()
        # ⚠️ 停机沉降：`close()` 返回时服务端后端**未必**已经消失，
        # 残留会在**下一个测试臂**的第一次采样里被数进去 ——
        # 实测到的症状是"臂 B（单连接）的 `pg_backends` 却显示 2"。
        # 这类跨用例污染会让相邻两臂的结论互相矛盾，而排查方向会被引到"谁多开了一条"。
        await asyncio.sleep(0.3)

    return result


# ============================================================================
# 附带：检查点体积 → 写入耗时（给 §5.2.1 的 64KB 上限一个实测支撑）
# ============================================================================


async def run_size_tiers(
    settings: Settings, *, tiers: tuple[int, ...] = CHECKPOINT_SIZE_TIERS
) -> list[dict[str, Any]]:
    """测 1KB / 16KB / 64KB 三档 `aput` 的耗时。

    ⚠️ **这不是 §16.3 的一部分**，它是 §5.2.1「单次检查点 ≤64KB 由 CI 断言」的支撑数据：
    该上限当前是**拍的**，需要一个"64KB 到底花多少时间"的量级感。
    ⚠️ 只测 `aput`（写入），不测 `aget_tuple`：后者是读，与上限无关。
    """
    from langgraph.checkpoint.base import ChannelVersions, CheckpointMetadata

    out: list[dict[str, Any]] = []
    saver = await make_checkpointer(CheckpointStrategy.SINGLE_SAVER_SHARED_POOL, settings, setup=True)
    try:
        for size in tiers:
            checkpoint = empty_checkpoint()
            # 用一个中性键承载"体积"：不写任何业务字段名，
            # 避免这个探针数据被误当成"某个真实字段有多大"。
            checkpoint["channel_values"]["_ta1_padding"] = "x" * max(0, size - 512)
            metadata: CheckpointMetadata = {
                "source": "input",
                "step": 0,
                "parents": {},
            }
            config = {"configurable": {"thread_id": f"ta1_size_{size}", "checkpoint_ns": ""}}
            versions: ChannelVersions = {}
            started = time.perf_counter()
            try:
                await saver.aput(config, checkpoint, metadata, versions)  # type: ignore[arg-type]
                elapsed = (time.perf_counter() - started) * 1000.0
                out.append({"bytes": size, "aput_ms": round(elapsed, 3), "ok": True})
            except Exception as exc:
                out.append({"bytes": size, "aput_ms": None, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        conn = getattr(saver, "conn", None)
        if conn is not None and hasattr(conn, "close"):
            await conn.close()
    return out


# ============================================================================
# 输出
# ============================================================================


def _verdict(case: CaseResult, baseline_wall_ms: float | None) -> tuple[str, float | None]:
    """把原始指标翻成结论。**判据在这里写死**（文件头也抄了一份），只做投影。

    返回 `(结论, 相对 N=1 的 wall time 缩放倍数)`。

    ⚠️⚠️ **一律用"中位数 + 持续占比"，不用 `max`**。
    这是本探针最贵的一次自我修正：第一版用 `in_use_max >= 0.6·N` 判长持，于是
    `per_run_shared_pool N=5` 被误判为 `LONG_HELD_WHOLE_RUN` —— 而原始时间序列显示
    `in_use` 只在**前 97ms 的连接建立阶段**从 1 升到 5，之后整段都是 0。
    `max` 把"冷启动建连接"读成了"整 run 持有"，**结论与真相完全相反**。
    （诊断依据：同期 `pool_available` 在 97ms 之后恒等于 `pool_size` ——
    连接确实回到了池里。这比任何间接推断都硬。）

    | 指标 | 强度 | 说明 |
    |---|---|---|
    | `in_use_median` 持续高 + `pool_available ≈ 0` | **强（长持）** | 池侧"借出数"是定义级指标 |
    | `in_use_median ≈ 0` 且 `pool_available ≈ pool_size` | **强（短持）** | 连接**确实**回到了池里 |
    | `pg_backends_median ≈ N` 且**无池** | **强（N 条并存）** | 单连接臂的构造决定它们只能长持 |
    | wall time 缩放 ≈ 1 | **强（无串行瓶颈）** | 并发真的并发 |
    | wall time 缩放 ≈ N | **强（串行）** | 无论连接数多少，这是用户可感知的那一半 |
    | `in_use_max` | **弱，仅参考** | 会被冷启动污染，**不得用于判定** |
    """
    if case.errors:
        return "ERROR", None

    scaling = (case.wall_ms / baseline_wall_ms) if baseline_wall_ms else None

    if case.concurrency == 1:
        # 单并发下"短持"与"长持"的观测值**完全一样**（都只会看到 ≤1 条），
        # 故此处**不给持有语义结论**，只作为缩放比的基线。
        return "BASELINE_ONLY", scaling

    in_use_median = case.pooled_in_use_median
    if in_use_median is not None:
        pool_max = case.pool_max
        if pool_max is not None and in_use_median >= 0.9 * pool_max:
            return "LONG_HELD_POOL_EXHAUSTED", scaling
        if in_use_median >= 0.6 * case.concurrency:
            return "LONG_HELD_WHOLE_RUN", scaling
        if scaling is not None and scaling >= 0.5 * case.concurrency:
            # 连接数不高但 wall time 按 N 增长 → 瓶颈在锁或池等待，而不是在连接数
            return "SERIALIZED_BY_SAVER_LOCK_OR_POOL_WAIT", scaling
        if case.pg_idle_in_tx_max > 0:
            return "IDLE_IN_TRANSACTION", scaling
        return "SHORT_HELD", scaling

    # 无池句柄（单连接臂）：构造上只能长持；用 pg 后端数的**中位数**确认"N 条并存"
    backends_median = case.pg_backends_median or 0
    if backends_median >= 0.6 * case.concurrency:
        return "N_CONNECTIONS_OPEN_THROUGHOUT", scaling
    if backends_median <= 1:
        return "SINGLE_CONN_SERIALIZED", scaling
    return "BACKENDS_PARTIAL", scaling


def write_outputs(results: list[CaseResult], sizes: list[dict[str, Any]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # 原始采样（长表，便于画图/复核）
    with (out_dir / "samples.csv").open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "strategy", "concurrency", *Sample.__dataclass_fields__.keys(),
            ],
        )
        writer.writeheader()
        for case in results:
            for sample in case.samples:
                writer.writerow({"strategy": case.strategy, "concurrency": case.concurrency, **asdict(sample)})

    with (out_dir / "op_timings.csv").open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=["strategy", "concurrency", "op", "duration_ms"])
        writer.writeheader()
        for case in results:
            for op in case.ops:
                writer.writerow({"strategy": case.strategy, "concurrency": case.concurrency, **asdict(op)})

    verdicts = verdicts_by_case(results)
    summary = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checkpoint_application_name": CHECKPOINT_APPLICATION_NAME,
        "cases": [
            {
                "strategy": c.strategy,
                "concurrency": c.concurrency,
                "node_delay_s": c.node_delay_s,
                "sample_interval_s": c.sample_interval_s,
                "wall_ms": round(c.wall_ms, 2),
                "run_wall_ms_median": round(statistics.median(c.run_wall_ms), 2) if c.run_wall_ms else None,
                "wall_scaling_vs_n1": verdicts[id(c)][1],
                "pooled_in_use_max": c.pooled_in_use_max,
                "pooled_in_use_p95": c.pooled_in_use_p95,
                "pooled_in_use_median": c.pooled_in_use_median,
                "pool_size": c.pool_max,
                "pg_backends_median": c.pg_backends_median,
                "in_use_nonzero_ratio": c.in_use_nonzero_ratio,
                "requests_waiting_max": c.requests_waiting_max,
                "pg_backends_max": c.pg_backends_max,
                "pg_active_max": c.pg_active_max,
                "pg_idle_in_tx_max": c.pg_idle_in_tx_max,
                "op_count": len(c.ops),
                "op_duration_median_ms": c.op_duration_median_ms,
                "op_duration_p95_ms": c.op_duration_p95_ms,
                "sample_count": len(c.samples),
                "runs_completed": len(c.run_wall_ms),
                "verdict": verdicts[id(c)][0],
                "errors": c.errors,
            }
            for c in results
        ],
        "checkpoint_size_tiers": sizes,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def verdicts_by_case(results: list[CaseResult]) -> dict[int, tuple[str, float | None]]:
    """先算出每个装配臂的 N=1 基线，再统一出结论。

    ⚠️ 结论**不能在采集时算**：`SHORT_HELD` 与 `SERIALIZED` 的分野靠"wall time 相对
    N=1 是否线性增长"，而那需要基线。第一版在采集时就算结论，于是"没有基线可比的臂"
    被硬判成串行 —— 一个纯粹由工具缺陷造出来的假结论。
    """
    baselines: dict[str, float] = {c.strategy: c.wall_ms for c in results if c.concurrency == 1}
    return {id(c): _verdict(c, baselines.get(c.strategy)) for c in results}


def print_table(results: list[CaseResult]) -> None:
    verdicts = verdicts_by_case(results)
    head = (
        f"{'strategy':<26}{'N':>4}{'wall_ms':>10}{'scale':>7}{'in_use_max':>12}"
        f"{'in_use_p95':>12}{'nz%':>7}{'pg_bk_max':>11}{'idle_tx':>9}  verdict"
    )
    print(head)
    print("-" * len(head))
    for c in results:
        verdict, scaling = verdicts[id(c)]
        print(
            f"{c.strategy:<26}{c.concurrency:>4}{c.wall_ms:>10.1f}"
            f"{(f'{scaling:.2f}' if scaling is not None else '-'):>7}"
            f"{(c.pooled_in_use_max if c.pooled_in_use_max is not None else -1):>12}"
            f"{(f'{c.pooled_in_use_p95:.0f}' if c.pooled_in_use_p95 is not None else '-'):>12}"
            f"{(f'{100 * c.in_use_nonzero_ratio:.0f}' if c.in_use_nonzero_ratio is not None else '-'):>7}"
            f"{c.pg_backends_max:>11}{c.pg_idle_in_tx_max:>9}  {verdict}"
        )
        for err in c.errors:
            print(f"    ! {err}")


# ============================================================================
# CLI
# ============================================================================


# ============================================================================
# ⚠️ Windows 事件循环：**本机跑异步 psycopg 的前置条件**（实测踩坑，见文件头"诚实边界"）
# ============================================================================
# 症状：`AsyncConnectionPool` 的每一次连接尝试都失败，30 秒后只报
#      `PoolTimeout: couldn't get a connection after 30.00 sec`。
#      排查方向会被引到"数据库没起来 / 密码错 / pgbouncer 挂了"。
# 真相：日志里才有一行 WARNING ——
#      `Psycopg cannot use the 'ProactorEventLoop' to run in async mode`。
# Windows 的**默认**事件循环是 `ProactorEventLoop`，而 **psycopg 3 的异步模式不支持它**。
# 更麻烦的是：本机 uvicorn 在 Windows 上**刻意**选 `ProactorEventLoop`
# （`uvicorn/loops/asyncio.py`：`if sys.platform == "win32" and not use_subprocess: return asyncio.ProactorEventLoop`）
#      → 即"本地起服务"这条路**默认就是坏的**，而容器里（Linux）完全正常。
# 因此：本地任何"异步 psycopg"入口都必须显式用 Selector 循环。
# ⚠️ 这条属"本机开发环境实测约束"，已登记转达（07 §3.4 / 附录 D 的同类条目）。


#: ⚠️ 用 `startswith` 而不是 `sys.platform == "win32"`：mypy 会对后者做**平台收窄**，
#: 于是在 Windows 上把 `return asyncio.run(coro)` 判成 unreachable
#: （`warn_unreachable = true` 会因此报错）。`startswith` 不在 mypy 的收窄范围里。
_IS_WINDOWS: Final[bool] = sys.platform.startswith("win")


def _run(coro: Any) -> Any:
    """`asyncio.run`，但在 Windows 上强制用 Selector 事件循环（见上方说明）。"""
    if _IS_WINDOWS:
        import selectors

        return asyncio.run(
            coro,
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    return asyncio.run(coro)


def _masked(dsn: str) -> str:
    """只打印 host/port/db，**绝不打印密码**（探针的输出会进报告与仓库）。"""
    tail = dsn.split("@", 1)[-1]
    return tail if "@" in dsn else "<无法解析的 DSN，已省略>"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="T-A1：checkpoint 池行为压测探针（docs/08 §3.3 DoD③）")
    parser.add_argument("--concurrency", default=",".join(str(n) for n in DEFAULT_CONCURRENCY))
    parser.add_argument("--strategies", default=",".join(s.value for s in CheckpointStrategy))
    parser.add_argument("--node-delay", type=float, default=DEFAULT_NODE_DELAY_S)
    parser.add_argument("--sample-interval", type=float, default=DEFAULT_SAMPLE_INTERVAL_S)
    parser.add_argument("--out", type=Path, default=_BACKEND / "reports" / "t-a1")
    parser.add_argument(
        "--superuser-dsn",
        default="postgresql://postgres:postgres@localhost:5432/ecom",
        help="仅用于读 pg_stat_activity（观测通道，不参与被压链路）",
    )
    parser.add_argument("--skip-size-tiers", action="store_true")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    concurrency_levels = [int(part) for part in args.concurrency.split(",") if part.strip()]
    strategies = [CheckpointStrategy(part) for part in args.strategies.split(",") if part.strip()]

    print("=== T-A1 checkpoint 池行为探针 ===")
    print(f"目标 DSN：{_masked(settings.DATABASE_URL)}")
    print(f"节点延时 {args.node_delay}s × 3 节点；采样周期 {args.sample_interval}s")
    print(f"并发档位 {concurrency_levels}；装配臂 {[s.value for s in strategies]}")
    print("⚠️ 探针自身不引入真实 SQL —— 本结论只对 checkpoint 池有效\n")

    results: list[CaseResult] = []
    for strategy in strategies:
        for n in concurrency_levels:
            case = await run_case(
                strategy,
                n,
                settings=settings,
                node_delay_s=args.node_delay,
                sample_interval_s=args.sample_interval,
                superuser_dsn=args.superuser_dsn,
            )
            results.append(case)
            print(
                f"  done {strategy.value} N={n} → wall={case.wall_ms:.0f}ms "
                f"in_use_max={case.pooled_in_use_max} pg_bk={case.pg_backends_max}"
            )

    sizes: list[dict[str, Any]] = []
    if not args.skip_size_tiers:
        print("\n=== 附带：检查点体积 → aput 耗时（§5.2.1 的 64KB 上限支撑）===")
        sizes = await run_size_tiers(settings)
        for row in sizes:
            print(f"  {row['bytes']:>7} B → {row['aput_ms']} ms ok={row['ok']}")

    print()
    print_table(results)
    write_outputs(results, sizes, args.out)
    print(f"\n原始数据已写入 {args.out}（samples.csv / op_timings.csv / summary.json）")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run(main()))
