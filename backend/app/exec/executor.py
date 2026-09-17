"""受控执行器 —— `SqlExecutorPort` 的实现（07 §8.1–8.6 / N-02 / N-05）。

归属窗口：W2D（docs/08 §4.1：`app/exec/**`）。

--------------------------------------------------------------------------------
执行一次 fetch 的完整动作序列（顺序即契约，任何一条都不可省）
--------------------------------------------------------------------------------

1. **analytics 池唯一出口**：只用构造时注入的 analytics engine（`app_ro`）；
2. **`prepare_threshold = None`**：命名预处理语句在事务池化下不可靠（07 §8.1 纪律 3；
   W1B 在 pools.py 明确把这一步留给了本模块）；
3. **身份注入**（ADR-09）：`repo/dsn.IDENTITY_INJECTION_TEMPLATE`（`set_config(..., true)`
   的 GUC 绑参数形态；模板占位符是 pg 原生 `$n`，经 `_bind_dollar_params` 转成
   psycopg 客户端绑定的 `%s` —— 值仍走参数绑定），与连接借用**原子**——这是"裸取连接"被禁止的原因；
4. **资源控制**（07 §8.2）：`SET LOCAL statement_timeout`（⚠️ 毫秒）+ `work_mem`；
   走 `set_config` 绑参数而非 `SET LOCAL` 字面量拼接；
5. **服务端游标分批取**（`fetch_size=1000` 语义），行数上限 `max_rows`（硬上限
   `EXEC_MAX_ROWS`）；
6. **内存估算**：累计行体积，超 `EXEC_MAX_MEMORY_MB` → `EXEC_RESOURCE_EXCEEDED`
   （07 §8.2；**不是** `COST_TOO_HIGH`，附录 A §A.11 补充约定 —— 那是 gate3 的预执行码）；
7. **取消登记**：执行期间 `task_id → backend_pid`，`cancel()` 走
   `pg_cancel_backend`（只对自己连接的后端；不用 `pg_terminate_backend`，§8.3 硬要求 3）；
8. **类型归一化**（07 §8.4，逐条）；
9. **脱敏交接**（N-05）：结果离开本模块**之前**必须过 `MaskPort` —— 掩码后的
   `ResultSet` 才是返回值，任何下游（present / SSE / 缓存）拿到的都不可能有明文；
10. **指纹**（07 §8.8）：`sha256(列序 + 行序 + 生效参数)`，不含 tenant_id。

--------------------------------------------------------------------------------
诚实边界（P0 范围外，未掩盖）
--------------------------------------------------------------------------------

- **列身份掩码（sensitivity 路径）在 executor 侧未接线**：输出列名（SQL 别名）→
  语义包资产的映射属绑定层（W3C 的 `bindings`），端口签名里没有它的位置。
  P0 接线的是**语义包 mask_rules 覆盖路径**（`bundle.policy()["mask_rules"]`
  对输出列名做正则匹配 —— 判据仍是语义包声明，不是本模块发明的正则）。
  引擎本身的 sensitivity 路径已实现并有测试，等 W4 在装配点提供列身份映射即可启用。
- **`ColumnMeta.unit` 恒为 None**：单位标注需要"输出列 → 指标"映射（绑定层），
  同上归 W4 装配点。
- **每租户连接配额是进程内信号量**（40% × analytics 池上限，07 §8.2）：
  多进程部署时各进程独立计数 —— 07 的"池内按租户"语义在单进程下成立，
  多进程形态由 W7 的部署模型决定，不在此假装全局。
"""

from __future__ import annotations

import asyncio
import re
import sys
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any, Final
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.core.contracts import (
    ColumnMeta,
    IdentityContext,
    MaskPort,
    ResultSet,
    SemanticBundlePort,
)
from app.core.errors import CommerceQLError
from app.exec.errors import ExecError, ExecFailure, classify_pg_error
from app.exec.fingerprint import result_fingerprint
from app.exec.normalize import normalize_row, raw_type_name
from app.repo.dsn import IDENTITY_INJECTION_TEMPLATE

__all__ = ["PgSqlExecutor", "FETCH_SIZE", "WORK_MEM", "TENANT_QUOTA_RATIO"]

#: 服务端游标分批大小（07 §8.2："游标按 fetch_size=1000 分批取"）。
FETCH_SIZE: Final[int] = 1000

#: `work_mem`（07 §8.2：防大排序落盘拖垮实例）。
WORK_MEM: Final[str] = "64MB"

#: 每租户连接配额占 analytics 池硬上限的比例（07 §8.2：40%）。
TENANT_QUOTA_RATIO: Final[float] = 0.4

