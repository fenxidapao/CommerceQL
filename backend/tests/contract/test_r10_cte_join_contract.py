"""U-137（T-36 A）：闸门 R10 不认 **CTE 侧 JOIN** —— 契约 vs 实现 vs 文案的三方夹具（零额度、零活体、零 DB）。

| 面 | 内容 |
|---|---|
| 契约 | `docs/07` §7.2 **AST-R10**（`:1831`）：「每个 JOIN 的（左表, 右表, 条件列）必须在 `join_path` 内」；§7.6（`:1953`）把 R05/R10/R11/R13 的文案并成一句「查询涉及的数据范围超出你的权限」 |
| 实现 | `app/guard/ast_gate.py:638-648` 把 JOIN 的左侧候选取成 `from_.find_all(exp.Table)` 的 `t.name` —— 而 sqlglot 把 **CTE 引用也解析成 `exp.Table`** ⇒ 左侧 = CTE 名 ⇒ `self.assets.get(cte)` = `{}` ⇒ `left_logical` 是 CTE 名 ⇒ 与任何认证边都不等 ⇒ `:677-678` 落 **R10** |
| 现实后果 | 面 R 三对六条准入里那 3 条 `GATE_AST_REJECTED`（`tk_8fbf1cf3…`／`tk_51912ce6…`／`tk_0696f1a8…`）全是这一形状：**先聚合（CTE）再连维表**，即"复购率 Top 店铺"这类产品主形态；且用户读到的文案是"超出你的权限"（实际不是越权：两侧资产都在 allowlist 内，租户面由 RLS ＋ deny 列承担，见 `U-121` 子事实 3） |

三条夹具的分工：

1. `test_cte_side_join_current_shape_r10` —— 钉**现状形状**：`passed=False` ＋ `rule_id=R10` ＋ 文案 = 越权类。
   修好那天这条必须翻红（无论往哪个方向修：放行 ⇒ `passed` 翻；明写"预期拒绝" ⇒ 文案必须翻）⇒ 与 `docs/07` 的 `U-137` 行同时改。
2. `test_frozen_redteam_r10_arms_still_block` —— 钉**逐臂复查**：三条冻结红队臂（RT-R10-001/002/003）都是
   **真实资产对**、不含 CTE 侧 ⇒ 本号裁定的放宽面**动不到它们**。谁把认证面放宽到放走未授权资产对，这条红。
3. `test_u137_registered_and_names_the_cte_side_trigger` —— 钉**台账在位**：`U-137` 行存在且点名 CTE 侧，
   且 §7.2 AST-R10 行带 v1.7.21 那句"左表/右表指**资产**"的定义补句。

零额度：`run_gate1` 纯静态（sqlglot ＋ 语义包 YAML），不发 LLM、不连库。
"""

from __future__ import annotations

import json
import os

from app.core.enums import AstRule
from app.guard.ast_gate import _FROM_KEY, run_gate1
from app.guard.rules import RULE_BY_ID
from tests.unit.guard_fixtures import REDTEAM_PATH, build_allowlist

__all__ = [
    "test_cte_side_join_current_shape_r10",
    "test_frozen_redteam_r10_arms_still_block",
    "test_u137_registered_and_names_the_cte_side_trigger",
]

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_TDD = os.path.join(_ROOT, "docs", "07_技术设计文档_TDD.md")

#: 面 R 三条红的**同形骨架**（取自 `app.audit_log.final_executed_sql`，`tk_0696f1a88…`，776 字符）。
#: 关键形状 = `FROM <CTE 名> JOIN v_shop ON …`：两侧都在 allowlist 的资产面上，但左侧是 CTE 名。
_CTE_JOIN_SQL = """
WITH buyer_shop_cnt AS (
  SELECT v_order_paid.shop_id AS shop_id, v_order_paid.buyer_id AS buyer_id,
         COUNT(DISTINCT v_order_paid.sub_order_id) AS cnt
  FROM v_order_paid
  WHERE v_order_paid.pay_status = %(pay_status)s AND v_order_paid.is_test_order = false
  GROUP BY v_order_paid.shop_id, v_order_paid.buyer_id
)
SELECT v_shop.shop_id AS shop_id, v_shop.shop_name AS shop_name,
       COUNT(DISTINCT CASE WHEN buyer_shop_cnt.cnt >= 2 THEN buyer_shop_cnt.buyer_id END) * 1.0
         / NULLIF(COUNT(DISTINCT buyer_shop_cnt.buyer_id), 0) AS repurchase_rate_90d
FROM buyer_shop_cnt
JOIN v_shop ON v_shop.shop_id = buyer_shop_cnt.shop_id
GROUP BY v_shop.shop_id, v_shop.shop_name
ORDER BY repurchase_rate_90d DESC
LIMIT 10
"""

