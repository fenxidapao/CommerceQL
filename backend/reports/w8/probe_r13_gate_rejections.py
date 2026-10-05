"""T-36 A（零额度）：把面 R 那三条 `GATE_AST_REJECTED` **逐条归因**，结论必给。

为什么单独打这一枪：`U-125` 判据④ 明令「生产侧拿不到 `rule_id` ⇒ 任何按规则号的归因必须标
"来自离线器件"」。回执里只有 `code`＋`outcome`＋`stage=sql_ready`，三条红落在 `U-129` 的读数面上
就被计进 `ok` 率的分母 ⇒ 悬着就是"50% 没有解释人"。

判据面（读码，不改码）：
- 契约：`docs/07` §7.2 **AST-R10**（`:1831`）「每个 JOIN 的（左表, 右表, 条件列）必须在 `join_path` 内」；
- 实现：`app/guard/ast_gate.py:638-648` 把左侧候选取成 `from_.find_all(exp.Table)` 的 `t.name`，
  而 sqlglot 把 **CTE 引用也解析成 `exp.Table`** ⇒ 左侧 = CTE 名 ⇒ `self.assets.get(cte)` = `{}`
  ⇒ `left_logical` 是 CTE 名 ⇒ 与任何认证边都不等 ⇒ `:677-678` **④ 无认证边 → R10**；
- 文案：`app/guard/rules.py` 的 `R10_JOIN_PATH` 用 `_msg_scope()` = 「查询涉及的数据范围超出你的权限」
  ⇒ 把"路径未认证"报成"越权"，方向指错（租户面实际由 RLS ＋ deny 列承担，见 `U-121` 子事实 3）。

口径（每条只落一类，优先级从上到下）：
- `cte_side_join`      —— JOIN 的**任一侧是 CTE 名**（`with` 的别名）⇒ 闸门认证面不认派生侧；
- `injection_self_defect` —— `eval/harness.detect_gate_self_defect` 命中 F1/F2 ⇒ 闸门的账；
- `model_unknown_column`  —— R06 且模型引用的列不在该资产可见面；
- `other:<rule>`          —— 其余，回显规则号。

复算（cwd = 仓库根 `CommerceQL/`；只读取证，外层 `begin; … rollback;`，服务端零持久写、零出站）：
    PYTHONUTF8=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w8/probe_r13_gate_rejections.py
产物：同目录 `probe_r13_gate_rejections.json`
"""

from __future__ import annotations

import argparse
import base64
import collections
import glob
import json
import os
import subprocess
import sys
from datetime import UTC, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # reports/w8 -> backend -> repo
for _p in (os.path.join(ROOT, "eval"), os.path.join(ROOT, "backend")):
    sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

import harness as eval_harness  # noqa: E402
import sqlglot  # noqa: E402
from sqlglot import exp  # noqa: E402

from app.auth.context import IdentityContext  # noqa: E402
from app.core.enums import Role  # noqa: E402
from app.guard import run_gate1  # noqa: E402
from app.guard.ast_gate import _FROM_KEY  # noqa: E402
from app.guard.rules import RULE_BY_ID  # noqa: E402
from app.semantics.loader import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

CONTAINER = "commerceql-pg-1"
DB = "ecom"
OUT = os.path.join(HERE, "probe_r13_gate_rejections.json")
RECEIPT_GLOB = "deploy/loadtest/u129_paprime_r12_pair*.json"


def _psql(sql: str) -> list[str]:
    """只读取证：外层 `begin; … rollback;` ⇒ 服务端零持久写（零额度自证）。"""
    script = "begin;\n\\set ON_ERROR_STOP on\n" + sql.strip() + "\nrollback;\n"
    proc = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", DB,
         "-t", "-A", "-v", "ON_ERROR_STOP=1", "-f", "-"],
        input=script, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"psql rc={proc.returncode}: {(proc.stderr or '').strip()[:400]}")
    return [ln.rstrip("\r") for ln in (proc.stdout or "").splitlines()
            if ln.strip() not in ("", "BEGIN", "ROLLBACK")]