_EXEC_STATEMENT_TIMEOUT_SQL: Final[str] = (
    "SELECT set_config('statement_timeout', %s, true), set_config('work_mem', %s, true)"
)

_CANCEL_SQL: Final[str] = "SELECT pg_cancel_backend(:pid)"

#: pg 原生位置占位符（`$n`，如 `repo/dsn.IDENTITY_INJECTION_TEMPLATE`）→ psycopg 客户端绑定形态（`%s`）。
_DOLLAR_RE: Final[re.Pattern[str]] = re.compile(r"\$(\d+)")


def _bind_dollar_params(template: str, params: Sequence[Any]) -> tuple[str, tuple[Any, ...]]:
    """把 pg 原生 `$n` 模板转换成 psycopg 可绑定形态并按 `$n` 序重排参数。

    契约模板（W1B 的 `IDENTITY_INJECTION_TEMPLATE`）用 `$n` 写占位符 —— 那是
    pg 服务端绑定形态；psycopg 的客户端绑定只认 `%s`（值仍走参数绑定，N-04
    不受影响：转换只动占位符，不碰值）。
    占位符不连续 / 有缺号 / 参数不足 → 契约破损，fail-fast（绝不静默错位绑定）。
    """
    idx = [int(m) - 1 for m in _DOLLAR_RE.findall(template)]
    if not idx or len(set(idx)) != len(idx) or set(idx) != set(range(max(idx) + 1)):
        # 占位符必须恰好是 $1..$max 各出现一次：缺号 / 重复都拒绝；
        # 出现次序可以乱（按 $n 重排参数），但编号集合必须完整。
        raise CommerceQLError(
            "身份注入模板占位符不是完整的 $1..$n（契约破损）",
            detail={"placeholders": len(idx), "distinct": len(set(idx))},
        )
    if len(params) != len(idx):
        raise CommerceQLError(
            "身份注入参数数量与模板占位符不一致（契约破损）",
            detail={"placeholders": len(idx), "params": len(params)},
        )
    return _DOLLAR_RE.sub("%s", template), tuple(params[i] for i in idx)


def _estimate_cell_bytes(value: Any) -> int:
    """单格体积估算（07 §8.2："sys.getsizeof 级估算 + 行数×列宽"）。"""
    if value is None:
        return 8  # null 占位
    if isinstance(value, (bytes, memoryview, bytearray, str)):
        return sys.getsizeof(value)
    if isinstance(value, (dict, list, tuple)):
        return sys.getsizeof(value) + sum(_estimate_cell_bytes(v) for v in value)
    return sys.getsizeof(value)


