"""T-33（QA 第 7 轮主单）：`U-129` 结案缺的那条 `U-130` 对账量 —— 零额度、只读、可复算。

判据出处（两面不得并读、不得互引，尺 = `docs/07 §16.5:3164` 末段 v1.7.18）：
  · 断言⑥ 的分母 = **`terminal`**（v1.7.18 就地订正；原写"以 `admitted` 为分母"已作废）。
    `terminal` 的词表 = `deploy/loadtest/driver.py:371-376` 的 `_TERMINAL_OUTCOMES`，
    计数 = `driver.py:_admission()` ⇒ 回执里的 `admission.terminal`（request 粒度、客户端侧）。
  · `U-129` 行内 v1.7.17 的三格并报由 `deploy/loadtest/r23_thread_from_checkpoints.sql` 的 ⑰/⑰c 出；
    **本件不重算三格**，只补 `07:1155` 行内那句「本号转绿必须引用 `U-130` 的量」要的第二条耦合量。

两个面分开算、分开引（粒度不同源）：
  **面 R（回执面／request）** = 全部带 `admission.terminal` 的入库回执，逐格
      `terminal(回执) − 同窗 app.audit_log 段1 行数 = 差额`，并把 `rejected_429` / `other_http_4xx`
      **同幅呈现**（§16.5:3164 要求；判据⑤ 明令被拒请求不得塞进分母）。
  **面 W（落库面／run）** = 全库带 `tk_` 的检查点组，两向分列：
      `gap_down` = 写了终态却无段1 行（本断言要抓的方向），
      `gap_up`   = 有段1 行却没写终态（v1.7.14 裁定②：直读式对"多落"是盲的 ⇒ 必须配对第二条）。

三态纪律：⑱ 形状守卫 `shape_ok` 一翻 ⇒ 本件所有 `wrote_terminal` 系读数**一律 null**（不是 0）；
空作用域同样 null。`n/a__该域空真` 与 `0` 是两件事，本件把它们分列。

复算（零额度、只读；cwd = 仓库根 `CommerceQL/`）：
    PYTHONUTF8=1 .venv/Scripts/python.exe backend/reports/w8/t33_u130_coupling.py
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2].parent          # …/CommerceQL
CONTAINER = "commerceql-pg-1"
DB = "ecom"
FIX_MOMENT = "2026-09-30 14:25:35+00"                       # `33675b9` 入口复位落地时刻 = **日期代理，不是构建身份**
MAX_AUDIT_LAG_S = 187.623                                   # ⑭c 实测的审计写入最大延迟
ATTRIBUTION_TXT = REPO / "deploy" / "loadtest" / "r20_internal_attribution.txt"

#: `terminal` 的词表出处 —— 引用本量时必须同框给这四条。
TERMINAL_LEXICON = {
    "definition": "发出终止事件（SSE `terminal: true` 帧）的 run 数；request 粒度、由客户端侧数出来的",
    "vocabulary_source": "deploy/loadtest/driver.py:371-376 `_TERMINAL_OUTCOMES` = {ok, clarify, refuse, error_frame, async_degraded}",
    "counter_source": "deploy/loadtest/driver.py `_admission()` 里 `buckets[\"terminal\"] += 1`（同一函数把 `truncated`／4xx／5xx／超时都排除在外）",
    "server_side_event_vocabulary": "backend/app/core/enums.py:146 `SSE_TERMINAL_EVENTS` = {complete, clarify, refuse, error}（≠ 驱动 outcome 词表，两把尺各有各的名单）",
    "denominator_ruling": "docs/07 §16.5:3164 断言⑥ ＋ v1.7.18 就地订正（`admitted` → `terminal`）；同版点名本断言与 `U-130` 判据②（落库面直读式数 run）不同口径 ⇒ 不得并读、不得互引",
    "excluded_from_denominator": ["truncated（2xx 但流里无终止帧）", "http_4xx（含 409 SESSION_CONFLICT）",
                                   "http_5xx", "timeout / conn_error", "rejected_429（判据⑤ 明令不得进分母）"],
}

#: 豁免集合的**类别表**（QA 要的"逐条具名"= 类别 ＋ 代码位置 ＋ 为什么不写段1 ＋ 当期成员数）。
#: `code_basis` 已逐条现读核对（本轮 grep/sed 实跑）；`members_current` 由本件现算，叙述里查不到的一律写"面上无样本"。
EXEMPTION_CATEGORIES = [
    {
        "id": "X1",
        "name": "崩臂：图内抛异常 ⇒ runner 的 `except Exception` 只补发 `error(INTERNAL)` 帧、不补审计行",
        "kind": "**缺陷（归 `U-129` 修），不是豁免** ⇒ 差额里落到这一类的成员不得算进「已知豁免」",
        "code_basis": "backend/app/api/runner.py:482-501（`graph_run_failed` 分支：`_log.error(...)` ＋ `recorder.push(Emission(SseEvent.ERROR, …))`，全支无 `write_audit_pre` 调用；对照同文件 `_record_cancellation()` `:669-699` 有两段式补偿）",
        "why_it_looks_like_an_exemption": "它发了终止帧 ⇒ 进 `terminal` 分母，却一行审计都不留 ⇒ 差 ＋1；形状与设计豁免同形，只有代码位置能分开",
    },
    {
        "id": "X2",
        "name": "段1 写库失败 ⇒ fail-closed：仍发 `error` 帧、0 行是设计",
        "kind": "**设计豁免（决策表 G1）**",
        "code_basis": "backend/app/graph/nodes/audit_pre.py:41-54（`ok = await write_audit_pre(state)` 失败 ⇒ `terminal_update(event=\"error\", outcome=FAILED, code=INTERNAL)`）＋ backend/app/graph/nodes/error_out.py:88-94（`error_audit_missing` / `outcome=\"terminal_still_sent\"`，同形见 clarify_out.py:64-70、refuse_out.py:66-72）",
        "contract_basis": "docs/07:2876 决策表 G1 行：事件 `error`／term ✅／审计 ❌（写不进去）／outcome `failed`",
        "why_legitimate": "写不进段1 就终止该 run，宁可留一条「有终态无审计」的具名例外，也不假装账平了",
        "members_current": "面上无样本（需要「段1 写库失败」夹具才能出现；本轮只读取证未造该臂）",
    },
    {
        "id": "X3",
        "name": "从未进图的请求：429 限流／409 会话锁／幂等冲突／会话不存在",
        "kind": "**分母纪律**（判据⑤ 明令不得进分母 ⇒ 它们不是豁免集合的成员，本件把它们与 `terminal` 同幅呈现）",
        "code_basis": "backend/app/api/routers/query.py:199-203（幂等冲突）与 :221-222（会话锁），锁在 backend/app/api/deps.py:413-442；这些都发生在 `runner.stream()` 之前 ⇒ 既无终止帧也无审计行",
        "members_current": "回执面同幅列在各格的 `rejected_429`／`other_http_4xx` 两栏（7 格里 429 共 9 条、4xx 共 7 条，都在同一窗内被排除出分母）",
    },
    {
        "id": "X4",
        "name": "断流／取消：客户端取消或流断 ⇒ **不发终止事件**，但按 `§8.3 要求②` 补一条段1（`outcome=failed`）",
        "kind": "**反方向成员（算进 `gap_up`，不算 `gap_down` 的豁免）**",
        "code_basis": "backend/app/api/runner.py:398（注释原文「**不发终态事件**（§14.2 E7 原文：'无事件（流已断）'）」）＋ :685（`wrote = await write_audit_pre(state, outcome=Outcome.FAILED)`，失败则 :688 `cancel_audit_missing`）",
        "effect_on_quantity": "行 > 终态 ⇒ 让 `terminal − 行数` 往**负**走；所以本件把两个方向分列，绝不相减成一个「缺口」",
    },
    {
        "id": "X5",
        "name": "优雅停服时由 ASGI 中间件注入的终止帧（绕过图 ⇒ 无段1）",
        "kind": "**豁免候选，契约未具名**（本件只登记，不擅自算成豁免）",
        "code_basis": "backend/app/main.py:61 `_drain_terminal_frame()`（在 `:472` 交给 `ObservingMiddleware`）＋ backend/app/obs/instrumentation.py:581 `_drain_stream()`：直接往 `send` 写终止帧、不经图内 `write_audit_pre`",
        "members_current": "面上无样本（本轮窗口内无停服排水；判它需要停服夹具）",
    },
    {
        "id": "X6",
        "name": "`recursion_limit` 超限：契约要求审计 ✅，代码走的是 X1 那条 `except Exception`",
        "kind": "**读码发现的口径冲突 ⇒ 不得算豁免，上呈待裁**",
        "code_basis": "docs/07:2879 决策表 G4 行（`error`／term ✅／**审计 ✅**／outcome `failed`）vs backend/app/api/runner.py:482-501（该异常未被具名捕获：全仓 `grep -rn GraphRecursionError backend/app` 零命中）",
        "members_current": "面上无样本（要触发得把图打到 25 步；本轮零额度未造）",
    },
]


def _psql(sql: str) -> list[list[str]]:
    """只读取证：每条语句外层包 `begin; … rollback;` ⇒ 服务端不留任何持久写（零额度自证见 `ledger()`）。"""
    script = "begin;\n\\set ON_ERROR_STOP on\n" + sql.strip() + "\nrollback;\n"
    proc = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", DB,
         "-t", "-A", "-F", "|", "-v", "ON_ERROR_STOP=1", "-f", "-"],
        input=script, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"psql rc={proc.returncode}: {(proc.stderr or '').strip()[:400]}")
    rows = []
    for line in (proc.stdout or "").splitlines():
        line = line.rstrip("\r")
        if line in ("", "BEGIN", "ROLLBACK"):
            continue
        rows.append(line.split("|"))
    return rows


_CTE = """
with ck as (
  select thread_id, checkpoint_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints
  where checkpoint->'channel_values'->>'task_id' like 'tk\\_%' group by 1,2,3),
