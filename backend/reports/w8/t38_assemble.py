"""T-38 主单的**结件装配**：把「一把 c3/n30 当期批」的六条硬要求逐格判一遍，结论必给。

零额度、零出站：只读三样东西 —— ① 盘上的报价与两把回执，② 容器里的构建身份（`attest` 已写好），
③ 共享 `ecom` 的只读 CQ（每支都包在 `begin; … rollback;` 里，服务端零持久写）。

为什么要一件装配而不是散在散文里：派单那六条 (a)…(f) 每一条都是**可判伪**的，
把它们逐格落成 `verdict` ＋ `尺` ＋ `读数`，QA 就能只看这一件判"执行与证据是否一致"，
不用在我的散文里找数。任何一格拿不到读数 ⇒ 写 `UNVERIFIED`，不写"达成"。

口径三件必须同框（本窗自订，起因见 §十六）：
- **准入的分母** = 主批回执 `admission.admitted`，**作废格不进任何分母**（硬要求 a）；
- **样本下限** = `MIN_ADMITTED_FOR_P95`（`driver.py` 现读 = 20），不足则 G-6 只能 `null` ＋ caveat 原文；
- **thread 尺有两把**：回执侧 `thread_depth` 的键是 `(worker, session_id)`，库面的键是 `tenant:user:session`
  ⇒ 两把在本几何下**不等价**（实测 7 vs 3），凡"第 N 轮"的结论只从库面那把取。

复算（cwd = 仓库根）：
    PYTHONUTF8=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w8/t38_assemble.py
产物：同目录 `t38_assembled.json`（除两个时钟派生字段外逐字幂等）。
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
W8 = ROOT / "backend" / "reports" / "w8"
EVID = W8 / "evidence" / "t38"
QUOTE = ROOT / "deploy" / "loadtest" / "t38_c3n30_quote.json"
MAIN = ROOT / "deploy" / "loadtest" / "t38_c3n30_main.json"
VOID = ROOT / "deploy" / "loadtest" / "t38_c3n30_warm.json"
OUT = W8 / "t38_assembled.json"

USER_PREFIX = "u_t38c3"
VOID_TASK = "tk_e52c0019f24d4c09b58facd9e7a0f59f"  # 作废格那一跑，具名剔除
CAP_CNY = 0.25
TERMINAL_KEYS = ("admission", "outcomes", "codes", "codes_task_ids", "thread_depth",
                 "p95_scope", "g6_p95_le_8s", "g6_caveat", "latency_samples_ms",
                 "terminal_provenance", "rejection_headers", "error_messages")


def sh(args: list[str]) -> str:
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit(f"命令失败 rc={p.returncode}: {' '.join(args)}\n{(p.stderr or p.stdout)[-300:]}")
    return (p.stdout or "").strip()


def psql(sql: str) -> str:
    return sh(["docker", "exec", "-i", "commerceql-pg-1", "psql", "-U", "postgres", "-d", "ecom",
               "-q", "-t", "-A", "-c", f"begin; {sql} rollback;"])


def jload(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def harness_row(name: str, which: str) -> list[str]:
    """从归档的 ⑰ 件输出里取以 `name` 开头那一行（`which` = 文件名里要含的子串）。

    ⚠️ 两把窗各一份归档（含作废 / 具名剔作废），**不许**在两份里"取第一条命中"——
    那会让两格读到同一份，正是本窗要防的"同一个数两种作用域"。
    """
    for path in sorted(EVID.glob(f"r23_scope_*{which}*.txt")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(name):
                return [path.name, *line.split("|")[1:]]
    raise SystemExit(f"尺坏：在 {which} 那把归档里找不到 `{name}` 行（不要退回硬抄）")


def spend_window(since_iso: str) -> dict:
    rows, total, lo, hi, tasks, peak = psql(
        f"select count(*), to_char(sum(cost_cny),'FM999990.000000'), min(created_at), max(created_at),"
        f" count(distinct task_id), bool_and(not is_peak) from app.cost_ledger"
        f" where created_at >= '{since_iso}';").split("|")
    grand_rows, grand_sum, grand_max = psql(
        "select count(*), to_char(sum(cost_cny),'FM999990.000000'), max(created_at) "
        "from app.cost_ledger;").split("|")
    return {"since": since_iso, "rows": int(rows), "sum_cny": float(total),
            "first_created_at": lo, "last_created_at": hi, "distinct_task_ids": int(tasks),
            "all_non_peak": peak == "t",
            "ledger_now": {"rows": int(grand_rows), "sum_cny": float(grand_sum),
                           "max_created_at": grand_max}}


def spend_for_tasks(task_ids: list[str]) -> dict:
    """按**主批那 9 个 run 的 `task_id` 具名取台账** ⇒ 分子与分母（`admitted`）严格同面。

    ⚠️ 不用"时间窗减一秒"这种做法：回执的 `finished_at` 只到秒，而末帧调用落在 `04:26:21.407`，
    按秒取整会把这一条切在窗外（T-39 A 撞 H 时就是被这个边界骗过一次）。具名 `task_id` 才稳。
    """
    ids = ",".join(f"'{t}'" for t in task_ids)
    rows, total, distinct, lo, hi = psql(
        f"select count(*), to_char(sum(cost_cny),'FM999990.000000'), count(distinct task_id),"
        f" min(created_at), max(created_at) from app.cost_ledger where task_id in ({ids});").split("|")
    return {"task_ids_given": len(task_ids), "rows": int(rows), "sum_cny": float(total),
            "distinct_task_ids_billed": int(distinct), "first_created_at": lo, "last_created_at": hi}


def main() -> int:
    quote, main_r, void_r = jload(QUOTE), jload(MAIN), jload(VOID)
    scen = main_r["scenarios"][0]
    void_scen = void_r["scenarios"][0]

    quote_commit = sh(["git", "log", "-1", "--format=%H", "--",
                       "deploy/loadtest/t38_c3n30_quote.json"])
    quote_cd = sh(["git", "log", "-1", "--format=%cd", "--date=iso-strict", quote_commit])
    quote_utc = dt.datetime.fromisoformat(quote_cd)
    main_started = dt.datetime.fromisoformat(main_r["started_at"])
    void_started = dt.datetime.fromisoformat(void_r["started_at"])

    admitted = int(scen["admission"]["admitted"])
    terminal = int(scen["admission"]["terminal"])
    floor = int(quote["sample_floor"]["MIN_ADMITTED_FOR_P95"])
    spend = spend_window(quote_utc.astimezone(dt.UTC).isoformat(timespec="microseconds"))
    # 🔴 T-39 B（F4）：旧写法 `spend["sum_cny"] / (admitted + 1)` 的 `+1` 把作废那跑算回了分母，
    # 与同文件 docstring「作废格不进任何分母」直接打架。改法 = 分子也换成**具名 9 个 run** 的花费，
    # 两边同面 ⇒ 单价真叫 `cny_per_admission`；整窗（含作废）那把另起一个名字并报。
    main_only = spend_for_tasks([str(s["task_id"]) for s in (scen.get("latency_samples_ms") or [])])
    unit_measured = round(main_only["sum_cny"] / admitted, 6)
    unit_window_incl_void = round(spend["sum_cny"] / (admitted + int(void_scen["admission"]["admitted"])), 6)

    # 两把 thread 尺里的"回执那把"：U-138 落地后新键 = `worker_session_depth`/`groups`，
    # 旧那份（T-38 当期批）= `thread_depth`/`threads` ⇒ 两种都接住，但**键名与实际读到的那一面**必须同框点名。
    depth_raw = scen.get("worker_session_depth") or scen.get("thread_depth") or {}
    key_in_receipt = ("worker_session_depth" if scen.get("worker_session_depth") else "thread_depth（U-138 改名之前）")
    depth_cell = {
        "groups": depth_raw.get("groups", depth_raw.get("threads")),
        "grouping_key": depth_raw.get("grouping_key", "(worker, session_id)"),
        "depth_hist": depth_raw.get("depth_hist"),
        "key_in_receipt": key_in_receipt,
    }
    if depth_cell["groups"] is None:
        raise SystemExit("尺坏：回执里两把键名都取不到组数（不要退回硬抄 7）")

    agg = main_r["build_identity"]["layer1_2"]["app_tree_aggregate"]
    pre = jload(EVID / "build_identity_pre_run.json")["build_identity"]

    # 库面作用域读数：两把窗（含作废 / 具名剔除作废），thread 尺与审计行覆盖
    def scope(win_a: str, excl_void: bool) -> dict:
        cond = f"user_id = '{USER_PREFIX}' and \"timestamp\" >= '{win_a}'"
        if excl_void:
            cond += f" and task_id <> '{VOID_TASK}'"
        rows, runs = psql(f"select count(*), count(distinct task_id) from app.audit_log where {cond};").split("|")
        threads = psql(
            f"select count(distinct split_part(thread_id,':',1)||':'||split_part(thread_id,':',2)"
            f"||':'||split_part(thread_id,':',3)) from lg.checkpoints ck where exists "
            f"(select 1 from app.audit_log a where a.task_id = ck.checkpoint->'channel_values'->>'task_id'"
            f" and {cond});")
        return {"audit_rows": int(rows), "runs": int(runs), "server_threads": int(threads)}

    out = {
        "artifact": "commerceql.w8.t38_assembled/1",
        "task": "T-38 主单：一把 c=3/n=30 的当期批（U-129 ③ ＋ G-6 P95）",
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "identity": {
            "rev": sh(["git", "rev-parse", "HEAD"]),
            "rev_short": sh(["git", "rev-parse", "--short", "HEAD"]),
            "commit_count": int(sh(["git", "rev-list", "--count", "HEAD"])),
            "dirty": bool(sh(["git", "status", "--porcelain"])),
            "captured_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "口径": "PROMPT §2 ④ 两格并报：本块 = **装配那一刻**的树；两把回执各自另有件内 `git_rev`／`git_dirty`（跑那一刻）",
        },
        "geometry_requested": quote["geometry"],
        "hard_requirements": {
            "a_void_cell": {
                "verdict": "达成" if void_scen["admission"]["admitted"] == 1 else "UNVERIFIED",
                "读数": {"void_admitted": void_scen["admission"]["admitted"],
                         "void_started_at": void_r["started_at"], "void_outcomes": void_scen["outcomes"],
                         "不进分母": f"主批分母 = {admitted}（不含作废格那 1 条具名 task_id）"},
                "尺": "回执 `scenarios[0].admission.admitted` ⟷ 主批窗口的具名剔除（`task_id <> VOID_TASK`）",
                "note_rule": "作废格 `note` 已点名其身份为跑后补打（跑前另有独立取证，见 build_identity_pre_run）",
            },
            "b_quote_before_started_at": {
                "verdict": "达成" if quote_utc < main_started else "🔴 未达成",
                "读数": {"quote_commit": quote_commit[:7], "quote_committer_date": quote_cd,
                         "main_started_at": main_r["started_at"],
                         "delta_s": round((main_started - quote_utc).total_seconds(), 1),
                         "void_started_at": void_r["started_at"],
                         "void_also_after_quote": quote_utc < void_started},
                "尺": "git log -1 --format=%cd --date=iso-strict <报价笔>  ⟷  回执 started_at（两侧都转 UTC 再比）",
                "教训来源": "第 12 轮那次报价笔晚 20 分 10 秒 ⇒ (d) 判未达成；本轮把报价做成**先提交的产物**",
            },
            "c_build_identity": {
                "verdict": "达成（**链一** 容器 ⟷ 工作树字节 ＝ 逐件 18/18 ＋ 聚合容器面 ⟷ 工作树面；"
                           "**链二** 工作树 ⟷ HEAD ＝ 跑前 `git_dirty = false` ＋ 层 3 present。"
                           "🔻 本句原写「三面全量相等 ＋ 逐件 18/18 ＋ 层 3 ＋ 跑前独立一次」，"
                           "『三面』二字按 `U-139` 换代成两链，见本格 `当期性写法`）",
                "读数": {"container": main_r["build_identity"]["container"],
                         "image_id": main_r["build_identity"]["image_id"],
                         "container_created_at": main_r["build_identity"]["container_created_at"],
                         "head_rev_at_attest": main_r["build_identity"]["head_rev_short"],
                         "per_file_same": f"{sum(1 for f in main_r['build_identity']['layer1_2']['files'] if f['verdict'] == 'SAME')}/18",
                         "aggregate_three_way_equal": agg["three_way_equal"],
                         "aggregate_files": f"{agg['files_count_container']}/{agg['files_count_git']}",
                         "layer3": main_r["build_identity"]["layer3_behavior"],
                         "pre_run_attestation": {"attested_at_utc": pre["attested_at_utc"],
                                                 "head_rev_short": pre["head_rev_short"],
                                                 "per_file_same": f"{sum(1 for f in pre['layer1_2']['files'] if f['verdict'] == 'SAME')}/{len(pre['layer1_2']['files'])}",
                                                 "image_id": pre["image_id"]}},
                "尺": "deploy/loadtest/attest_build_identity.py（聚合面 10-06 换代：旧尺容器侧带 `./` 前缀 ⇒ 三列永不相等 = 坏尺，本轮起才有判别力）",
                "当期性写法": "只写**两链**：链一『容器 ⟷ 工作树字节』（这把尺真量到的：逐件 `verdict` ＋ 聚合容器面 ⟷ 工作树面）"
                             "＋ 链二『工作树 ⟷ HEAD』（逐件 `worktree_vs_head_lf` ＋ 跑前 `git_dirty = false`）。"
                             "🔻 本句原命令「只写『逐件 18/18 ＋ 全量 158 件三面相等 ＋ 层 3 符号 present』」——**『三面』二字作废**："
                             "当时那把逐件尺的 git 面走 `_run().strip()`（吃了结尾换行）⇒ 结构上永不等于真 blob ⇒ 那一面从未参与比较"
                             "（`U-139`，10-06 第 18 轮修尺；修后现测 `ratelimit.py` 三把全等、`state.py` 的 `head_blob_lf` 与 "
                             "`git show HEAD:… | md5sum` 逐字符同值、`ast_gate.py` 无命中）。🔴 **数字与读数一律不动**（本格 `读数` 那八键照旧），"
                             "改的只是「这句能支撑什么结论」。🚫 仍不写『本轮重建出新镜像』：`image_id` 那格 = 镜像 `commerceql-api` "
                             "`Created = 2026-10-05T15:19:25Z`，`container_created_at` 那格 = **容器** `2026-10-05T15:19:26Z`"
                             "（两个面、只差一秒，不可互换）⇒ 都不是本轮新建。",
            },
            "d_latency_samples": {
                "verdict": "达成" if len(scen.get("latency_samples_ms") or []) == admitted else "🔴 未达成",
                "读数": {"n_samples": len(scen.get("latency_samples_ms") or []),
                         "keys_per_sample": sorted((scen["latency_samples_ms"] or [{}])[0]),
                         "admitted": admitted},
                "尺": "逐样本数 ⟷ `admission.admitted` 必须相等；样本只装准入、升序、不含题面（N-11）",
                "来源": "T-36 E 那件（driver.py `latency_samples_ms`）第一次真用上",
            },
            "e_reading_surface": {k: scen.get(k) for k in TERMINAL_KEYS},
            "e_键名漂移": ("本格的 `thread_depth` 是 T-38 那份回执的原样搬运；U-138 落地后**新回执**给的是 "
                        "`worker_session_depth`（键语义自报、且显式声明不是服务端 thread）⇒ 读新批时把这一格换成 `worker_session_depth`，"
                        "契约测试 = `backend/tests/contract/test_loadtest_thread_key_contract.py`"),
            "f_p0_summary_current": {
                "verdict": "见 `p0_check`（本件不写库，判定由那格给）",
                "尺": "PYTHONUTF8=1 .venv/Scripts/python.exe -c \"import sys;sys.path[:0]=['eval','.'];import reporter;…\" --emit-p0-summary backend/reports/w8/gate_inputs_p0_summary.json",
            },
        },
        "g6": {
            "sample_floor": floor,
            "admitted_this_batch": admitted,
            "terminal_this_batch": terminal,
            "admitted_eq_terminal": admitted == terminal,
            "可引用": admitted >= floor,
            "verdict": ("达成：P95 可引用" if admitted >= floor else
                        f"🔴 未达成：{admitted} < 下限 {floor} ⇒ G-6 继续不可引用"),
            "g6_p95_le_8s": scen["g6_p95_le_8s"],
            "g6_caveat_原文": scen["g6_caveat"],
            "本批_p95_读数": scen["latency_ms"],
            "旧读数处置": "本轮不产生可引用 P95 ⇒ 旧的那把（第 12 轮 9.81/20.04/8.94/9.08s 与 6.18s 一类）**不被取代**，引用它们仍须带各自 n 与作废声明",
            "结构性发现": ("单用户稳态一把批**拿不到 ≥20 准入**：QUERY 桶 = 10/用户·分钟（`app/api/ratelimit.py:203`），"
                          "而 429 是秒回 ⇒ 30 条请求在 22 秒内全部发出 ⇒ 只有第一个窗口的 10 条被准入。"
                          "要 ≥20 样本只有两条路：① c=1 串行（墙钟 ~300s，能准入 ~28，但**丢掉 c=3 并发**那一格）；"
                          "② 多用户令牌（3 枚 ⇒ 3 个用户各自 10/min ⇒ 可准入 ~28–30，c=3 保留）。两条都超出本轮『一把批』的字面范围 ⇒ 已交回不擅自做"),
        },
        "u129_three_cells": {
            "口径": "格1 = ⑮ 两臂（臂1 ∧ 臂2 皆 0）；格2 = `t2_routed_audit_supp_without_terminal_write` = 0 且第四件前置 `t2_routed_supp > 0`（非空真）；格3 = `t2_with_terminal_write ≥ 1`",
            "harness_rows": {"格1_含作废": harness_row("⑮", "with_void"),
                             "格1_剔作废": harness_row("⑮", "excl"),
                             "格2格3_含作废": harness_row("⑰ ", "with_void"),
                             "格2格3_剔作废": harness_row("⑰ ", "excl"),
                             "尺自检_剔作废": harness_row("①", "excl")},
            "scope_readings": {"含作废格_窗_04:25:00Z": scope("2026-10-06 04:25:00+00", False),
                               "具名剔除作废格": scope("2026-10-06 04:25:00+00", True)},
            "两份归档": {"with_void": "evidence/t38/r23_scope_with_void_cell.txt",
                        "excl_void": "evidence/t38/r23_scope_excl_void_cell.txt"},
            "复算": "MSYS_NO_PATHCONV=1 docker exec -i commerceql-pg-1 psql -U postgres -d ecom -A -F'|' "
                   "-v win_a='2026-10-06 04:25:59+00' -v win_b='2026-10-06 04:27:00+00' "
                   "-v upref='u_t38c3%' -f - < deploy/loadtest/r23_thread_from_checkpoints.sql",
        },
        "thread_key_discrepancy": {
            "receipt_侧": {"组数": depth_cell["groups"],
                           "分组键": depth_cell["grouping_key"],
                           "depth_hist": depth_cell["depth_hist"],
                           "回执键名": depth_cell["key_in_receipt"],
                           "改名依据": "U-138① —— 旧键 `thread_depth`/`threads` 自称 thread ⇒ 新回执改叫 `worker_session_depth`/`groups`；"
                                   "本件读的是 T-38 当期那份（改名**之前**跑的），所以回执里的键仍是旧名，两格在此对上"},
            "库面": {"分组键": "tenant:user:session（`lg.checkpoints.thread_id`）",
                     "尺": "deploy/loadtest/r23_thread_from_checkpoints.sql ⑮/⑰（剔作废那跑）",
                     "含作废": scope("2026-10-06 04:25:00+00", False)["server_threads"],
                     "剔作废": scope("2026-10-06 04:25:00+00", True)["server_threads"]},
            "结论": "两把不等价（组数 vs 库面 thread 数）⇒ 凡『同一 thread 的第 N 轮』只从库面取（U-138③）；"
                    "本格 = U-138② 要求的『同框并报』落点",
        },
        "spend": {**spend, "cap_cny": CAP_CNY,
                  "within_cap": spend["sum_cny"] <= CAP_CNY,
                  "main_batch_only_named_tasks": main_only,
                  "unit_measured_cny_per_admission": unit_measured,
                  "unit_分子分母同面": f"分子 = 具名 {main_only['distinct_task_ids_billed']} 个 run 的 ¥{main_only['sum_cny']}；"
                                   f"分母 = admitted {admitted}；作废那跑（¥0.007166）不在分子里",
                  "unit_cny_per_run_in_window_incl_void": unit_window_incl_void,
                  "两把单价的差别": f"¥{unit_measured}（剔作废、具名）vs ¥{unit_window_incl_void}（整窗含作废 ÷ 10 run）"
                                f" ⇒ 旧写法把它叫 per_admission 是自相矛盾，本轮改名并同框并报",
                  "对表": {"报价 low/expected/high": quote["budget"]["cost_range_cny"],
                           "实付": spend["sum_cny"],
                           "偏差原因": "墙钟 22s（429 秒回）≠ 报价假设的 ~150s ⇒ 准入 9 而非 21 ⇒ 实付低于期望"},
                  "台账首末": {"本轮前": quote["ledger_baseline"], "本轮后": spend["ledger_now"]}},
        "residue_ruler": "docker exec -i commerceql-pg-1 psql -U postgres -d ecom -Atc \"select datname from pg_database where datname like 'ecom%' order by 1\"",
    }
    out["hard_requirements"]["f_p0_summary_current"]["verdict"] = _p0_verdict()
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    hr = out["hard_requirements"]
    print(f"a 作废格 = {hr['a_void_cell']['verdict']}")
    print(f"b 报价笔早于 started_at = {hr['b_quote_before_started_at']['verdict']}"
          f"（差 {hr['b_quote_before_started_at']['读数']['delta_s']}s）")
    print(f"c 构建身份 = {hr['c_build_identity']['verdict']}")
    print(f"d 逐样本延迟 = {hr['d_latency_samples']['verdict']}"
          f"（n={hr['d_latency_samples']['读数']['n_samples']} / admitted={admitted}）")
    print(f"e 读数面 = 已归档 {len(TERMINAL_KEYS)} 格")
    print(f"f p0 当期化 = {hr['f_p0_summary_current']['verdict']}")
    print(f"G-6 = {out['g6']['verdict']}")
    print(f"实付 = ¥{spend['sum_cny']} / 上界 ¥{CAP_CNY} ｜ 当期单价 ¥{unit_measured}/准入 ｜ "
          f"非峰 = {spend['all_non_peak']}")
    print(f"两把尺 = 回执侧 {depth_cell['groups']} 组（键名 {key_in_receipt}）vs 库面 {out['thread_key_discrepancy']['库面']['剔作废']} 条 thread")
    print(f"产物 = {OUT.relative_to(ROOT)}")
    return 0


def _p0_verdict() -> str:
    """(f)：证件里的 `git_rev`／笔数／两把 `passed` 是否已跟上本轮 ⇒ 只看件，不重算门禁。

    🔴 T-39 B 修坏尺：旧写法 `re.search(r"passed=(\\d+)", str(p0["offline"]))` **恒不命中**
    （`offline` 是 dict，`str()` 出来是 `'passed': 2454`，冒号不是等号）⇒ 那半格永远印 `—`。
    ⇒ 改成直取键值；拿不到就按 docstring 自己的规矩写 `UNVERIFIED`，不给"看起来像读数"的占位符。
    """
    p0 = jload(W8 / "gate_inputs_p0_summary.json")

    def passed(side: str) -> str:
        block = p0.get(side)
        value = block.get("passed") if isinstance(block, dict) else None
        return str(value) if isinstance(value, int) else "UNVERIFIED"

    return (f"证件 rev = {str(p0.get('git_rev'))[:7]} / {p0.get('commit_count')} 笔 / "
            f"generated {p0.get('generated_at')} / offline passed = {passed('offline')} / "
            f"integration passed = {passed('integration')}"
            f" → 与本轮干净树一致才算达成（装配件不下这一判，留给门禁那件）")


if __name__ == "__main__":
    sys.exit(main())
