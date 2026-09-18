"""§17.6 口径不变量的**一致性三测**（07 §17.6 末表 ①②③；08 §3.8 产出④）。

归属窗口：W6。

为什么这张表必须"跑"而不是"写"
--------------------------------------------------------------------------
07 §17.6 的原话是"没有它，以上全是口头约定"。I-1…I-6 每一条都能让**同一份冻结集**
给出不同的分层、不同的通过率、不同的结论；而其中三条（①②③）恰好**不需要 LLM、
不需要网络、不花一分钱**就能机器判定 —— 所以它们没有理由出现在报告的"我们承诺"段落里。

| # | 测什么 | 本文件的落地 |
|---|---|---|
| ① | "注入后执行"与"手写含租户谓词的等价 SQL 执行"的 `gold_result_hash` **必须一致** | `test_tenant_boundary()`：三条链路（冻结值 / 视图边界 / `bfs.tenant_wrap`）逐个用例比对 + 边界有效性独立探针 |
| ② | `difficulty_struct_sitelabel` **不得**出现在任何报告 / 门禁输入里 | `assert_field_whitelist()`：源码 + 已产出 JSON 工件的字面扫描，**带正对照**（自检：故意造一次读取必须被抓） |
| ③ | **本项目锚点集**（07 §4.7.2）在 CI 中 100% 命中；官方 4 锚点只作差异记录 | `test_anchors()`：复用 `layering.PROJECT_ANCHORS` / `OFFICIAL_ANCHORS`，**不自己另立一套锚点** |

①的实现取舍（I-4 / I-5 的结构性冲突，详见 `sqlite_exec.py` 文档头 §二）
--------------------------------------------------------------------------
`tenant_id` 在语义包里是 **deny 列**（`policies.deny_columns` 逐条列了 6 个租户域的
`<logical>.tenant_id`），而 `LoadedBundle.allowlist` 的列集已剔除 deny 列
⇒ 把 `tenant_id = '…'` 写进**被审计**的 SQL 一定会被 gate1 拒（R06/R07）。
生产的租户谓词活在 **RLS 策略层**，压根不出现在 SQL 里，所以不撞这个矛盾。

⇒ 评测侧的"注入后"取的是与生产**同构**的那一半：`CREATE TEMP VIEW`（谓词在被测 SQL
之外、DB 对象层），而不是"往 SQL 里拼 tenant 谓词"。W1A 的 `tenant_wrap`（派生表形态）
在这里的角色 = **独立的第二实现**，用来验证视图边界确实等价于"手写含租户谓词"。
两者不一致 = 租户模拟本身失真（I-6 的"用 SQL 注入模拟 RLS"就失去依据），当场 FAIL。

⚠️ 本测试**不**声称验证了 PG 的 RLS 策略 —— 那是 §17.4 缺口表里的结构性未覆盖项。

跑法（CommerceQL 根目录，零 LLM / 零成本）
--------------------------------------------------------------------------
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/consistency.py
产物：`backend/reports/w6/consistency_results.json`；退出码非 0 = 至少一条不变量被破坏。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import _bootstrap

_bootstrap.bootstrap()

import build_frozen_set as bfs  # noqa: E402  # W1A 的唯一哈希/注入实现（只读复用）
import layering  # noqa: E402  # I-1 的唯一分层实现（W1A 归属、只读复用）
from harness import Harness  # noqa: E402  # 租户域清单的唯一导出点
from runner import run_in_sandbox  # noqa: E402  # 两种租户边界的唯一执行入口

__all__ = [
    "assert_field_whitelist",
    "main",
    "run_all",
    "test_anchors",
    "test_boundary_efficacy",
    "test_tenant_boundary",
]

DEFAULT_OUT = os.path.join(
    _bootstrap.ROOT, "backend", "reports", "w6", "consistency_results.json"
)

#: §17.6① 原文要求的条数。
ANCHOR_CASE_N: Final[int] = 3

#: §17.6② 点名的禁止字段（I-1 的"只作对照字段"）。
BANNED_FIELD: Final[str] = "difficulty_struct_sitelabel"

#: 扫描范围 = **报告与门禁输入的全部生产者**（本文件除外：它必须写出被禁字段的名字才能禁它）。
_SCAN_EXCLUDE: Final[frozenset[str]] = frozenset({"consistency.py"})


# ---------------------------------------------------------------------------
# ① 租户边界一致性：注入后执行 vs 手写含租户谓词的等价 SQL
# ---------------------------------------------------------------------------

def select_boundary_cases(
    cases: Sequence[Mapping[str, Any]], *, n: int = ANCHOR_CASE_N
) -> list[dict[str, Any]]:
    """确定性挑 n 条"含 `tenant_scoped` 资产"的用例（§17.6① 的题面要求）。

    判据用 `bfs.tenant_wrap` 的前后差异，而不是本文件自己再写一张表名清单：
    W1A 的注入实现是唯一真相，另起炉灶 = 第二个口径（也正是 I-1 要避免的事）。

    合格 = `expected_behavior == "execute"` ∧ 有 `gold_sql` ∧ 有 `gold_result_hash`
    ∧ **确实被 `tenant_wrap` 改写过的**（不含租户域表的用例两条路径必然同哈希 ——
    拿它做一致性测试会得到一个永远绿的假测试）。

    选取顺序 = **先按 `eval_tenant` 去重**，再按文件原序补足。
    理由：纯原序取前 3 条实测全落在 `T_A`，那"三条链路相等"只在一个租户上被验证过；
    而本测试要护的恰恰是**租户边界**，跨租户覆盖才是它的判别力所在。
    """
    eligible = [
        dict(c)
        for c in cases
        if c.get("gold_sql")
        and c.get("eval_tenant")
        and c.get("gold_result_hash")
        and str(c.get("expected_behavior")) == "execute"
        and bfs.tenant_wrap(str(c["gold_sql"]), str(c["eval_tenant"])) != str(c["gold_sql"])
    ]
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case in eligible:                      # 第一遍：每个租户各一条（跨租户覆盖）
        if len(picked) >= n:
            break
        tenant = str(case["eval_tenant"])
        if tenant in seen:
            continue
        seen.add(tenant)
        picked.append(case)
    for case in eligible:                      # 第二遍：按原序补足
        if len(picked) >= n:
            break
        if case not in picked:
            picked.append(case)
    return picked


def test_tenant_boundary(
    *,
    cases: Sequence[Mapping[str, Any]],
    db_path: str,
    tenant_scoped_physicals: Mapping[str, str],
    n: int = ANCHOR_CASE_N,
) -> dict[str, Any]:
    """§17.6① —— 三条哈希链路必须逐字相等。

    * `frozen` = 冻结集里 W1A 落盘的 `gold_result_hash`（复算它 = N-13 的哈希可复现面）；
    * `wrap`   = "手写含租户谓词的等价 SQL"（`bfs.tenant_wrap` 派生表形态）；
    * `view`   = "注入后执行"（TEMP VIEW 边界，被测 SQL 内不出现 `tenant_id`，与在线同形）。

    `frozen == wrap` 证明冻结标签可复现；`wrap == view` 证明**租户模拟与手写谓词等价**。
    两个等式分开落盘，因为它们的破坏者不是同一方（前者是数据集/沙箱漂移，后者是评测器）。
    """
    picked = select_boundary_cases(cases, n=n)
    rows: list[dict[str, Any]] = []
    ok = bool(picked)
    for case in picked:
        sql = str(case["gold_sql"])
        tenant = str(case["eval_tenant"])
        wrap = run_in_sandbox(
            sql, tenant=tenant, views=False,
            db_path=db_path, tenant_scoped_physicals=tenant_scoped_physicals,
        )
        view = run_in_sandbox(
            sql, tenant=tenant, views=True,
            db_path=db_path, tenant_scoped_physicals=tenant_scoped_physicals,
        )
        frozen = str(case["gold_result_hash"])
        row_ok = (
            wrap["error"] is None
            and view["error"] is None
            and wrap["hash"] == frozen
            and view["hash"] == frozen
        )
        ok &= row_ok
        rows.append({
            "case_id": case.get("case_id"),
            "eval_tenant": tenant,
            # 手写侧到底注入了哪些租户域表：由 W1A 的实现前后差异反证，不自己数。
            "touched_tenant_scoped": bfs.tenant_wrap(sql, tenant) != sql,
            "hash_frozen": frozen,
            "hash_wrap": wrap["hash"],
            "hash_view": view["hash"],
            "rows_wrap": wrap["rows"],
            "rows_view": view["rows"],
            "error_wrap": wrap["error"],
            "error_view": view["error"],
            "frozen_eq_wrap": wrap["hash"] == frozen,
            "wrap_eq_view": wrap["hash"] == view["hash"],
            "ok": row_ok,
        })
    return {
        "required_by": "07 §17.6①",
        "n_selected": len(picked),
        "n_required": n,
        "tenants_covered": sorted({str(r["eval_tenant"]) for r in rows}),
        # 选中数不足同样是失败：说明"含 tenant_scoped 资产的可执行用例"没找够，
        # 而不是"边界一致"。空测试必须表现为红，不能表现为绿。
        "selection_complete": len(picked) >= n,
        "rows": rows,
        "ok": ok and len(picked) >= n,
    }


def test_boundary_efficacy(
    *, db_path: str, tenant_scoped_physicals: Mapping[str, str], tenants: Sequence[str]
) -> dict[str, Any]:
    """①的前置探针：租户边界**必须真的在过滤**（否则 ① 的三个相等是空转出来的）。

    只看视图边界不够 —— 还要证明"逐租户计数之和 == 全量计数"，即沙箱里的租户键
    被评测租户集合**完整覆盖**。若有行属于未纳入评测的租户，视图会把它们**静默藏起来**，
    于是"跨租户不可见"（N-07）在评测里成立、在生产里不成立。
    """
    out: list[dict[str, Any]] = []
    ok = bool(tenants) and bool(tenant_scoped_physicals)
    baseline = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    try:
        for physical in sorted(tenant_scoped_physicals):
            ident = physical
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", ident):
                raise ValueError(f"资产标识符非法，拒绝拼进 COUNT：{ident!r}")
            total = baseline.execute(f"SELECT COUNT(*) FROM main.{ident}").fetchone()[0]
            per_tenant: dict[str, int] = {}
            for tenant in tenants:
                con = open_sandbox(
                    db_path, tenant_id=tenant, tenant_scoped_physicals=tenant_scoped_physicals
                )
                try:
                    per_tenant[tenant] = con.execute(
                        f"SELECT COUNT(*) FROM {ident}"
                    ).fetchone()[0]
                finally:
                    con.close()
            covered = sum(per_tenant.values())
            row = {
                "asset": physical,
                "unfiltered_rows": total,
                "per_tenant_rows": per_tenant,
                "sum_per_tenant": covered,
                # 视图生效 = 至少一个租户看到的是**严格子集**（全量相同 = 边界没起作用）。
                "filters_something": any(v < total for v in per_tenant.values()),
                "covers_all_rows": covered == total,
            }
            row["ok"] = row["filters_something"] and row["covers_all_rows"]
            ok &= row["ok"]
            out.append(row)
    finally:
        baseline.close()
    return {
        "purpose": "§17.6① 的前置：证明 TEMP VIEW 租户边界确实在过滤，且评测租户集合覆盖全量行",
        "rows": out,
        "ok": ok,
    }


def open_sandbox(
    db_path: str, *, tenant_id: str | None, tenant_scoped_physicals: Mapping[str, str]
) -> sqlite3.Connection:
    """`sqlite_exec.open_sandbox_connection` 的薄封装（保持本文件只依赖一个入口）。"""
    from sqlite_exec import open_sandbox_connection  # 延迟导入：避免与 harness 的初始化顺序纠缠

    return open_sandbox_connection(
        db_path, tenant_id=tenant_id, tenant_scoped_physicals=tenant_scoped_physicals
    )


# ---------------------------------------------------------------------------
# ② 报告器字段白名单静态检查（I-1 的护栏）
# ---------------------------------------------------------------------------

#: "读到了被禁字段"的语法形状。**注释与 docstring 里的提及不算**（禁止性说明必须能写出来）。
_BANNED_READ_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(rf'\[\s*["\']{BANNED_FIELD}["\']\s*\]'),            # payload["…"]
    re.compile(rf'\.get\(\s*["\']{BANNED_FIELD}["\']'),            # payload.get("…")
    re.compile(rf'["\']{BANNED_FIELD}["\']\s*:'),                  # JSON/dict 的键
    re.compile(rf'\b{BANNED_FIELD}\s*='),                          # 关键字实参
)


def _scan_file(path: str) -> list[dict[str, Any]]:
    """扫一个文件，返回**读取形态**的命中（带行号）。"""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    hits: list[dict[str, Any]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # 整行注释：通常是"此处禁止使用"的说明
        for pattern in _BANNED_READ_PATTERNS:
            if pattern.search(line):
                hits.append({
                    "path": path,
                    "line": lineno,
                    "pattern": pattern.pattern,
                    "text": stripped[:160],
                })
                break
    return hits


def scan_field_whitelist(paths: Sequence[str]) -> dict[str, Any]:
    """对给定文件集合执行 ② 的扫描（正对照见 `assert_field_whitelist`）。"""
    hits: list[dict[str, Any]] = []
    scanned: list[str] = []
    for path in paths:
        if os.path.basename(path) in _SCAN_EXCLUDE:
            continue
        scanned.append(path)
        hits.extend(_scan_file(path))
    return {"n_files_scanned": len(scanned), "hits": hits, "ok": not hits}


def assert_field_whitelist(
    *, scan_paths: Sequence[str] | None = None, artifact_paths: Sequence[str] | None = None
) -> dict[str, Any]:
    """§17.6② —— `difficulty_struct_sitelabel` 不得进入任何报告 / 门禁输入。

    三条腿：
    1. **源码腿**：eval 侧生产者与 w6 探针里不得出现该字段的**读取形态**；
    2. **工件腿**：已产出的结果 JSON（= 门禁与报告的实际输入）里不得出现该**键**；
    3. **反向腿**：该字段必须**仍在冻结集里**（它是 I-1 指定的对照字段，不是可清理的垃圾）。

    ⚠️ 带**正对照**（`self_test`）：静态检查最大的失效模式不是误报而是"正则写坏了 → 永远绿"。
    所以每次运行都先拿一段人造的读取语句喂给同一个扫描器，**要求它必须命中**。
    对照失败 ⇒ 本检查判红，而不是判绿 —— 护栏坏了不能被护栏自己掩盖。
    """
    root = _bootstrap.ROOT
    if scan_paths is None:
        eval_dir = os.path.join(root, "eval")
        probe_dir = os.path.join(root, "backend", "reports", "w6")
        scan_paths = sorted(
            os.path.join(eval_dir, f) for f in os.listdir(eval_dir) if f.endswith(".py")
        ) + sorted(
            os.path.join(probe_dir, f) for f in os.listdir(probe_dir) if f.endswith(".py")
        )
    if artifact_paths is None:
        artifact_paths = sorted(
            _collect_artifacts(root)
        )
    source = scan_field_whitelist(scan_paths)
    artifacts = scan_field_whitelist(artifact_paths)

    ctrl = _positive_control()
    dataset_hits = _scan_file(_bootstrap.DATASET_PATH)
    return {
        "required_by": "07 §17.6② / I-1",
        "banned_field": BANNED_FIELD,
        "source": source,
        "artifacts": {**artifacts, "paths": artifact_paths},
        # 反向断言：对照字段必须**还在冻结集里**。它消失 = 有人为了让报告干净删了证据，
        # 那时上面两条腿会漂亮地全绿，而 U-30 的物证没了 —— 所以禁"进报告"必须配"留数据集"。
        "control_field_still_in_dataset": len(dataset_hits),
        "control_field_present": len(dataset_hits) > 0,
        "self_test": ctrl,
        "ok": (
            source["ok"]
            and artifacts["ok"]
            and ctrl["caught"]
            and len(dataset_hits) > 0
        ),
    }


def _collect_artifacts(root: str) -> list[str]:
    """门禁与报告的**实际输入**：`eval/results*.json` + `backend/reports/w6/*.json`。

    ⚠️ 刻意**不含** W1A 的内容资产（`dataset_v1_frozen.json` / `gold_query_seed_v1.json`
    / `red_team_cases_v1.json` / `MANIFEST_v1.json`）：§17.6② 禁的是"进入报告与统计"，
    对照字段留在冻结集里正是它的定位（I-1："只作对照字段"）。把它们扫进来
    会让这条检查永远红，而"永远红的检查"等于没有检查。
    """
    out: list[str] = []
    eval_dir = os.path.join(root, "eval")
    if os.path.isdir(eval_dir):
        out.extend(
            os.path.join(eval_dir, f) for f in sorted(os.listdir(eval_dir))
            if f.startswith("results") and f.endswith(".json")
        )
    report_dir = os.path.join(root, "backend", "reports", "w6")
    if os.path.isdir(report_dir):
        out.extend(
            os.path.join(report_dir, f) for f in sorted(os.listdir(report_dir))
            if f.endswith(".json")
        )
    return out


def _positive_control() -> dict[str, Any]:
    """人造一次"读取被禁字段"，要求扫描器必须抓到（三种形状各一条）。"""
    sample_dir = os.path.join(_bootstrap.HERE, "__pycache__")  # 可写、已被 git 忽略
    os.makedirs(sample_dir, exist_ok=True)
    path = os.path.join(sample_dir, "_whitelist_positive_control.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            "a = payload" + f'["{BANNED_FIELD}"]\n'
            f"b = payload.get('{BANNED_FIELD}')\n"
            f'c = {{"{BANNED_FIELD}": 1}}\n'
        )
    try:
        res = scan_field_whitelist([path])
    finally:
        os.remove(path)
    return {
        "patterns_expected_hits": 3,
        "patterns_hit": len(res["hits"]),
        "caught": res["ok"] is False and len(res["hits"]) == 3,
        "note": "对照没命中 = 扫描器自身失效，② 不得判绿",
    }


# ---------------------------------------------------------------------------
# ③ 锚点回归：本项目锚点必须 100% 命中；官方锚点只作差异记录
# ---------------------------------------------------------------------------

def test_anchors() -> dict[str, Any]:
    """§17.6③ —— 复算 `layering` 的两组锚点。

    * **本项目锚点**（07 §4.7.2 新立）：任一不符 ⇒ 门禁不通过。不符时 `why` 字段
      给出"它为什么落在该级"的判据（comp1/comp2/others 的构成），一眼能看出是**哪根计数**变了。
    * **官方锚点**：`participates_in_verdict=False` —— 07 §4.7.2 明确降级为差异记录。
      拿它当门禁的后果写在 `layering.run_anchors()` 的 docstring 里：Hard 那条永远红，
      于是有人会把门禁放宽，护栏就是这么失效的。
    * **分歧点**（`DIVERGENCE_*`）：反向断言 —— 采纳口径下它**必须仍是 `extra`**；
      哪天变成 `hard`，说明有人改了 `spider_level`，那必须先改 07 §4.7.2 与 I-1。
    """
    project = []
    for name, sql, expect, why in layering.PROJECT_ANCHORS:
        got = layering.classify_struct(sql)["difficulty_struct"]
        project.append({
            "anchor": name, "expected": expect, "actual": got, "ok": got == expect, "why": why,
        })
    official = []
    for name, sql, expect in layering.OFFICIAL_ANCHORS:
        r = layering.classify_struct(sql)
        official.append({
            "anchor": name,
            "expected": expect,
            "actual": r["difficulty_struct"],
            "match": r["difficulty_struct"] == expect,
        })
    div = layering.classify_struct(layering.DIVERGENCE_SQL)
    divergence = {
        "claimed_by_doc_4_7_2": layering.DIVERGENCE_CLAIMED,
        "actual_adopted": div["difficulty_struct"],
        # 断言的是"仍在分歧"，不是"分歧已修好"：它变了才说明口径被动过。
        "ok": div["difficulty_struct"] == layering.DIVERGENCE_ACTUAL,
        "note": "07 §4.7.2 锚点③ 的括号注称该形状为 hard，采纳口径实算 extra（U-30/U-35 物证）",
    }
    ok = all(p["ok"] for p in project) and divergence["ok"]
    return {
        "required_by": "07 §17.6③",
        "n_project_anchors": len(project),
        "project": project,
        "official": official,
        "official_participates_in_verdict": False,
        "official_mismatch_n": sum(1 for o in official if not o["match"]),
        "divergence": divergence,
        # 07 §4.7.2 说"新立 4 条"，layering.py 实际落了 6 条（hard / extra 各有两个形状）。
        # 差异如实登记，不为了对上文档数字而删锚点。
        "doc_says_n": 4,
        "ok": ok,
    }


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------

def run_all(*, n: int = ANCHOR_CASE_N) -> dict[str, Any]:
    """跑齐 ①②③，返回可直接渲染的报告块。

    `tenant_scoped_physicals` 取自 `Harness`（即语义包 `tenant_scoped=true` 的活跃资产），
    本文件不硬编码第二份租户域清单 —— 清单一旦在这里各写一份，①就变成了
    "评测器自己跟自己对齐"。
    """
    dataset = _bootstrap.load_json(_bootstrap.DATASET_PATH)
    cases = dataset.get("cases") or []
    tenants = sorted({
        str(c["eval_tenant"]) for c in cases if c.get("eval_tenant")
    })

    harness = Harness()
    try:
        tenant_scoped_physicals = dict(harness.tenant_scoped_physicals)
    finally:
        asyncio.run(harness.aclose())
    db_path = _bootstrap.SANDBOX_DB

    t1 = test_tenant_boundary(
        cases=cases, db_path=db_path, tenant_scoped_physicals=tenant_scoped_physicals, n=n
    )
    t1b = test_boundary_efficacy(
        db_path=db_path, tenant_scoped_physicals=tenant_scoped_physicals, tenants=tenants
    )
    t2 = assert_field_whitelist()
    t3 = test_anchors()
    return {
        "invariants_checked": ["I-1", "I-4", "I-5", "I-6", "N-13"],
        "eval_tenants": tenants,
        "tenant_scoped_assets": sorted(tenant_scoped_physicals),
        "test_1_tenant_boundary": t1,
        "test_1b_boundary_efficacy": t1b,
        "test_2_field_whitelist": t2,
        "test_3_anchors": t3,
        "ok": bool(t1["ok"] and t1b["ok"] and t2["ok"] and t3["ok"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="07 §17.6 一致性三测（零 LLM / 零成本）")
    parser.add_argument("--n-cases", type=int, default=ANCHOR_CASE_N, help="① 取几条用例")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    out = run_all(n=args.n_cases)
    if not args.no_write:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)

    print(f"① 租户边界一致性：{'OK' if out['test_1_tenant_boundary']['ok'] else 'FAIL'}"
          f"（{out['test_1_tenant_boundary']['n_selected']}/{ANCHOR_CASE_N} 条，三条链路逐字相等）")
    print(f"① 前置（边界真的在过滤）：{'OK' if out['test_1b_boundary_efficacy']['ok'] else 'FAIL'}"
          f"（{len(out['test_1b_boundary_efficacy']['rows'])} 个租户域资产）")
    t2 = out["test_2_field_whitelist"]
    print(f"② 字段白名单：{'OK' if t2['ok'] else 'FAIL'}"
          f"（源码 {t2['source']['n_files_scanned']} 个文件、"
          f"工件 {t2['artifacts']['n_files_scanned']} 个 JSON，"
          f"对照字段仍在冻结集 {t2['control_field_still_in_dataset']} 处，"
          f"正对照 {'命中' if t2['self_test']['caught'] else '未命中 ← 扫描器失效'}）")
    t3 = out["test_3_anchors"]
    print(f"③ 锚点回归：{'OK' if t3['ok'] else 'FAIL'}"
          f"（本项目 {sum(1 for p in t3['project'] if p['ok'])}/{t3['n_project_anchors']} 命中；"
          f"官方 {t3['official_mismatch_n']} 条不符——按 §4.7.2 只作差异记录，不参与门禁）")
    print("总判定：", "全部不变量一致" if out["ok"] else "存在不变量被破坏（详见 JSON）")
    if not args.no_write:
        print("written:", args.out)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
