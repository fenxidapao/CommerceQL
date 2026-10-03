"""T-27 · 把 T-23 的反证夹具接成**可重复门禁**（一次性容器，零 LLM / 零额度）。

要守的东西（不是"再跑一遍探针"）
--------------------------------------------------------------------------
T-23 的结论是"⑱ 的 `shape_ok` 真的进了 ⑰/⑰c 的判定量"。那条结论当时**只由一次手工反证支撑**
（容器 `w8-t23-neg`，2026-10-02 20:1x）⇒ 一旦有人把 verdict 的第一支改坏、或把 `shape` CTE 的连接
摘掉，**没有任何器件会红**。本件把那次手工反证固化成机器可重复的两件事：

1. **假绿可复现**：pre-fix 对照件（`backend/reports/w8/t23_prefix_control.sql` = rev `2ae0b43`
   的 ⑰ 逐字抽取）在同一份注入数据上给出 `非空真达成`；
2. **新版必降级**：当前版 `r23_thread_from_checkpoints.sql` 的 ⑰/⑰c/⑱ 在**同一份**注入数据上
   给出 `不可判__shape_guard_failed`（⑰c 是**逐行**都要，且必须**有行** —— 0 行的"通过"不算通过）。

两条同时成立才叫"守卫接成了否决位"；只成立第 2 条 = 可能根本没打中靶子（本项目登记过的形状）。

跑法（🔴 必须指向**一次性库**；库名等于 `ecom` 直接拒，见 `_open()`）
--------------------------------------------------------------------------
    COMMERCEQL_NEGFIX_DSN='postgresql://postgres@127.0.0.1:55441/ecom_neg' \
    PYTHONUTF8=1 .venv/Scripts/python.exe deploy/loadtest/t23_negative_gate.py

本机起一次性容器的命令在 `backend/reports/w8/t23_negative_fixture.sql` 的文件头（用完即删容器，
夹具与对照件本身入库留证）。CI 的挂法见 `.github/workflows/ci.yml` 的 `t23-shape-guard-gate` job。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "eval"))

from pg_guard import redact_dsn, safe_error_text  # noqa: E402

DSN_ENV = "COMMERCEQL_NEGFIX_DSN"
#: 🔴 本件会在目标库上 `create schema` / `drop table` / `insert` ⇒ 共享实例名一律拒绝。
FORBIDDEN_DBNAMES = frozenset({"ecom"})
FIXTURE = REPO / "backend" / "reports" / "w8" / "t23_negative_fixture.sql"
CONTROL = REPO / "backend" / "reports" / "w8" / "t23_prefix_control.sql"
R23 = REPO / "deploy" / "loadtest" / "r23_thread_from_checkpoints.sql"
RECEIPT = REPO / "backend" / "reports" / "w8" / "t23_negative_gate_receipt.json"

#: 标记一律带 `select '` 前缀：裸格子号在注释头/对照件说明里也会出现在同一文件内
#: （实测：`t23_prefix_control.sql` 的注释头让裸标记命中 2 行 ⇒ grab 直接拒绝，这是设计）。
MARK_17 = "select '" + "⑰ U-129"
MARK_17C = "select '" + "⑰c 分域并报"
MARK_18 = "select '" + "⑱ 形状守卫（排除式的正当性前提）"
MARK_FIXTURE = "select 'fixture_g1_rows__want_1"
CONTROL_REV = "2ae0b43"

#: 夹具与格⑰都在**这个窗口**里取样：夹具两条 run 的 ts 是 2026-09-20 / 2026-10-01，
#: 全放行窗口 ＋ `upref='%'`（夹具的 user 段是 `u_z01`）⇒ 不因取样条件漏掉而被误判成"没打中靶子"。
VARS = {"win_a": "2020-01-01 00:00:00+00", "win_b": "2120-01-01 00:00:00+00", "upref": "%"}

SHAPE_UNJUDGED = "不可判__shape_guard_failed"
PREFIX_FALSE_GREEN = "非空真达成"


# ----------------------------------------------------------------------------
# 抽取：与夹具文件头那条复算规则**逐字同源**（回溯到最近的 `with ` 行、前进到 `;` 行）
# ----------------------------------------------------------------------------
def grab(text: str, marker: str, *, start_at_marker: bool = False) -> str:
    lines = text.split("\n")
    idx = [k for k, line in enumerate(lines) if marker in line]
    if not idx:
        raise SystemExit(f"🔴 标记 {marker!r} 在件里找不到 ⇒ 抽取失败，别把'没抽到'读成'守卫没问题'")
    if len(idx) > 1:
        raise SystemExit(f"🔴 标记 {marker!r} 命中 {len(idx)} 行（应唯一）⇒ 先消歧再跑本件")
    i = idx[0]
    a = i
    if not start_at_marker:
        while not lines[a].lstrip().startswith("with "):
            a -= 1
    b = i
    while not lines[b].rstrip().endswith(";"):
        b += 1
    return "\n".join(lines[a : b + 1])


def split_statements(text: str) -> list[str]:
    """按"整行以 `;` 结尾"切分夹具（夹具里没有串内分号，故不写解析器、不猜）。"""
    out: list[str] = []
    buf: list[str] = []
    for line in text.split("\n"):
        if not line.strip().startswith("--") and not line.strip():
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            out.append("\n".join(buf))
            buf = []
    if buf:
        raise SystemExit("🔴 夹具末尾有未收口的语句 ⇒ 切分不可信，别硬跑")
    return out


def bind(sql: str) -> tuple[str, dict[str, str] | None]:
    """psql 的 `:'var'` 插值 → psycopg 命名参数。

    ⚠️ 顺序是刻意的：**先把字面 `%` 翻倍**（件里有 `like 'tk_%'`），再插 `%(name)s` 标记 ——
    反了会把标记自己吃掉。没有变量时原样返回（不传参 ⇒ psycopg 不解释 `%`）。
    """
    if ":'win_a'" not in sql and ":'upref'" not in sql:
        return sql, None
    body = sql.replace("%", "%%")
    for name in VARS:
        body = body.replace(f":'{name}'", f"%({name})s")
    return body, dict(VARS)


def run_rows(conn: psycopg.Connection, sql: str) -> list[dict[str, Any]]:
    body, params = bind(sql)
    with conn.cursor() as cur:
        cur.execute(body, params)
        if cur.description is None:
            return []
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


# ----------------------------------------------------------------------------
# 目标库必须是"一次性的"
# ----------------------------------------------------------------------------
def _open() -> psycopg.Connection:
    raw = os.environ.get(DSN_ENV, "")
    if not raw:
        raise SystemExit(
            f"🔴 未设 {DSN_ENV} ⇒ 不跑。本件会 create schema / drop table / insert，"
            "指向哪个库必须是显式的（缺 env ≠ 回落到任何默认）。"
        )
    conn = psycopg.connect(raw, autocommit=True, connect_timeout=8)
    try:
        dbname = conn.info.dbname or ""
        if dbname in FORBIDDEN_DBNAMES:
            conn.close()
            raise SystemExit(
                f"🔴 目标库名 = {dbname!r}（共享实例名）⇒ 拒跑。"
                "本夹具的 DROP/CREATE 会把别人的装载清掉（U-114）。"
            )
        print(f"目标 = {redact_dsn(raw)}（库名 {dbname}）")
    except psycopg.Error as exc:
        raise SystemExit(f"🔴 连不上：{safe_error_text(exc)}") from None
    return conn


def _body_of(text: str) -> str:
    """去掉注释头，取正文 —— 从第一条 `with ` 起（不数头行数：头一改就错位，那是假"不一致"）。

    ⚠️ 这里踩过的坑值得留一行：`text.split("\n", 14)[1]` **不是**"前 14 行之后的全部内容"，
    `maxsplit` 的剩余部分在**最后一个元素**（[14]），[1] 只是第二行 ⇒ 对照件会被读成两字符的
    `--`，于是 git 校验永远"不一致"。按形状取，不按偏移取。
    """
    lines = text.split("\n")
    for k, line in enumerate(lines):
        if line.lstrip().startswith("with "):
            return "\n".join(lines[k:]).strip()
    raise SystemExit("🔴 对照件里找不到 `with ` 起始行 ⇒ 文件被改坏或抽取规则变了")


def verify_control(conn: psycopg.Connection) -> dict[str, str]:
    """对照件与 `2ae0b43` 的抽取是否逐字相同 —— **有历史才验**，无历史记 UNVERIFIED（不红、也不装成已验）。"""
    try:
        pre = subprocess.run(
            ["git", "-C", str(REPO), "show", f"{CONTROL_REV}:deploy/loadtest/r23_thread_from_checkpoints.sql"],
            capture_output=True, text=True, encoding="utf-8", timeout=20, check=True,
        ).stdout
    except Exception as exc:
        return {"git_check": "UNVERIFIED", "why": f"{type(exc).__name__}（CI 默认 fetch-depth=1 属预期）"}
    extracted = grab(pre, MARK_17).strip()
    shipped = _body_of(CONTROL.read_text(encoding="utf-8"))
    return {
        "git_check": "一致" if extracted == shipped else f"🔴 不一致（抽 {len(extracted)} 字 vs 件 {len(shipped)} 字）",
        "extracted_chars": str(len(extracted)),
    }


def main() -> int:
    for path in (FIXTURE, CONTROL, R23):
        if not path.exists():
            print(f"🔴 缺件：{path.relative_to(REPO)}", file=sys.stderr)
            return 2

    conn = _open()
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        print(f"[{'ok' if ok else 'FAIL'}] {name} —— {detail}")

    with conn:
        # ① 夹具落地 + 注入自检（这一条不 = 夹具没建起来，而不是"守卫没响"）
        for stmt in split_statements(FIXTURE.read_text(encoding="utf-8")):
            conn.execute(stmt)
        self_rows = run_rows(conn, grab(
            FIXTURE.read_text(encoding="utf-8"), MARK_FIXTURE, start_at_marker=True))
        injected = self_rows[0]["n"] if self_rows else None
        check("夹具注入自检", injected == 1, f"fixture_g1_rows = {injected}（要 1）")

        r23 = R23.read_text(encoding="utf-8")
        # ② ⑱ 守卫位必须自己翻
        g18 = run_rows(conn, grab(r23, MARK_18, start_at_marker=True))[0]
        check("⑱ shape_ok 翻假", g18["shape_ok"] is False,
              f"terminal_rows={g18['terminal_rows']} g1={g18['g1_no_delim__want_0']} "
              f"g2={g18['g2_start_outside_seg2__want_0']} shape_ok={g18['shape_ok']}")

        # ③ 当前版 ⑰：两个 verdict 第一支都要不可判
        g17 = run_rows(conn, grab(r23, MARK_17))[0]
        check("⑰ 新版 ge3 降不可判", str(g17["ge3_verdict"]).startswith(SHAPE_UNJUDGED),
              repr(g17["ge3_verdict"])[:40])
        check("⑰ 新版 ge2 降不可判", str(g17["ge2_verdict"]).startswith(SHAPE_UNJUDGED),
              repr(g17["ge2_verdict"])[:40])

        # ④ 当前版 ⑰c：**逐行**不可判，且**必须有行**
        #   ⚠️ 列名一律取**小写**：件里写的是 `as verdict__T23`，但 PG 对未加引号的标识符做
        #   大小写折叠 ⇒ `cur.description` 给的是 `verdict__t23`。写成大写会 KeyError，
        #   而症状是"门禁自己坏了"，不是"守卫坏了"。
        rows17c = run_rows(conn, grab(r23, MARK_17C))
        bad = [r for r in rows17c if not str(r["verdict__t23"]).startswith(SHAPE_UNJUDGED)]
        check("⑰c 新版有行", len(rows17c) > 0, f"{len(rows17c)} 行（0 行的通过不算通过：没打中靶子）")
        check("⑰c 新版逐行不可判", bool(rows17c) and not bad,
              f"{len(rows17c) - len(bad)}/{len(rows17c)} 行 = 不可判")

        # ⑤ 对照件：同库、同参，只换件版本 ⇒ 必须**复现假绿**
        pre17 = run_rows(conn, grab(CONTROL.read_text(encoding="utf-8"), MARK_17))[0]
        verdict = str(pre17["ge2_verdict"])
        check("⑰ 对照件复现假绿", PREFIX_FALSE_GREEN in verdict and SHAPE_UNJUDGED not in verdict,
              repr(verdict)[:60])

        # ⑥ 对照件的**溯源**：入库件必须真等于 2ae0b43 的抽取（无历史 ⇒ UNVERIFIED，不红也不装成已验）
        gc = verify_control(conn)
        check("对照件 git 溯源", gc.get("git_check") in ("一致", "UNVERIFIED"), str(gc))

    payload = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "control_rev": CONTROL_REV,
        "vars": VARS,
        "checks": checks,
        "passed": all(c["ok"] for c in checks if "ok" in c),
    }
    try:
        rev = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=15, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                                    capture_output=True, text=True, timeout=15, check=True).stdout.strip())
        payload["git_rev"], payload["git_dirty"] = rev or None, dirty
    except Exception as exc:
        payload["git_rev"], payload["git_dirty"] = None, None
        payload["git_rev_error"] = type(exc).__name__
    RECEIPT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"回执：{RECEIPT.relative_to(REPO)}  passed={payload['passed']}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
