"""`POST /api/v1/export` —— 导出查询结果为 CSV（附录 A §A.15，Phase B B2）。

层号：L5｜归属窗口：Phase B B2。

--------------------------------------------------------------------------
一、顺序是判据，不是实现细节
--------------------------------------------------------------------------

```
归属校验 → 读已脱敏结果集缓存 → 写 audit_export_log（失败即中止） → 生成并下发 CSV
```

| # | 判据 | 违反后的形态 |
|---|---|---|
| 1 | **审计早于下发** | 先出文件再写审计 = 存在「数据已经离开系统、库里没痕迹」的窗口；写失败时用户手里已有一份无法追溯的导出 |
| 2 | **不重新查库** | 重查会得到「与用户刚看到的结果不一致」的第二份数据 —— 本项目最不接受的失效形态（用户看到 A、导出得到 B，且两边都不报错） |
| 3 | **不缓存文件** | 导出产物是一次性的；落缓存等于给「数据离开边界」再造一个无审计的副本 |
| 4 | **归属校验只在一处** | 复用 `store.get_task`（比对 `tenant_id` + `user_id`，不符一律 `None`）。导出路径上再判一次权限，就是两处各判一次 —— 权限面上最典型的假绿来源 |

⚠️ 判据 1 的边界要说清：审计**先于**下发，但 CSV 的内容在主进程里已先渲染好
（纯函数、无 I/O）。这不违反判据 1 —— 违反的是「把字节送出去」，而那一步在审计之后。
把它写成「先写审计、再渲染」会拉长 Redis 与 DB 之间的空窗，收益为零。

--------------------------------------------------------------------------
二、`TASK_NOT_FOUND` 覆盖三种情形（这不是偷懒，是契约要求）
--------------------------------------------------------------------------
不存在 / 不属于当前用户 / 结果集缓存已过 1h TTL —— **三者同码同文案**。
区分它们等于给攻击者一条 404/403 差分枚举通道（`docs/02 §A.11` 的 404 语义原文
就是「不存在或已过期」）。`state_store.get_task` 的所有权校验已经按这个口径返回 `None`，
本文件只是不在它之外另开口子。

--------------------------------------------------------------------------
三、CSV 注入防护会**改变单元格字面值**（刻意，必须写明）
--------------------------------------------------------------------------
以 `= + - @ \t \r` 开头的单元格加一个前导 `'`。代价：文件里该单元格的字面值
与库里不同（Excel 打开显示为原文、另有前导单引号被吃掉）。收益：不让人用一条
查询结果在运维的 Excel 里执行公式。取舍已写进 `render_csv` 的 docstring 与单测。
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.api.deps import (
    authenticate,
    check_rate_limit,
    get_graph_runtime,
    get_runtime,
    new_identity,
    remember_identity,
    trace_scope,
)
from app.api.dto.export import ExportRequest
from app.api.exceptions import task_not_found
from app.api.routers.query import read_cached_result
from app.auth.tokens import VerifiedToken
from app.core.enums import RateLimitBucket
from app.obs.logging import get_logger
from app.obs.trace import new_id

__all__ = ["CSV_INJECTION_PREFIXES", "render_csv", "router"]

_log = get_logger(__name__)

router = APIRouter(prefix="/export", tags=["export"])

#: CSV 公式注入的起始字符（OWASP 口径）。命中即加前导 `'`。
CSV_INJECTION_PREFIXES: Final[tuple[str, ...]] = ("=", "+", "-", "@", "\t", "\r")

#: `Content-Disposition` 文件名的安全字符集。
#: ⚠️ 必须净化：`task_id` 虽由服务端生成，但**响应头**是可被注入的面
#: （换行会让响应被切开）。这里白名单而不是黑名单 —— 黑名单永远漏一个字符。
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9_.-]")


def _header_text(column: Any) -> str:
    """列元数据 → 表头文本。

    收两种形态：`{name, type_name, unit}`（`data_frame.data_payload` 的产物）与裸字符串
    （旧断言/替身里出现过）。读不出名字就给空串，**不猜**。
    """
    if isinstance(column, Mapping):
        return str(column.get("name") or "")
    return "" if column is None else str(column)


def _cell_text(value: Any) -> Any:
    """单元格 → CSV 值。`None` 写成空串（CSV 没有 NULL），并做公式注入防护。"""
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(CSV_INJECTION_PREFIXES):
        return "'" + value
    return value


def render_csv(
    columns: Sequence[Any], rows: Sequence[Sequence[Any]]
) -> str:
    """把已脱敏结果渲染成 CSV 文本（**纯函数**：零 I/O、零配置、可单测）。

    ⚠️ `lineterminator=\"\\r\\n\"` 是 RFC 4180 的规定形态。用默认的 `\\r\\n`
    在 Excel 下也没问题，显式写出来是为了「换行符是契约的一部分」这件事可见。

    ⚠️ **公式注入防护会改变字面值**：以 `= + - @ \t \r` 开头的字符串加前导 `'`。
    这是刻意取舍（见模块 docstring §三），不是 bug；单测钉住它，避免下一个人
    把「导出应当与库里完全一致」当成 bug 修掉而把防护删了。

    ⚠️ **不做类型归一化**：`Decimal` / `date` / `datetime` 交给 `csv` 的 `str()` 转换。
    它们在本项目里已经过 `app/exec/normalize.py` 归一（07 §8.4），在这里二次解释
    会造出第二套口径。
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([_header_text(column) for column in columns])
    for row in rows:
        writer.writerow([_cell_text(value) for value in row])
    return buffer.getvalue()


