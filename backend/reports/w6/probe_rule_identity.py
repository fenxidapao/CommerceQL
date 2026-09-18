"""W6 探针：同一次 deny 列引用，**写法**决定 `rule_id`（R06 还是 R07）。

结论用途：进 `reports/w6/RELAY.md`（上呈 W2C / W1A / 架构）与 §C.7 归因口径说明。

--------------------------------------------------------------------------
一句话结论（2026-09-18 实测）
--------------------------------------------------------------------------
`ast_gate._check_columns` 的判定顺序是「先解析归属，再查 deny」：

```
resolved = self._resolve_column(col, cte_names)      # ast_gate.py:656
if resolved is None: return _build_reject(R06)       # :659  ← 归属失败先落 R06
...
if f"{logical}.{colname}" in deny_columns: return _build_reject(R07)   # :665-667
```

而 `SemanticBundleRuntime.asset_allowlist(ctx)` **按角色把 deny 列从可见列里删掉**
（实测 `v_order_paid` 24 → 21 列，被删的正是 `tenant_id` / `receiver_phone` / `receiver_address`）。
⇒ 无表前缀的 deny 列引用**永远解析不出归属** ⇒ 永远走 `:659` 的 R06 分支；
只有写了表前缀（`o.tenant_id` / `v_order_paid.tenant_id`）才可能命中 R07。

⇒ **同一语义的越权探测有两个身份**：`R06 / FORBIDDEN_SCOPE` 与 `R07 / PII_BLOCKED`。
安全侧没错（都拦下了），**统计侧错了**：PRD §14.2 要求按 `rule_id` 归因、
§C.7 要求把"越权探测"与"列名写错"分开 —— 而这里 `rule_id` 是**书写习惯**的函数。

--------------------------------------------------------------------------
为什么这条与 F2 叠加后会放大（`probe_gate_rejections.py`）
--------------------------------------------------------------------------
`R06` 的用户文案是 `"查询包含受保护字段"`（`rules.py:136-140`，与 R07 同一条），
所以：
* 模型只是写了个不存在的列（含 F2 里**闸门自己注入出来**的列）→ 被告知"你碰了受保护字段"；
* 真正的 PII 探测 → 有 50% 概率（看有没有写表前缀）被记成"列不在白名单"。

两类问题在审计、告警、门禁统计里**互相冒充**。本探针给出的是可复算的最小对照表。

跑法（CommerceQL 根目录）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/probe_rule_identity.py
产物：同目录 `probe_rule_identity.json`
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # reports/w6 -> backend -> repo
for _p in (os.path.join(ROOT, "eval"), os.path.join(ROOT, "backend")):
    sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

from harness import build_guard_allowlist, identity_for_case  # noqa: E402

from app.core.enums import Role  # noqa: E402
from app.guard import run_gate1  # noqa: E402
from app.guard.rules import RULE_BY_ID  # noqa: E402
from app.semantics.loader import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

#: 最小对照：**只差表前缀**，语义完全相同（同列、同表、同租户）。
PAIRS: tuple[tuple[str, str, str], ...] = (
    ("tenant_id_unqualified", "SELECT tenant_id FROM v_order_paid LIMIT 10", "R07"),
    ("tenant_id_qualified", "SELECT o.tenant_id FROM v_order_paid o LIMIT 10", "R07"),
    ("receiver_phone_unqualified", "SELECT receiver_phone FROM v_order_paid LIMIT 10", "R07"),
    ("receiver_phone_qualified", "SELECT v_order_paid.receiver_phone FROM v_order_paid LIMIT 10", "R07"),
    ("cost_price_unqualified", "SELECT cost_price FROM v_product LIMIT 10", "R07"),
    ("cost_price_qualified", "SELECT v_product.cost_price FROM v_product LIMIT 10", "R07"),
    #: 反向对照：一个**根本不存在的列**（既非 deny 也非合法列）—— 期望 R06，看文案是否也报"受保护字段"。
    ("bogus_column", "SELECT not_a_real_col FROM v_order_paid LIMIT 10", "R06"),
)


def main() -> int:
    loaded = load_bundle(_bootstrap.BUNDLE_PATH)
    runtime = SemanticBundleRuntime(loaded)
    ctx = identity_for_case("probe-rule-identity", "T_A", role=Role.ANALYST)
    allowlist = build_guard_allowlist(loaded, runtime, ctx)

    visible = {
        str(a.physical_asset): sorted(allowlist["assets"][str(a.physical_asset)]["columns"])
        for a in loaded.bundle.assets
        if str(a.physical_asset) in allowlist["assets"]
    }
    bundle_cols = {str(a.physical_asset): sorted(str(c.name) for c in a.columns) for a in loaded.bundle.assets}

    rows = []
    for name, sql, expect in PAIRS:
        r = run_gate1(sql, allowlist).gate_result
        rule_def = RULE_BY_ID.get(str(r.rule_id or ""))
        rows.append({
            "probe": name,
            "sql": sql,
            "expected_rule": expect,
            "actual_rule_id": r.rule_id,
            "error_code": rule_def.error_code.value if rule_def is not None else None,
            "user_message": r.reason,
            "matches_frozen_set": r.rule_id == expect,
        })

    out = {
        "deny_columns_dropped_from_visible": {
            p: sorted(set(bundle_cols[p]) - set(visible[p])) for p in visible
            if set(bundle_cols[p]) - set(visible[p])
        },
        "visible_column_count": {p: len(v) for p, v in visible.items()},
        "bundle_column_count": {p: len(v) for p, v in bundle_cols.items()},
        "rows": rows,
        "r07_hits_among_pairs": sum(1 for x in rows if x["actual_rule_id"] == "R07"),
        "r06_hits_among_deny_pairs": sum(
            1 for x in rows if x["expected_rule"] == "R07" and x["actual_rule_id"] == "R06"
        ),
        "finding": (
            "deny 列引用是否命中 R07 取决于**有没有写表前缀**；无前置一律 R06/FORBIDDEN_SCOPE。"
            "且 R06 与 R07 共用文案『查询包含受保护字段』⇒ 列名写错（含闸门注入出的缺列，见 "
            "probe_gate_rejections F2）也会被提示成权限问题。安全侧 fail-closed 正确，"
            "**归因侧（§C.7 / PRD §14.2 的 rule_id 统计）失真**。归属：W2C（判据顺序 + 文案），"
            "编号待架构窗口分配。"
        ),
    }
    path = os.path.join(HERE, "probe_rule_identity.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    for x in rows:
        print(f"{x['probe']:28s} actual={x['actual_rule_id']} expected={x['expected_rule']} msg={x['user_message']}")
    print("written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
