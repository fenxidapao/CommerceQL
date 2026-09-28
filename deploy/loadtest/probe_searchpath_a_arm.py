"""U-124 A 臂复跑探针（只读、零 DeepSeek）：认证视图面在非限定名下是否可达。

判据来自 W2A 的 U-124 结案要求 —— 从含 `d8eca02` 的新树重建镜像后，跑**原样**的
analytics 池（调用方**不**给任何 `search_path` preset）执行非限定 `from v_order_paid`：

- 修复前：`ProgrammingError: relation "v_order_paid" does not exist`（六臂实测的 A 臂）
- 修复后：名称解析通过，且连接建立时 `show search_path` 已等于 `app`
  （池级 `options=-c search_path=app`，唯一构造点见 `app/repo/pools.py:223-253`）

⚠️ **`rows=0` 不是缺陷，是"没给被看见的条件"**：基表 `app.order_paid` 的 RLS 策略
`app.p_order_paid_tenant` 的第二支是
`current_setting('app.shop_ids', true) = '' OR shop_id = ANY(...)`，
而 `current_setting(..., true)` 在键未设时返回 **NULL** ⇒ `NULL = ''` 为 NULL ⇒ 整条策略不为真。
所以只注入 `app.tenant_id` 也仍然是 0 行；**三个身份 GUC 必须一起给**
（生产模板 `app/repo/dsn.py:141-145`：`app.tenant_id` / `app.role` / `app.shop_ids`，
`shop_ids` 空串 = 不限）。本探针因此补第二段：注入身份后重数，应见 200,000（T_A 的全部行）。

⚠️ 只读 `v_order_paid`，不碰事实表写路径、不跑迁移、不碰 `tests/integration`（U-114）。
"""

import asyncio

from app.core.config import Settings
from app.repo.pools import build_analytics_engine


async def main() -> None:
    engine = build_analytics_engine(Settings())
    async with engine.begin() as conn:
        from sqlalchemy import text

        print("show_search_path =", (await conn.execute(text("show search_path"))).scalar())
        print("current_user     =", (await conn.execute(text("select current_user"))).fetchall())
        try:
            n = (await conn.execute(text("select count(*) from v_order_paid"))).scalar()
            print("UNQUALIFIED_VIEW_FACE = OK  rows =", n, "(未注入身份 ⇒ 预期 0)")
        except Exception as exc:  # noqa: BLE001 - 探针要把异常类名原样报出来
            print("UNQUALIFIED_VIEW_FACE = FAIL", type(exc).__name__, str(exc)[:200])
            return
        # 三个身份 GUC 一起给（生产模板是 $1/$2/$3 位置绑定，这里逐条具名绑定，效果同）
        for key, val in (("app.tenant_id", "T_A"), ("app.role", "analyst"), ("app.shop_ids", "")):
            await conn.execute(
                text("select set_config(:k, :v, true)"), {"k": key, "v": val}
            )
        print("WITH_IDENTITY    rows =", (
            await conn.execute(text("select count(*) from v_order_paid"))).scalar())
    await engine.dispose()


asyncio.run(main())