#: 同一条 SQL 去掉 CTE（直接把聚合写在子查询里也不行，这里改成**资产直连**的对照：证明 R10 是被"左侧是 CTE 名"触发的，
#: 不是被"列/表不在 allowlist"触发的。
_ASSET_DIRECT_JOIN_SQL = """
SELECT v_shop.shop_id AS shop_id, COUNT(DISTINCT v_order_paid.sub_order_id) AS cnt
FROM v_order_paid
JOIN v_shop ON v_shop.shop_id = v_order_paid.shop_id
GROUP BY v_shop.shop_id
LIMIT 10
"""


def _sql(text: str) -> str:
    return " ".join(text.split())


def test_cte_side_join_current_shape_r10() -> None:
    import sqlglot
    from sqlglot import exp

    allow = build_allowlist()
    tree = sqlglot.parse_one(_sql(_CTE_JOIN_SQL), dialect="postgres")
    ctes = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    join = next(iter(tree.find_all(exp.Join)))
    frm = join.parent.args.get(_FROM_KEY)
    lefts = [t.name for t in frm.find_all(exp.Table)] if frm is not None else []

    # 机制：左侧解析出来就是 CTE 名，而 CTE 名不在 assets（= 认证面的定义域）里。
    assert lefts and lefts[0] in ctes, f"左侧应解析成 CTE 名，实得 {lefts} / CTE={ctes}"
    assert lefts[0] not in (allow.get("assets") or {}), "CTE 名不该出现在资产面（这正是触发面）"

    report = run_gate1(_sql(_CTE_JOIN_SQL), allow)
    assert report.gate_result.passed is False, "现状必须仍被拒（这条钉的是 U-137 的现状，不是修完的样子）"
    assert report.gate_result.rule_id == AstRule.R10_JOIN_PATH.value, (
        f"现状归因 = R10，实得 {report.gate_result.rule_id}")

    # 文案面：R10 与"越权"同句 = 本号第二半（修完必须翻红 ⇒ 与 U-137 行同改）。
    rd = RULE_BY_ID[AstRule.R10_JOIN_PATH]
    assert rd.user_message == "查询涉及的数据范围超出你的权限", (
        f"R10 文案已改（{rd.user_message}）⇒ docs/07 的 U-137 行与 §7.6 分组必须同轮改，不许只改代码")

    # 对照：同一对**资产**直连必须通过 ⇒ 证明拒的是"左侧是 CTE 名"，不是资产/列不在面内。
    direct = run_gate1(_sql(_ASSET_DIRECT_JOIN_SQL), allow)
    assert direct.gate_result.passed is True, (
        f"资产直连对照意外被拒：{direct.gate_result.rule_id} ⇒ 本号的归因不再成立，需重裁")


def test_frozen_redteam_r10_arms_still_block() -> None:
    """逐臂复查落盘：三条冻结红队臂都是真实资产对 ⇒ 放宽 CTE 侧动不到它们。"""
    allow = build_allowlist()
    cases = json.loads(REDTEAM_PATH.read_text(encoding="utf-8"))["cases"]
    r10 = [c for c in cases if "R10" in (c.get("rule_ids") or [])]
    assert len(r10) == 3, f"冻结集 R10 臂数变了（实得 {len(r10)}）⇒ 判据变更的逐臂复查要重做"

    for case in r10:
        sql = case["attack_sql"]
        assert "WITH" not in sql.upper(), (
            f"{case['case_id']} 现在带 CTE 侧 ⇒ 本夹具的前提变了：U-137 的放宽面与它重叠，必须逐臂重裁")
        report = run_gate1(sql, allow)
        assert report.gate_result.passed is False, f"{case['case_id']} 被放行 = 安全面破了"
        assert report.gate_result.rule_id == "R10", (
            f"{case['case_id']} 归因漂了：实得 {report.gate_result.rule_id}")


def test_u137_registered_and_names_the_cte_side_trigger() -> None:
    with open(_TDD, encoding="utf-8") as fh:
        tdd = fh.read()

    row = next((ln for ln in tdd.splitlines() if ln.startswith("| **U-137** |")), None)
    assert row is not None, "U-137 未登记在 docs/07 §4.8（改了实现/契约却没落号）"
    assert "CTE" in row and "R10" in row, "U-137 行必须点名 CTE 侧与 R10，否则下一窗无法据此复核"

    r10_row = next((ln for ln in tdd.splitlines() if "| **AST-R10** |" in ln), "")
    assert "v1.7.21" in r10_row, (
        "§7.2 AST-R10 行缺 v1.7.21 的定义补句（「左表 / 右表」指**资产**）⇒ 契约与实现又在各说各话")