class PgSqlExecutor:
    """`SqlExecutorPort` 实现。构造期注入全部依赖（可离线替身测试）。"""

    def __init__(
        self,
        analytics_engine: Any,  # SQLAlchemy AsyncEngine（W1B 的 analytics 池）
        mask: MaskPort,
        settings: Settings,
        *,
        bundle: SemanticBundlePort | None = None,
        tz: ZoneInfo | None = None,
        tenant_quota: int | None = None,
    ) -> None:
        self._engine = analytics_engine
        self._mask = mask
        self._settings = settings
        self._bundle = bundle
        self._tz = tz or ZoneInfo(settings.TIMEZONE)
        # 每租户配额：默认 40% × analytics 池硬上限（07 §8.2）
        spec_max = 40  # POOL_SPECS[ANALYTICS].max_size（20+20）；不 import 以免反向耦合装配细节
        self._tenant_quota = tenant_quota if tenant_quota is not None else max(1, int(spec_max * TENANT_QUOTA_RATIO))
        self._tenant_semaphores: dict[str, asyncio.Semaphore] = {}
        # 取消登记：task_id → backend_pid（进程内；执行结束即清除）
        self._running: dict[str, int] = {}

    # ------------------------------------------------------------------
    # SqlExecutorPort.fetch
    # ------------------------------------------------------------------

    async def fetch(
        self,
        sql: str,
        params: Mapping[str, Any],
        ctx: IdentityContext,
        *,
        max_rows: int,
        statement_timeout_ms: int,
        effective_limit: int | None = None,
    ) -> ResultSet:
        """受控执行 → 类型归一化 → 脱敏 → 指纹（N-02 / N-05 / 07 §8.4/8.6/8.8）。

        `effective_limit`：闸门改写后的生效 LIMIT（state.limit_injected，07 §7.3）。
        给了它，`truncated` 按 §8.6 原文判定（行数 == 生效 LIMIT）；
        不给（仅离线调用方），退化为"取到 max_rows 仍有余量"判定 —— 两者在
        "注入 LIMIT == max_rows"的常规路径下等价，但前者是**唯一**能正确处理
        "生效 LIMIT < max_rows"的口径。

        ⚠️ 本方法只接**业务 SELECT**。EXPLAIN（gate3_cost，U-63）必须走
        `explain()` —— EXPLAIN 不能经 DECLARE 游标执行（PG 实测 42601），
        计划 JSON 也不是掩码/指纹管线的适用对象。
        """
        if max_rows > self._settings.EXEC_MAX_ROWS:
            max_rows = self._settings.EXEC_MAX_ROWS
        if statement_timeout_ms <= 0:
            raise ValueError(f"statement_timeout_ms 必须为正（毫秒）：{statement_timeout_ms}")

        memory_budget = self._settings.EXEC_MAX_MEMORY_MB * 1024 * 1024
        async with self._controlled_session(ctx, statement_timeout_ms=statement_timeout_ms) as raw:
            return await self._execute_and_collect(
                raw, sql, params, ctx, max_rows=max_rows,
                effective_limit=effective_limit, memory_budget=memory_budget,
            )

    # ------------------------------------------------------------------
    # EXPLAIN 受控入口（U-63 正式契约：gate3_cost 节点的唯一合法通道）
    # ------------------------------------------------------------------

    async def explain(
        self,
        sql: str,
        params: Mapping[str, Any],
        ctx: IdentityContext,
        *,
        statement_timeout_ms: int,
    ) -> list[dict[str, Any]]:
        """gate3 成本预估的 EXPLAIN 通道（U-63：W4 `gate3_cost` 节点专用）。

        与 `fetch` 共享**同一套受控前提**（07 §7.5 三前提 / U-63 限定）：
        analytics 池 + 同事务 + 同身份 GUC 注入 + 只读连接 + statement_timeout +
        取消登记 —— 节点**不得**自建连接（U-63 原文）。

        ⚠️ 为什么不是 `fetch`：EXPLAIN 不能经 `DECLARE ... CURSOR` 执行
        （PG 实测 42601，与 DML 同因）；且计划 JSON 不是业务结果集 ——
        掩码（N-05）/ 类型归一化 / 指纹（§8.8）都是为**用户数据**设计的，
        对计划不适用。

        契约：`sql` 必须是 `EXPLAIN (FORMAT JSON) ...`（返回值才能是
        结构化计划而非文本）；普通 EXPLAIN 会在 fail-closed 检查处被拒。
        返回 = psycopg 解析后的计划 JSON（`list[dict]`，单行单列的第 0 列）。
        """
        if not sql.lstrip().upper().startswith("EXPLAIN"):
            raise CommerceQLError(
                "explain() 只接受 EXPLAIN 语句（契约破损）",
                detail={"stage": "explain"},
            )
        async with self._controlled_session(ctx, statement_timeout_ms=statement_timeout_ms) as raw:
            async with raw.cursor() as cur:
                await cur.execute(sql, dict(params) if params else None)
                row = await cur.fetchone()
            if row is None:
                raise CommerceQLError(
                    "EXPLAIN 没有输出（契约破损）", detail={"stage": "explain"}
                )
            plan = row[0]
        if not isinstance(plan, list):
            # 文本形态的 EXPLAIN 输出是 str —— 说明调用方漏了 FORMAT JSON
            raise CommerceQLError(
                "EXPLAIN 必须使用 FORMAT JSON（契约破损）", detail={"stage": "explain"}
            )
        return plan

    # ------------------------------------------------------------------
    # 取消（07 §8.3；SSE 断连检测归 W4，本模块只提供能力）
    # ------------------------------------------------------------------

    async def cancel(self, task_id: str) -> bool:
        """`pg_cancel_backend`（只对自己连接的后端；**不用** terminate，§8.3）。

        同角色（app_ro）可取消自己的后端，故从 analytics 池另借一条连接发取消。
        目标不在执行中（已结束 / 未开始）→ False（幂等）。
        """
        pid = self._running.get(task_id)
        if pid is None:
            return False
        async with self._engine.connect() as conn:
            await conn.execute(self._text(_CANCEL_SQL), {"pid": pid})
        return True

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def _controlled_session(
        self, ctx: IdentityContext, *, statement_timeout_ms: int
    ) -> AsyncIterator[Any]:
        """受控会话（fetch / explain 共用的**唯一**序列，07 §8.1–8.2 顺序即契约）：

        每租户配额 → analytics 池借连接 → 揭盖取 psycopg 本体 → `prepare_threshold=None`
        → 取消登记 → 事务 + ADR-09 身份注入 + statement_timeout/work_mem。
        退出统一清理：登记表 pop；PG 错误 → 脱敏分类（N-11）；非 PG 异常 →
        内部错误（绝不伪装成 SQL 错误喂 repair）。
        """
        if statement_timeout_ms <= 0:
            raise ValueError(f"statement_timeout_ms 必须为正（毫秒）：{statement_timeout_ms}")
        sema = self._tenant_semaphores.setdefault(
            ctx.tenant_id, asyncio.Semaphore(self._tenant_quota)
        )
        async with sema, self._engine.connect() as conn:
            raw = await self._raw_connection(conn)
            if raw is None:
                raise CommerceQLError(
                    "analytics 池未给出可用的 psycopg 连接（装配缺陷，非运行时故障）",
                    detail={"engine": type(self._engine).__name__},
                )
            # 纪律 3（07 §8.1）：命名预处理语句在事务池化下不可靠
            raw.prepare_threshold = None
            pid = raw.pgconn.backend_pid
            self._running[ctx.task_id] = pid
            try:
                async with conn.begin():
                    # ADR-09：身份注入与连接借用原子（值一律绑定参数，N-04）
                    inj_sql, inj_params = _bind_dollar_params(
                        IDENTITY_INJECTION_TEMPLATE,
                        (ctx.tenant_id, ctx.role.value, ",".join(ctx.shop_ids)),
                    )
                    await raw.execute(inj_sql, inj_params)
                    # ⚠️ statement_timeout 单位是毫秒（07 §8.2 陷阱注释）
                    await raw.execute(
                        _EXEC_STATEMENT_TIMEOUT_SQL,
                        (str(statement_timeout_ms), WORK_MEM),
                    )
                    yield raw
            except CommerceQLError:
                raise
            except asyncio.CancelledError:
                # 不得吞掉取消：pg_cancel / asyncio 取消链路依赖它（07 §8.3 硬要求 1）
                raise
            except BaseException as exc:
                import psycopg

                if isinstance(exc, psycopg.Error):
                    # PG 错误 → 统一走脱敏分类（N-11）
                    raise ExecFailure(classify_pg_error(exc)) from exc
                # 非 PG 异常（应用缺陷）：绝不伪装成 SQL 错误喂给 repair
                # （那会让 LLM 修一条根本没坏的 SQL）—— 按内部错误诚实上抛。
                raise CommerceQLError(
                    "执行层内部错误", detail={"stage": "controlled_session", "error_kind": type(exc).__name__}
                ) from exc
            finally:
                self._running.pop(ctx.task_id, None)

    async def _execute_and_collect(
        self,
        raw: Any,
        sql: str,
        params: Mapping[str, Any],
        ctx: IdentityContext,
        *,
        max_rows: int,
        effective_limit: int | None,
        memory_budget: int,
    ) -> ResultSet:
        # 服务端游标：分批取，不在应用侧一次性物化全量（07 §8.2）
        # 收集硬上限：给了 effective_limit 还要再压一道（纵深防御：即便 SQL 里
        # 的 LIMIT 改写失守，执行器也绝不返回超过生效 LIMIT 的行数，§8.6）
        collect_cap = max_rows if effective_limit is None else min(max_rows, effective_limit)
        estimated = 0
        collected: list[tuple[Any, ...]] = []
        col_names: tuple[str, ...] | None = None
        async with raw.cursor(name="commerceql_exec") as scur:
            # ⚠️ params 必须按**映射**传（psycopg 的 %(name)s 形态，N-04 参数化绑定）：
            # 位置形态会依赖 dict 序 —— 那是调用方重排参数名时的静默错位。
            await scur.execute(sql, dict(params) if params else None)
            if scur.description is not None:
                col_names = tuple(d.name for d in scur.description)
            else:
                raise CommerceQLError(
                    "执行语句没有结果集（闸门只放行 SELECT —— 契约破损）",
                    detail={"has_result_set": False},
                )
            while True:
                batch = await scur.fetchmany(FETCH_SIZE)
                if not batch:
                    break
                for row in batch:
                    collected.append(tuple(row))
                    estimated += sum(_estimate_cell_bytes(c) for c in row)
                    if estimated > memory_budget:
                        # 先关闭游标把查询真正停掉，再抛（连接归还后查询不能还挂着）
                        # ⚠️ `_resource_error` 返回的就是成品 ExecFailure（自带 detail），
                        # 直接 raise —— 再包一层会把 ExecFailure 当 ExecError 用，必炸
                        await scur.close()
                        raise _resource_error(estimated, memory_budget)
                    if len(collected) > collect_cap:
                        break  # 只多取 1 行用于"是否还有余量"判定，立即停
                if len(collected) > collect_cap:
                    await scur.close()
                    break

        more_exist = len(collected) > collect_cap
        rows_raw = collected[:collect_cap]

        # 07 §8.4：类型归一化（先归一化，掩码在字符串形态上工作）
        rows_norm = [normalize_row(r, tz=self._tz) for r in rows_raw]

        # 07 §8.6：truncated 只由 LIMIT 触发；RLS 减行**不可能**触发本判定
        truncated = len(rows_norm) == effective_limit if effective_limit is not None else more_exist

        # N-05：离开 exec 前必须脱敏（掩码后的值才是返回值，下游不可能拿到明文）
        policy = self._mask_policy(col_names or ())
        outcome = self._mask.apply(rows_norm, policy)

        # ⚠️ 列元数据按**原始值**判型（归一化后 Decimal 已是字符串，类型信息会丢）
        columns = self._column_meta(col_names or (), rows_raw)
        fingerprint = result_fingerprint(
            columns=[c.name for c in columns], rows=outcome.rows, params=params
        )
        return ResultSet(
            columns=columns,
            rows=outcome.rows,
            row_count=len(outcome.rows),
            truncated=truncated,
            fingerprint=fingerprint,
        )

    def _mask_policy(self, col_names: tuple[str, ...]) -> dict[str, Any]:
        """组装 `MaskPort` 的 policy 载荷（形状约定见 app/mask/engine.py）。

        ⚠️ sensitivity 恒 None（P0 诚实边界，见模块头）：输出列名 → 语义包资产的
        映射属绑定层，P0 接线的是语义包 mask_rules 覆盖路径。
        """
        mask_rules: Sequence[Mapping[str, Any]] = ()
        if self._bundle is not None:
            bundle_policy = self._bundle.policy() or {}
            mask_rules = bundle_policy.get("mask_rules", ()) or ()
        return {
            "columns": [{"name": name, "sensitivity": None} for name in col_names],
            "mask_rules": list(mask_rules),
        }

    @staticmethod
    def _column_meta(col_names: Sequence[str], rows_raw: Sequence[Sequence[Any]]) -> tuple[ColumnMeta, ...]:
        """列元数据。⚠️ 按原始值判型（`raw_type_name`），归一化后判不出 decimal。"""
        metas: list[ColumnMeta] = []
        for idx, name in enumerate(col_names):
            type_name = "null"
            for row in rows_raw:
                if row[idx] is not None:
                    type_name = raw_type_name(row[idx])
                    break
            # unit 恒 None（诚实边界：输出列 → 指标单位映射归绑定层/W4）
            metas.append(ColumnMeta(name=name, type_name=type_name, unit=None))
        return tuple(metas)

    @staticmethod
    async def _raw_connection(conn: Any) -> Any | None:
        """SQLAlchemy AsyncConnection → 底层 psycopg 连接（唯一的"揭盖"点）。

        async 门面必须走 `get_raw_connection()` 协程（`conn.connection` 属性在
        AsyncConnection 上未实现）；链条：`AdaptedConnection.dbapi_connection`
        `.driver_connection`（psycopg.AsyncConnection 本体）。
        拿不到 → 返回 None（调用方 fail-fast），**绝不**静默退化成"没有身份注入"。
        """
        inner = await conn.get_raw_connection()
        dbapi = getattr(inner, "dbapi_connection", None)
        if dbapi is None:
            return None
        raw = getattr(dbapi, "driver_connection", dbapi)
        return raw if hasattr(raw, "pgconn") else None

    @staticmethod
    def _text(sql: str) -> Any:
        """SQLAlchemy `text()` 的局部包装（避免模块级 import 第三方方言细节）。"""
        from sqlalchemy import text

        return text(sql)


def _resource_error(estimated: int, budget: int) -> ExecFailure:
    """内存超限 → `EXEC_RESOURCE_EXCEEDED`（**不是** COST_TOO_HIGH，附录 A §A.11）。"""
    from app.core.enums import LimitType

    return ExecFailure(
        ExecError(
            error_class="resource_exceeded",
            pgcode=None,
            message="查询结果超出单次内存上限，请收窄查询范围或增加过滤条件",
            llm_hint=None,
        ),
        detail={"limit_type": LimitType.MEMORY.value, "estimated_bytes": estimated, "budget_bytes": budget},
    )