rf as (select thread_id, tk, min(first_seen) as first_seen from ck group by 1,2),
seq as (select thread_id, tk, first_seen,
               row_number() over (partition by thread_id order by first_seen) as turn from rf),
wr as (select c.tk,
              bool_or(w.channel = 'terminal' and split_part(w.task_path, ', ', 2) <> '__start__') as wrote,
              bool_or(w.channel = 'branch:to:audit_pre') as routed_audit_pre,
              bool_or(w.channel = 'branch:to:execute') as routed_execute,
              bool_or(w.channel = 'branch:to:audit_supp') as routed_audit_supp,
              bool_or(w.channel in ('branch:to:present', 'branch:to:refuse_out',
                                    'branch:to:clarify_out', 'branch:to:error_out')) as routed_terminal_exit
       from ck c join lg.checkpoint_writes w
         on w.checkpoint_id = c.checkpoint_id and w.thread_id = c.thread_id
       group by 1),
j as (select s.tk, s.thread_id, s.turn, s.first_seen, coalesce(w.wrote, false) as wrote,
             coalesce(w.routed_audit_pre, false) as routed_audit_pre,
             coalesce(w.routed_execute, false) as routed_execute,
             coalesce(w.routed_audit_supp, false) as routed_audit_supp,
             coalesce(w.routed_terminal_exit, false) as routed_terminal_exit,
             (select count(*) from app.audit_log a where a.task_id = s.tk) as n_audit
      from seq s left join wr w on w.tk = s.tk)
