"""U-137（T-39 D 落地）：闸门 R10 的「左表 / 右表」按**资产**判定 —— 契约 vs 实现 vs 文案的三方夹具。

| 面 | 内容 |
|---|---|
| 契约 | `docs/07` §7.2 **AST-R10**：「每个 JOIN 的（左表, 右表, 条件列）必须在 `join_path` 内」＋ v1.7.21 补句「左表/右表指**资产**」＋ v1.7.23 落地句「CTE／派生侧按其所含资产参与认证判定」；§7.6 文案分组已把 R05/R13（越权类）与 R10/R11（路径未认证／笛卡尔风险）**拆成两句** |
| 实现 | `app/guard/ast_gate.py::_side_logical()` 把 JOIN 两侧各自展开成"实际读取的资产逻辑名集合"，再与认证边比；CTE 体内的 JOIN 仍被全树遍历审计，资产/列面仍受 R05/R06/R07 约束 |
| 落地前形状（保留作反证参照） | 旧实现把 CTE 名直接当左表 ⇒ `self.assets.get(cte)` = `{}` ⇒ 永远匹配不到边 ⇒ 落 R10，且文案 = "查询涉及的数据范围超出你的权限"（第 13 轮面 R 三条红 `tk_8fbf1cf3…`／`tk_51912ce6…`／`tk_0696f1a8…` 全是这一形状） |

四条夹具的分工（判据原文 = `docs/07` 的 `U-137` 行格 2「结案判据」，逐字照钉）：

1. `test_cte_side_join_resolves_to_asset_closure` —— **①放行那一支**：机制前提仍在（左侧解析成 CTE 名、且 CTE 名不在资产面），
   但按资产口径必须 `passed=True`；**同件「资产直连」对照仍须 `passed=True`**（钉住归因机制，防止"因别的原因放行"被读成修好了）。
2. `test_frozen_redteam_r10_arms_still_block` —— **②逐臂复查**：三条冻结红队臂（RT-R10-001/002/003）都是真实资产对、
   不含 CTE 侧 ⇒ 放宽面动不到它们；若将来某臂带 CTE ⇒ 前提变、必须重裁（那条守卫仍钉在断言里）。
3. `test_r10_r11_wording_is_not_the_overreach_one` —— **①文案那一支**：R10/R11 的用户文案**不得**与 R05/R13 的
   "超出你的权限"共用一句（这是判据的第二半，也是演示红线那句话的根因）。
4. `test_u137_registered_and_docs_carry_the_asset_ruling` —— **③台账与两处抄本同改**：`U-137` 行在位 ＋
   §7.2 AST-R10 行带 v1.7.21 定义补句 **与** v1.7.23 落地句 ＋ §7.6 的分组已拆开。

零额度：`run_gate1` 纯静态（sqlglot ＋ 语义包 YAML），不发 LLM、不连库、不碰匣带。
"""

from __future__ import annotations

import json
import os

from app.core.enums import AstRule
from app.guard.ast_gate import _FROM_KEY, run_gate1
from app.guard.rules import RULE_BY_ID
from tests.unit.guard_fixtures import REDTEAM_PATH, build_allowlist

__all__ = [
    "test_cte_side_join_resolves_to_asset_closure",
    "test_cte_side_does_not_become_a_blanket_pass",
    "test_frozen_redteam_r10_arms_still_block",
    "test_r10_r11_wording_is_not_the_overreach_one",
    "test_u137_registered_and_docs_carry_the_asset_ruling",
]

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_TDD = os.path.join(_ROOT, "docs", "07_技术设计文档_TDD.md")

#: R05/R13 那一句"越权"文案的**唯一**出处（判据：R10/R11 不许与它共用一句）。
_OVERREACH = "查询涉及的数据范围超出你的权限"

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

#: 对照：**资产直连**的同一条认证边 ⇒ 用来证明"CTE 侧被放行"走的是与直连相同的认证边，
#: 不是"因为别的原因没被拦"。这条必须恒绿。
_ASSET_DIRECT_JOIN_SQL = """
SELECT v_shop.shop_id AS shop_id, COUNT(DISTINCT v_order_paid.sub_order_id) AS cnt
FROM v_order_paid
JOIN v_shop ON v_shop.shop_id = v_order_paid.shop_id
GROUP BY v_shop.shop_id
LIMIT 10
"""

#: 反面对照（本窗自订，防"把 CTE 侧一律放行"）：CTE 里装的是**未认证资产对** ⇒ 仍须 R10。
_CTE_HIDEING_UNCERTIFIED_PAIR_SQL = """
WITH mixed AS (
  SELECT v_order_paid.sku_id AS sku_id, v_traffic_daily.sku_id AS t_sku
  FROM v_order_paid
  CROSS JOIN v_traffic_daily
)
SELECT sku_id FROM mixed LIMIT 10
"""


def _sql(text: str) -> str:
    return " ".join(text.split())