def _filename(task_id: str) -> str:
    """`Content-Disposition` 的文件名。

    ⚠️ 净化后可能变空（`task_id` 全是不安全字符）⇒ 退成 `result`：给一个空文件名
    会让浏览器按 URL 猜，而 URL 里带着 `task_id`，那又回到注入面。
    """
    safe = _SAFE_FILENAME.sub("_", task_id)[:64]
    return f"{safe or 'result'}.csv"


@router.post(
    "",
    summary="导出查询结果为 CSV（先审计，失败不下发）",
    responses={
        200: {"content": {"text/csv": {}}, "description": "CSV 文件流（附录 A §A.15）"},
        400: {"description": "format 非法（INVALID_REQUEST）"},
        404: {"description": "任务不存在/不属于你/结果已过期（TASK_NOT_FOUND，三者同码）"},
        429: {"description": "READ 桶超限"},
        500: {"description": "导出审计写入失败（已中止，未下发任何字节）"},
    },
)
async def export_result(
    request: Request,
    body: ExportRequest,
    token: Annotated[VerifiedToken, Depends(authenticate)],
) -> Response:
    """导出（附录 A §A.15）。**审计失败 ⇒ 一个字节都不下发**。"""
    graph_runtime = get_graph_runtime(request)
    app_runtime = get_runtime(request)
    # ⚠️ `session_id` 用服务端占位：附录 A §A.15 的路径里只有 `task_id`，而
    #    `IdentityContext.session_id` 是审计三元组的一部分、非空才有意义。
    #    与 `cancel` / `poll` 同一处置（见 `query.py` 模块 docstring §四）。
    ctx = new_identity(token, session_id=new_id("session"), task_id=body.task_id)
    remember_identity(request, ctx)

    async with trace_scope(ctx):
        quota = await check_rate_limit(request, RateLimitBucket.READ, ctx)

        # ① 归属校验（唯一一处；不符与不存在同形）
        payload = await graph_runtime.store.get_task(ctx, body.task_id)
        if payload is None:
            raise task_not_found(body.task_id)

        # ② 读已脱敏结果集缓存（与轮询同一个读取器，同一套裁剪规则）
        cached = await read_cached_result(
            graph_runtime.result_cache, ctx, body.task_id
        )
        if cached is None:
            # 缓存过期 / 写入失败 / 该轮从未下发 data —— 对调用方都是「结果已过期」。
            raise task_not_found(body.task_id)

        columns = _as_sequence(cached.get("columns"))
        rows = [row for row in _as_sequence(cached.get("rows")) if isinstance(row, Sequence)]
        truncated = bool(cached.get("truncated"))

        # ③ 渲染（纯内存，还没送出去）
        csv_text = render_csv(columns, rows)

        # ④ 审计（**失败即中止**：抛 `AuditWriteFailed` → 500，文件不下发）
        await app_runtime.audit_export.write_export(
            ctx,
            {
                "export_format": body.format,
                "row_count": len(rows),
                "truncated": truncated,
            },
        )

        # ⑤ 下发
        headers = dict(quota.headers())
        headers["Content-Disposition"] = f'attachment; filename="{_filename(body.task_id)}"'
        _log.info(
            "export_delivered",
            task_id=body.task_id,
            row_count=len(rows),
            truncated=truncated,
            export_format=body.format,
            why="导出是数据出边界的行为，逐次留痕（审计在 ④ 已落库）",
        )
        return Response(
            content=csv_text.encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers=headers,
        )


def _as_sequence(value: Any) -> Sequence[Any]:
    """缓存载荷里的 `columns` / `rows` 读成序列（读不出就空序列，**不猜**）。"""
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    if isinstance(value, Sequence):
        return value
    return ()