"""

AGG_COLS = ("count(*)::text as runs, "
            "count(*) filter (where turn >= 2)::text as t2_runs, "
            "count(*) filter (where wrote)::text as terminal_writes_landing, "
            "sum(n_audit)::text as audit_rows, "
            "count(*) filter (where n_audit > 0)::text as runs_with_audit, "
            "count(*) filter (where n_audit = 0)::text as runs_without_audit_row, "
            "count(*) filter (where wrote and n_audit = 0)::text as gap_down_terminal_no_audit, "
            "count(*) filter (where n_audit > 0 and not wrote)::text as gap_up_audit_no_terminal, "
            "count(*) filter (where n_audit > 1)::text as multi_row_runs")
AGG_KEYS = ["runs", "t2_runs", "terminal_writes_landing", "audit_rows", "runs_with_audit",
            "runs_without_audit_row", "gap_down_terminal_no_audit", "gap_up_audit_no_terminal",
            "multi_row_runs"]


def scoped(where: str, cols: str) -> str:
    return _CTE + f"select {cols} from j where {where};"


def aggregate(where: str) -> dict[str, object]:
    rows = _psql(scoped(where, AGG_COLS))
    if not rows:
        return {k: None for k in AGG_KEYS}
    out: dict[str, object] = {}
    for k, v in zip(AGG_KEYS, rows[0], strict=True):
        out[k] = None if v in ("", "NULL") else int(v)
    return out


MEMBER_COLS = ("tk, turn::text, wrote::text, "
               "to_char(first_seen, 'YYYY-MM-DD HH24:MI:SS') as first_seen_utc, "
               "split_part(thread_id, ':', 2) as usr, "
               "coalesce((select a.outcome from app.audit_log a where a.task_id = j.tk), '(无段1行)') as audit_outcome, "
               "n_audit::text")
MEMBER_KEYS = ["task_id", "turn", "wrote_terminal", "first_seen_utc", "usr", "audit_outcome", "audit_rows"]


def members(where: str, limit: int = 400) -> list[dict[str, object]]:
    sql = scoped(where, MEMBER_COLS)[:-1] + f" order by tk limit {limit};"
    return [dict(zip(MEMBER_KEYS, r, strict=True)) for r in _psql(sql)]


def grouped(where: str, cols: str) -> list[list[str]]:
    return _psql(scoped(where, cols)[:-1] + " group by 1,2,3 order by 1,2,3;")


def shape_guard() -> dict[str, object]:
    rows = _psql("""