def test_cte_side_join_resolves_to_asset_closure() -> None:
    import sqlglot
    from sqlglot import exp

    allow = build_allowlist()
    tree = sqlglot.parse_one(_sql(_CTE_JOIN_SQL), dialect="postgres")
    ctes = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    join = next(iter(tree.find_all(exp.Join)))
    frm = join.parent.args.get(_FROM_KEY)
    lefts = [t.name for t in frm.find_all(exp.Table)] if frm is not None else []

    # 机制前提**没变**：左侧解析出来仍是 CTE 名，而 CTE 名不在资产定义域里 ⇒ 变的是判定口径。
    assert lefts and lefts[0] in ctes, f"左侧应解析成 CTE 名，实得 {lefts} / CTE={ctes}"
    assert lefts[0] not in (allow.get("assets") or {}), "CTE 名不该出现在资产面（这正是原触发面）"

    report = run_gate1(_sql(_CTE_JOIN_SQL), allow)
    assert report.gate_result.passed is True, (
        f"U-137 已落地 ⇒ CTE 侧应按其所含资产参与认证判定，实得 "
        f"passed={report.gate_result.passed} rule_id={report.gate_result.rule_id}")

    # 对照：同一对**资产**直连必须通过 ⇒ 证明放行走的是同一条认证边，不是别的原因。
    direct = run_gate1(_sql(_ASSET_DIRECT_JOIN_SQL), allow)
    assert direct.gate_result.passed is True, (
        f"资产直连对照意外被拒：{direct.gate_result.rule_id} ⇒ 本号的归因不再成立，需重裁")


def test_cte_side_does_not_become_a_blanket_pass() -> None:
    """本窗自订的反面夹具（判据没写、但不写就守不住）：CTE 侧放宽 ≠ CTE 一律放行。

    CTE 体内藏一条未认证边（`v_order_paid CROSS JOIN v_traffic_daily`）⇒ 体内那条 JOIN 仍须落 R10。
    缺这条，下一轮谁把 `_side_logical` 写成"CTE 名 → 直接 return None"也能让第 1 条绿。
    """
    report = run_gate1(_sql(_CTE_HIDEING_UNCERTIFIED_PAIR_SQL), build_allowlist())
    assert report.gate_result.passed is False, "CTE 体内的未认证边被放行了 ⇒ 放宽面越界"
    assert report.gate_result.rule_id == AstRule.R10_JOIN_PATH.value, (
        f"归因漂了：实得 {report.gate_result.rule_id}")


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


def test_r10_r11_wording_is_not_the_overreach_one() -> None:
    """判据第二半：R10／R11 属"路径未认证／笛卡尔风险"，**不得**与"越权"共用一句。"""
    for rule in (AstRule.R10_JOIN_PATH, AstRule.R11_CARTESIAN):
        message = RULE_BY_ID[rule].user_message
        assert message != _OVERREACH, f"{rule.value} 的文案仍是越权句 ⇒ §7.6 分组与 `rules.py` 没同轮改（第二份真相）"
        assert "权限" not in message, f"{rule.value} 文案仍带『权限』二字：{message}"
    # 越权句仍归 R05／R13 —— 拆组不等于把那句删掉。
    for rule in (AstRule.R05_TABLE_ALLOWLIST, AstRule.R13_UNION_SCOPE):
        assert RULE_BY_ID[rule].user_message == _OVERREACH, f"{rule.value} 的越权文案被误改：{RULE_BY_ID[rule].user_message}"


def test_u137_registered_and_docs_carry_the_asset_ruling() -> None:
    with open(_TDD, encoding="utf-8") as fh:
        tdd = fh.read()

    row = next((ln for ln in tdd.splitlines() if ln.startswith("| **U-137** |")), None)
    assert row is not None, "U-137 未登记在 docs/07 §4.8（改了实现/契约却没落号）"
    assert "CTE" in row and "R10" in row, "U-137 行必须点名 CTE 侧与 R10，否则下一窗无法据此复核"

    r10_row = next((ln for ln in tdd.splitlines() if "| **AST-R10** |" in ln), "")
    assert "v1.7.21" in r10_row, (
        "§7.2 AST-R10 行缺 v1.7.21 的定义补句（「左表 / 右表」指**资产**）⇒ 契约与实现又在各说各话")
    assert "v1.7.23" in r10_row, (
        "§7.2 AST-R10 行缺 v1.7.23 的**落地**句（CTE／派生侧按其所含资产参与判定）⇒ 代码改了、契约还停在'已裁未落'")

    grouping = [ln for ln in tdd.splitlines() if ln.strip().startswith("| AST-R05 / R10 / R11 / R13 |")]
    assert not grouping, (
        f"§7.6 仍把 R05/R10/R11/R13 并成一句（命中 {len(grouping)} 行）⇒ 文案分组没与 `rules.py` 同轮拆开"
        "（⚠️ 只查**行首表行**：`U-137` 台账格里引用这个旧分组名是合法的抄本记录，不算未拆）")