def _sql_of(task_id: str) -> dict[str, str]:
    """`encode(base64)` 单列取出 SQL：psql 会在 76 字符折行 ⇒ 续行**拼接**还原。"""
    sel = ("select encode(convert_to(final_executed_sql,'UTF8'),'base64') from app.audit_log "
           f"where task_id = '{task_id}';")
    body = "".join(ln.strip() for ln in _psql(sel))
    meta = _psql("select tenant_id || '~' || user_id || '~' || role || '~' || coalesce(length("
                 "final_executed_sql)::text,'-') || '~' || raw_question from app.audit_log "
                 f"where task_id = '{task_id}';")
    sql = base64.b64decode(body).decode("utf-8")
    tenant, user, role, declared_len, question = (meta[0].split("~") + ["?"] * 5)[:5]
    return {"sql": sql, "tenant_id": tenant, "user_id": user, "role": role, "raw_question": question,
            "declared_len": int(declared_len), "decoded_len": len(sql)}


def _rejecting_task_ids(receipts: list[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for path in receipts:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        for sc in payload.get("scenarios") or []:
            adm = sc.get("admission") or {}
            for code, ids in (sc.get("codes_task_ids") or {}).items():
                if code == "GATE_AST_REJECTED":
                    for tk in ids:
                        out.append({"task_id": tk, "receipt": os.path.basename(path),
                                    "receipt_admitted": adm.get("admitted"),
                                    "receipt_terminal": adm.get("terminal")})
    return out


def _cte_names(tree: exp.Expr) -> set[str]:
    return {c.alias_or_name for c in tree.find_all(exp.CTE) if c.alias_or_name}


def _join_sides(tree: exp.Expr) -> list[dict[str, object]]:
    rows = []
    for j in tree.find_all(exp.Join):
        right = j.this
        parent = j.parent
        lefts: list[str] = []
        if isinstance(parent, exp.Select):
            frm = parent.args.get(_FROM_KEY)  # 🔻 与闸门同一个键（本 sqlglot 版本是 `from_`，写死 "from" 会读到 None）
            if frm is not None:
                lefts = [t.name for t in frm.find_all(exp.Table)]
        rows.append({"lefts": lefts,
                     "right": getattr(right, "name", None),
                     "on": None if j.args.get("on") is None else j.args["on"].sql(dialect="postgres")})
    return rows


def _self_identity() -> dict[str, object]:
    """🔻 10-05 T-37 C：产物**自报身份三格**（rev／dirty／时刻）。

    这是 `T-11 ②` 的第三实例（前两处 = `t33_u130_coupling.json`、`gate_inputs_p0_summary.json`）：
    引用一个离线读数时必须能问"它是哪一笔、干净与否、什么时候取的"，否则下一轮只能靠文档里
    的一句话相信它 —— 而本项目"两跑矛盾"的成因形状之一就是**分母含目录／件内自报 rev 与入库笔混写**。
    ⚠️ `dirty` 记的是**取数那一秒的工作树**，不是提交后的状态 ⇒ 引用时两件事分开引。
    """
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace"
        ).stdout.strip()

    return {
        "rev": git("rev-parse", "--short", "HEAD"),
        "rev_full": git("rev-parse", "HEAD"),
        "commit_count": int(git("rev-list", "--count", "HEAD") or 0),
        "dirty": bool(git("status", "--porcelain")),
        "captured_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _receipt_selection(receipts: list[str], explicit: bool) -> dict[str, object]:
    """`--receipt` 缺省时**点名用了哪几把**（缺省 = 按 mtime 取 `RECEIPT_GLOB` 全组）。"""
    return {
        "mode": "explicit_cli" if explicit else "default_glob_by_mtime",
        "glob": os.path.relpath(os.path.join(ROOT, RECEIPT_GLOB), ROOT),
        "container": CONTAINER,
        "files": [
            {
                "path": os.path.relpath(p, ROOT),
                "mtime_utc": datetime.fromtimestamp(os.path.getmtime(p), UTC).isoformat(timespec="seconds"),
                "bytes": os.path.getsize(p),
            }
            for p in receipts
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipt", action="append", default=None,
                    help=f"可多次；缺省 = 按 mtime 取最新一组 {RECEIPT_GLOB}")
    args = ap.parse_args(argv)

    receipts = args.receipt or sorted(glob.glob(os.path.join(ROOT, RECEIPT_GLOB)),
                                     key=os.path.getmtime)
    print(f"所用回执（mode = {'explicit_cli' if args.receipt else 'default_glob_by_mtime'}）：")
    for r in receipts:
        print("  -", os.path.relpath(r, ROOT))

    hits = _rejecting_task_ids(receipts)
    if not hits:
        print("🔴 回执里没有 GATE_AST_REJECTED 的 task_id ⇒ 本件无事可做（不是通过，是无样本）")
        return 0

    runtime = SemanticBundleRuntime(load_bundle(_bootstrap.BUNDLE_PATH))
    rows = []
    for hit in hits:
        rec = _sql_of(hit["task_id"])
        sql = rec["sql"]
        ident_role = Role.ANALYST if rec["role"] == "analyst" else Role.PLATFORM_ADMIN
        identity = IdentityContext(
            trace_id="tr-probe", task_id=hit["task_id"], session_id="se-probe",
            tenant_id=rec["tenant_id"], user_id=rec["user_id"], role=ident_role,
            scope_claims=(), shop_ids=())
        allowlist = runtime.guard_allowlist(identity, max_rows=None)
        report = run_gate1(sql, allowlist)
        self_defect = eval_harness.detect_gate_self_defect(sql, allowlist)
        tree = sqlglot.parse_one(sql, dialect="postgres")
        ctes = _cte_names(tree)
        sides = _join_sides(tree)
        cte_side = any((set(s["lefts"]) | {s["right"]}) & ctes for s in sides)
        rule = report.gate_result.rule_id
        if cte_side:
            klass = "cte_side_join"
        elif self_defect:
            klass = "injection_self_defect"
        elif rule == "R06":
            klass = "model_unknown_column"
        else:
            klass = f"other:{rule}"
        rows.append({
            **hit,
            "tenant_id": rec["tenant_id"], "user_id": rec["user_id"], "role": rec["role"],
            "raw_question": rec["raw_question"],
            "sql_len_declared": rec["declared_len"], "sql_len_decoded": rec["decoded_len"],
            "passed": report.gate_result.passed,
            "rule_id": rule,
            "user_message": RULE_BY_ID[rule].user_message if rule in RULE_BY_ID else None,
            "error_code": (RULE_BY_ID[rule].error_code.value if rule in RULE_BY_ID else None),
            "class": klass,
            "cte_names": sorted(ctes),
            "join_sides": sides,
            "self_defect": self_defect,
            "certified_edges_n": len(allowlist.get("joins") or []),
            "certified_edges": sorted({f"{e.get('left')}–{e.get('right')}"
                                       for e in (allowlist.get("joins") or [])}),
        })

    tally = dict(collections.Counter(r["class"] for r in rows).most_common())
    rule_tally = dict(collections.Counter(r["rule_id"] for r in rows).most_common())
    out = {
        "identity": _self_identity(),
        "receipt_selection": _receipt_selection(receipts, explicit=bool(args.receipt)),
        "face": "面 R 的 GATE_AST_REJECTED 归因（**离线器件产出** ⇒ 依 U-125 判据④ 引用时必须标"
                "「来自离线器件」，不得写成生产可观测）",
        "receipts_used": [os.path.relpath(r, ROOT) for r in receipts],
        "n_rejected": len(rows),
        "class_tally": tally,
        "rule_id_tally": rule_tally,
        "distinct_questions": sorted({r["raw_question"] for r in rows}),
        "rows": [{k: v for k, v in r.items() if k != "sql"} for r in rows],
        "verdict": None,
    }
    if rows and all(r["class"] == "cte_side_join" for r in rows):
        out["verdict"] = (
            "三条红 = **同一形状**：JOIN 的一侧是 CTE 名（先聚合再连维表），而 `_join_verdict` 的左侧候选"
            "取 `from_.find_all(exp.Table)` 的 `t.name` ⇒ CTE 名不在认证边集 ⇒ 落 R10；"
            "且 `R10` 的用户文案是 `_msg_scope()`「查询涉及的数据范围超出你的权限」⇒ **把「路径未认证」报成越权**。"
            "⇒ 既不是 `U-129` 的入口复位面、也不是模型编列（`self_defect` 的 F1 只是别名排序的旁证），"
            "`§4.8` 现无判据覆盖 ⇒ 取新号。")
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

    print(json.dumps({k: out[k] for k in
                      ("n_rejected", "class_tally", "rule_id_tally", "verdict")},
                     ensure_ascii=False, indent=2))
    for r in rows:
        print(f"  {r['task_id'][:14]}… rule={r['rule_id']} passed={r['passed']} class={r['class']} "
              f"cte={r['cte_names']} 文案=「{r['user_message']}」认证边 {r['certified_edges_n']} 条 "
              f"SQL {r['sql_len_declared']}/{r['sql_len_decoded']} 字符")
    print(f"\nwritten: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