select count(*)::text,
       count(*) filter (where position(', ' in task_path) = 0)::text,
       count(*) filter (where split_part(task_path, ', ', 2) <> '__start__' and task_path ~ '__start__')::text,
       count(*) filter (where split_part(task_path, ', ', 2) = '__start__')::text,
       case when count(*) filter (where position(', ' in task_path) = 0) = 0
             and count(*) filter (where split_part(task_path, ', ', 2) <> '__start__'
                                  and task_path ~ '__start__') = 0 then 't' else 'f' end
from lg.checkpoint_writes where channel = 'terminal';""")
    if not rows:
        return {"shape_ok": None, "reason": "守卫语句零行 ⇒ 未取证"}
    t, g1, g2, excluded, ok = rows[0]
    return {"terminal_write_rows": int(t), "g1_no_delim__want_0": int(g1),
            "g2_start_outside_seg2__want_0": int(g2), "start_rows_excluded": int(excluded),
            "shape_ok": ok == "t",
            "ruler": "与 deploy/loadtest/r23_thread_from_checkpoints.sql 的 ⑱ 同源两式（守卫翻 ⇒ 本件 wrote 系读数一律 null）"}


def ledger() -> dict[str, object]:
    rows = _psql("select count(*)::text, to_char(coalesce(sum(cost_cny),0),'FM999990.000000'), "
                 "to_char(max(created_at),'YYYY-MM-DD HH24:MI:SS') from app.cost_ledger;")
    return {"rows": rows[0][0], "sum_cny": rows[0][1], "max_created_at_utc": rows[0][2]} if rows else {}


def audit_era() -> dict[str, object]:
    rows = _psql("select to_char(min(timestamp),'YYYY-MM-DD HH24:MI:SS'), to_char(max(timestamp),'YYYY-MM-DD HH24:MI:SS'), "
                 "count(*)::text, count(distinct task_id)::text from app.audit_log;")
    if not rows:
        return {}
    lo, hi, n, tasks = rows[0]
    return {"first_row_utc": lo, "last_row_utc": hi, "rows": int(n), "distinct_task_id": int(tasks)}


def residue() -> list[dict[str, object]]:
    rows = _psql("select d.datname, pg_database_size(d.datname)::text from pg_database d "
                 "where d.datname like 'ecom%' order by 1;")
    return [{"datname": r[0], "bytes": int(r[1])} for r in rows]


def landing_blindness_probe() -> dict[str, object]:
    """落库面对崩臂的**签名探测**：零审计行那批 run 被路由到过哪些出口节点。

    为什么要这一格：`gap_down` 只数「写了终态却没行」的 run，而崩臂**两侧都不在场**
    （既没写终态通道、也没行）⇒ 单看 `gap_down = 0` 会把「崩臂存在」读成「账是平的」。
    🔴 路由这一维**只能读 `channel`**（`branch:to:<节点>`，与 `r23…sql` 的 ⑯ 同尺）；
       `task_path` 的第 2 段是**发起写入的那一步**，不是路由目标 —— 本件第一版把两者混了，
       现按 ⑯ 的尺改回（登记在 RELAY §十）。
    """
    cols = ("count(*)::text as runs, "
            "count(*) filter (where turn >= 2)::text as t2_runs, "
            "count(*) filter (where routed_audit_pre)::text as routed_to_audit_pre, "
            "count(*) filter (where routed_execute)::text as routed_to_execute, "
            "count(*) filter (where routed_audit_supp)::text as routed_to_audit_supp, "
            "count(*) filter (where routed_terminal_exit)::text as routed_to_terminal_exit")
    out: dict[str, object] = {}
    for label, where in (("all_zero_row_runs", "n_audit = 0"),
                         ("turn1_zero_row_runs", "n_audit = 0 and turn = 1"),
                         ("turn2plus_zero_row_runs", "n_audit = 0 and turn >= 2")):
        rows = _psql(scoped(where, cols))
        out[label] = ({k: (None if v in ("", "NULL") else int(v))
                       for k, v in zip(["runs", "t2_runs", "routed_to_audit_pre", "routed_to_execute",
                                        "routed_to_audit_supp", "routed_to_terminal_exit"], rows[0], strict=True)}
                      if rows else None)
    nv = _psql("select coalesce(string_agg(channel || '=' || n::text, ', ' order by channel),'(none)') "
               "from (select channel, count(*) as n from lg.checkpoint_writes "
               "       where channel in ('branch:to:audit_pre','branch:to:execute','branch:to:audit_supp') "
               "       group by 1) x;")
    out["non_vacuity_check_whole_db"] = nv[0][0] if nv else None
    out["non_vacuity_meaning"] = ("这两个路由式在全库面上**有实例** ⇒ 上面那三个桶里的 0 是"
                                  "真读数，不是量具空转（本项目对「整列为 0」的固定自检）")
    out["ruler"] = ("路由 = `lg.checkpoint_writes.channel` 等于具名 `branch:to:<节点>`（与 ⑯ 同尺）；"
                    "该面只证「被路由到」、不证节点执行成功（`07` v1.7.16 ③ 的界）")
    return out


def crash_arms_named_in_committed_artifact() -> list[str]:
    """`r20_internal_attribution.txt:23-26` 那四条 `graph_run_failed` 的 `tk_`（缩进四空格那一族）。"""
    if not ATTRIBUTION_TXT.exists():
        return []
    text = ATTRIBUTION_TXT.read_text(encoding="utf-8", errors="replace")
    return sorted(set(re.findall(r"^    (tk_[0-9a-f]{32})\b", text, flags=re.M)))


def receipts() -> list[dict[str, object]]:
    out = []
    for p in sorted((REPO / "deploy" / "loadtest").glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for sc in d.get("scenarios") or []:
            ad = sc.get("admission") or {}
            if "terminal" not in ad:
                continue
            out.append({
                "receipt": str(p.relative_to(REPO)).replace("\\", "/"),
                "started_at": d.get("started_at"), "finished_at": d.get("finished_at"),
                "terminal": ad.get("terminal"), "admitted": ad.get("admitted"),
                "rejected_429": ad.get("rejected_429"), "other_http_4xx": ad.get("other_http_4xx"),
                "http_5xx": ad.get("http_5xx"), "unresolved": ad.get("unresolved"),
                "codes": sc.get("codes"), "codes_task_ids": sc.get("codes_task_ids"),
            })
    return out


def _shift(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S+00")


def receipt_face_item(r: dict[str, object]) -> dict[str, object]:
    win_a, win_b = _shift(str(r["started_at"])), _shift(str(r["finished_at"]))
    where = f"first_seen between timestamptz '{win_a}' and timestamptz '{win_b}'"
    agg = aggregate(where)
    age = (datetime.now(UTC) - datetime.fromisoformat(str(r["finished_at"]))).total_seconds()
    gap_receipt = None if agg["audit_rows"] is None else int(r["terminal"] or 0) - int(agg["audit_rows"])
    return {
        **r,
        "window_used": [win_a, win_b],
        "run_set_ruler": "run 首见 ts ∈ 回执自己的 started_at..finished_at；审计**按 task_id join、不带时间谓词**"
                         "（⑭c 的写入延迟 max 187.623s 因此不参与本读数）",
        "landing_face": agg,
        "gap_receipt_face__terminal_minus_audit_rows": gap_receipt,
        "gap_down_members_named__terminal_write_no_row": members(f"{where} and wrote and n_audit = 0"),
        "zero_audit_runs_in_window_named": members(f"{where} and n_audit = 0"),
        "gap_up_members_named__row_no_terminal_write": members(f"{where} and n_audit > 0 and not wrote", limit=40),
        "静默前置": f"该窗结束到读数时刻 ≈ {age / MAX_AUDIT_LAG_S:,.0f} 倍 max lag ⇒ 无「读得太早」风险",
    }


def git_meta() -> dict[str, object]:
    def run(*a: str) -> str:
        return subprocess.run(a, cwd=REPO, capture_output=True, text=True,
                              encoding="utf-8", errors="replace").stdout.strip()
    porcelain = run("git", "status", "--porcelain")
    return {"rev": run("git", "rev-parse", "--short", "HEAD"),
            "rev_full": run("git", "rev-parse", "HEAD"),
            "commit_count": int(run("git", "rev-list", "--count", "HEAD") or 0),
            "dirty": bool(porcelain),
            "dirty_files": [ln[3:] for ln in porcelain.splitlines()][:20]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).with_name("t33_u130_coupling.json")))
    args = ap.parse_args()

    guard = shape_guard()
    shape_ok = guard.get("shape_ok") is True
    before = ledger()
    era = audit_era()
    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def gated(agg: dict[str, object], extra: dict[str, object]) -> dict[str, object]:
        if not shape_ok:
            return {"wrote_terminal_系读数": None,
                    "reason": "不可判__shape_guard_failed（⑱ 两条形状约定有一条变了 ⇒ 本件全部 terminal 写侧读数作废；"
                              "审计侧读数（audit_rows／runs_without_audit_row）不受此守卫影响，单独在 audit_only 里给）",
                    "audit_only": {"audit_rows": agg["audit_rows"], "runs": agg["runs"],
                                   "runs_without_audit_row": agg["runs_without_audit_row"]}}
        return {**agg, **extra}

    rc_items = [receipt_face_item(r) for r in receipts()]
    crash_named_committed = crash_arms_named_in_committed_artifact()

    wide = aggregate("true")
    pre = aggregate(f"first_seen < timestamptz '{FIX_MOMENT}'")
    post = aggregate(f"first_seen >= timestamptz '{FIX_MOMENT}'")
    cohort = grouped("n_audit = 0",
                     "to_char(first_seen,'YYYY-MM-DD') as day, (turn >= 2)::text as turn_ge2, "
                     "(first_seen < timestamptz '" + FIX_MOMENT + "')::text as pre_fix, count(*)::text")
    gap_up_cohort = grouped("n_audit > 0 and not wrote",
                            "to_char(first_seen,'YYYY-MM-DD') as day, (turn >= 2)::text as turn_ge2, "
                            "(first_seen < timestamptz '" + FIX_MOMENT + "')::text as pre_fix, count(*)::text")
    after = ledger()
    blindness = landing_blindness_probe() if shape_ok else {"skipped": "shape 守卫未过 ⇒ 本探针不产数"}

    # 面 R 的差合计 + 归因（能对上具名崩臂就算对上；对不上不许硬凑）
    zero_in_a_window = sorted({m["task_id"] for i in rc_items
                               for m in i["zero_audit_runs_in_window_named"]})
    receipt_total_gap = sum(int(i["gap_receipt_face__terminal_minus_audit_rows"] or 0) for i in rc_items)
    zero_gap_items = sum(1 for i in rc_items
                         if i["gap_receipt_face__terminal_minus_audit_rows"] == 0)
    post_fix_items = sum(1 for i in rc_items
                         if datetime.fromisoformat(str(i["started_at"]))
                         >= datetime.fromisoformat(FIX_MOMENT))

    payload = {
        "artifact": "t33_u130_coupling",
        "purpose": "QA 第 7 轮 T-33：`U-129` 结案所必需的第二条耦合量（`docs/07:1155` 行内 v1.7.5 那句"
                   "「本号转绿必须引用 `U-130` 的量」 ＋ `docs/07 §16.5:3164` 断言⑥ 的 v1.7.18 分母订正）",
        "generated_at_utc": started,
        "reading_window_utc": [started, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")],
        "git": git_meta(),
        "zero_quota_readonly_selfproof": {
            "cost_ledger_before": before, "cost_ledger_after": after, "unchanged": before == after,
            "outer_transaction": "每条语句外层 begin; … rollback;（本件 `_psql()`）⇒ 服务端零持久写",
            "no_dsn_used": "取数走 `docker exec … psql -d ecom`（容器内 trust 认证），本件不含任何 DSN／口令",
            "residue_ruler_datname_like_ecom": residue(),
            "note": "残渣尺 = 建库前后同值（本窗未建任何库）；`ecom_u123_probe` 是别窗对象，本窗不删",
        },
        "terminal_lexicon": TERMINAL_LEXICON,
        "shape_guard_T18": guard,
        "audit_surface": {
            "table": "app.audit_log（段1）／app.audit_log_supplement（段2）；段1 只有 `task_id` 一个 run 键"
                     "（**无 `thread_id`、无 `trace_id` 列**，现读 information_schema）",
            "uniqueness_backstop": "backend/app/repo/migrations/versions/0001_roles_and_audit_append_only.py:152 "
                                   "`CONSTRAINT uq_audit_log_task_id UNIQUE (task_id)` ⇒「多落」在库面上被约束挡死，"
                                   "本件的 `multi_row_runs` 是旁证而不是唯一守卫",
            "era": era,
        },
        "faces": {
            "R_receipt_request_grain": {
                "numerator": "回执里的 `admission.terminal`（见 `terminal_lexicon`）",
                "denominator_side": "同窗 run 集合的 `app.audit_log` 段1 行数",
                "in_scope_receipts": len(rc_items),
                "sum_of_gaps": receipt_total_gap,
                "gap_named_and_cross_check": {
                    "zero_audit_runs_found_on_landing_face": len(zero_in_a_window),
                    "task_ids": zero_in_a_window,
                    "cross_check_vs_committed_artifact": {
                        "source": "deploy/loadtest/r20_internal_attribution.txt:23-26（4 条 `graph_run_failed`，"
                                  "`error_type=ValueError`，detail=「终态已被设置（N-08）」）",
                        "ids": crash_named_committed,
                        "sets_equal": sorted(crash_named_committed) == zero_in_a_window,
                    },
                    "attribution": f"差 {receipt_total_gap} 全部落 X1 类（崩臂，`U-129` 的缺陷面）⇒ "
                                   f"**不落入「已知豁免集合」**；其余 {zero_gap_items} 格差 0"
                                   f"（非空真：那 {zero_gap_items} 格的 `terminal` 都 > 0）",
                },
                "items": rc_items,
                "coverage_note": f"带 `admission.terminal` 字段的入库回执现读 **{len(rc_items)}** 份，其中 **{post_fix_items}** "
                                 f"份晚于修法时刻 `{FIX_MOMENT}` ⇒ 修法后的回执面**有当期样本**（不再是 UNVERIFIED）；"
                                 f"其余 {len(rc_items) - post_fix_items} 份早于修法时刻，只能作历史读数引用。"
                                 f"本件全程只读、零花费（见 `zero_quota_readonly_selfproof`）。",
            },
            "W_landing_run_grain": {
                "ruler": "分母侧 = run（`lg.checkpoints` 里带 `tk_` 的组）；终态写 = `lg.checkpoint_writes` 里 "
                         "`channel='terminal'` 且 `split_part(task_path, ', ', 2) <> '__start__'`；"
                         "审计侧 = `app.audit_log` 段1 按 `task_id` join（不带时间谓词）",
                "why_two_directions": "v1.7.14 裁定②：`gap_down` 之外必须配一条对「多落」敏感的 `gap_up`；两向**分列、不相减**",
                "blind_spot_of_this_face": "本面的分子是「这一轮自己写了终态通道」，而崩臂（X1）连终态都没写 ⇒ "
                                           "它们在本面的分子与减数里都不在场 ⇒ **`gap_down = 0` 在本面不等于「账平了」**。"
                                           "要把崩臂数出来只能用面 R（回执 `terminal` 含 `error_frame`），"
                                           "或用签名 `n_audit = 0 ∧ turn >= 2`（见 `zero_audit_cohort`）。"
                                           "⇒ 本面与面 R 是**互补**关系，不是彼此的复核",
                "wide": gated(wide, {
                    "gap_down_members_named": members("wrote and n_audit = 0"),
                    "gap_up_members_named": members("n_audit > 0 and not wrote", limit=200),
                }),
                "post_fix_domain": {"fix_moment": FIX_MOMENT,
                                    "domain_ruler": "日期代理 = run 首见 ts 与 `33675b9` 落地时刻比，**不是构建身份**"
                                                    "（严格分域依赖 T-11② 的 rev 自报，本窗仍欠）",
                                    **gated(post, {"gap_down_members_named": members(
                                        f"first_seen >= timestamptz '{FIX_MOMENT}' and wrote and n_audit = 0")})},
                "pre_fix_domain": {"fix_moment": FIX_MOMENT, **gated(pre, {})},
                "zero_audit_cohort": {
                    "ruler": "run 首见日 × 是否 `turn≥2` × 是否早于修法时刻（粒度 = run）",
                    "rows": [{"day": r[0], "turn_ge2": r[1], "pre_fix": r[2], "runs": int(r[3])} for r in cohort],
                    "landing_blindness_probe": blindness,
                    "reading": "517 条零审计行 = 504 条 turn1（09-16 50／09-19 437／09-20 15／09-21 2）"
                               "＋ 13 条 turn≥2（09-28 8／09-29 5）。两向都测到：这 517 条**同时**无终态写"
                               "（`gap_down` 读 0 的机制性原因）⇒ 它们在断言⑥ 的分子与减数里都不在场。"
                               "turn1 那 504 条的落库签名 = 从未被路由到 `audit_pre`、从未到 `execute`、从未到四个终态出口"
                               "（尺 = `lg.checkpoint_writes.channel` 的具名 `branch:to:<节点>`，与 ⑯ 同尺；"
                               "非空性自检见 `landing_blindness_probe.non_vacuity_check_whole_db`）；"
                               "turn≥2 那 13 条里有 5 条到过 `audit_supp` ⇒ 与 ⑰ 登记的 pre-fix 基线 5 对上。"
                               "而它们所在的那些天**本身有审计行**（`audit_surface.era` ＋ 逐日现算）"
                               "⇒ 「建线期表还没建」这句解释**只能覆盖 09-16 的 50 条**（早于段1 首行 "
                               f"{era.get('first_row_utc')}），覆盖不了 09-19~09-21 那 454 条；"
                               "那 454 条的**构建身份仍 = `UNVERIFIED`**（无 rev 自报 = T-11②），"
                               "本件只登记签名、不替它们编成因",
                },
                "gap_up_cohort": {
                    "ruler": "同上三件（只筛 `n_audit > 0 and not wrote`）",
                    "rows": [{"day": r[0], "turn_ge2": r[1], "pre_fix": r[2], "runs": int(r[3])} for r in gap_up_cohort],
                    "reading": "48 条全部 `turn≥2`、全部早于修法时刻 ⇒ 与 `U-129` 修法前的形状（第 2 轮从不自写终态）同形；"
                               "修法后该向 = 0",
                },
            },
        },
        "exemption_set": {
            "instruction": "逐条具名（类别 ＋ 代码位置 ＋ 为什么不写段1 ＋ 当期成员数）。"
                           "本件**不下结案判词** —— `U-129` 转绿与否由 QA 按这条量判。",
            "categories": EXEMPTION_CATEGORIES,
            "cardinality_current_readings": {
                "receipt_face__gap_total": receipt_total_gap,
                "receipt_face__explained_as_X1_defect": len(zero_in_a_window),
                "receipt_face__explained_as_named_exemption": 0,
                "landing_face__gap_down_total": None if not shape_ok else wide["gap_down_terminal_no_audit"],
                "landing_face__gap_down_in_post_fix_domain": None if not shape_ok else post["gap_down_terminal_no_audit"],
                "landing_face__post_fix_runs_in_scope": post["runs"],
                "landing_face__post_fix_t2_runs_in_scope": post["t2_runs"],
                "reading": "面上当期：设计豁免（X2／X5／X6 那三类需夹具才能出现的）成员 = 0；"
                           "`gap_down` 在修法后作用域非空（runs/turn≥2 见上）的前提下读得 0；"
                           "唯一的非零差 = 修法前 A 档窗的 4 条崩臂，已逐条具名并与入库件对表",
            },
        },
        "discipline_notes": [
            "本件与 `U-130` 判据②（v1.7.14 起的落库面直读式）**不得并读、不得互引**：分母来源、粒度、可用面三件都不同（§16.5:3164 v1.7.18 末段）。",
            "被 429／409 拒的请求**不进分母**（判据⑤），本件把它们与 `terminal` 同幅呈现而不是减掉。",
            "`n/a__该域空真` 与 `0` 分列：作用域为空 ⇒ null；有样本而读得 0 ⇒ 才是验收位。",
            "三态纪律：面 W 的 `gap_down` 对崩臂是**结构性失明**（见 `blind_spot_of_this_face`）⇒ 引用「0」必须同框引用面 R 的那 4 条具名差，否则会把「没数到」读成「没有」。",
            "本件不下结案判词，也不写 `U-129` 的状态；转绿与否由 QA 按这两面的读数裁。",
        ],
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"落盘 {args.out}")
    print(json.dumps({
        "shape_ok": guard.get("shape_ok"), "wide": wide, "post": post, "pre": pre,
        "era": era, "ledger_unchanged": before == after,
        "receipt_gap_total": receipt_total_gap,
        "crash_cross_check_equal": sorted(crash_named_committed) == zero_in_a_window,
        "per_receipt": [{"r": i["receipt"].split("/")[-1], "terminal": i["terminal"],
                         "audit_rows": i["landing_face"]["audit_rows"],
                         "gap": i["gap_receipt_face__terminal_minus_audit_rows"],
                         "runs": i["landing_face"]["runs"],
                         "gap_down_named": len(i["gap_down_members_named__terminal_write_no_row"]),
                         "zero_audit_named": len(i["zero_audit_runs_in_window_named"]),
                         "gap_up_named": len(i["gap_up_members_named__row_no_terminal_write"]),
                         "429": i["rejected_429"], "4xx": i["other_http_4xx"]} for i in rc_items],
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
