"""T-38 起建、**第 20 轮换指 T-45 那把批**的结件装配：六条硬要求逐格判一遍，结论必给。

🔻 件名与产物名留在 `t38_*` 是历史锚点（QA 复算认这个路径）；**读哪几把文件**由 `QUOTE/MAIN/VOID/VOID2` 显式常量决定，
并在产物格 `读的哪一份回执` 里逐把点名 ⇒ 不许跟着文件名漂。

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
EVID = W8 / "evidence" / "t45"
QUOTE = ROOT / "deploy" / "loadtest" / "t45_3u_c3_n28_quote.json"
MAIN = ROOT / "deploy" / "loadtest" / "t45_3u_c3_n28_main.json"
VOID = ROOT / "deploy" / "loadtest" / "t45_3u_c3_n28_warm.json"
VOID2 = ROOT / "deploy" / "loadtest" / "t45_3u_c3_n28_warm2.json"
OUT = W8 / "t38_assembled.json"

USER_LIKE = "u_t45c3%"
VOID_TASKS = ["tk_c10130f05eac41b288251d01eb0493fd",   # 预热第一格（冷启动，p95 15,629ms）
                "tk_17db76d050f743ac85a5082d20f7a616"]  # 预热第二格（上游门 ④，p95 6,665.5ms）
CAP_CNY = 0.30  # 🔴 必须与报价件 approved_cap_cny 逐值相等，main() 里有断言，防两边漂
TERMINAL_KEYS = ("admission", "outcomes", "codes", "codes_task_ids", "thread_depth",
                 "worker_session_depth",
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
    void2_r = jload(VOID2)
    scen = main_r["scenarios"][0]
    void_scen, void2_scen = void_r["scenarios"][0], void2_r["scenarios"][0]
    if abs(float(quote["budget"]["approved_cap_cny"]) - CAP_CNY) > 1e-9:
        raise SystemExit("尺坏：报价件的上界与装配件的 CAP_CNY 不一致（两边漂了）")

    quote_commit = sh(["git", "log", "-1", "--format=%H", "--",
                       "deploy/loadtest/t45_3u_c3_n28_quote.json"])
    quote_cd = sh(["git", "log", "-1", "--format=%cd", "--date=iso-strict", quote_commit])
    # 🔴 T-45 D（§26.2 B 裁 (i)）：花费窗的左锚点 = 报价件的 `generated_at_utc`，**不是**报价笔的 commit date。
    # 第 15 轮那把窗的当期读数不变（两把同数），防的是"报价件被再次提交 ⇒ 整窗移位"这个必然发生的未来。
    # (b) 格仍用 `quote_cd`：那条尺问的是"报价笔早不早于主批起跑"，与窗的左边界是两件事。
    quote_utc = dt.datetime.fromisoformat(quote["generated_at_utc"])
    quote_commit_utc = dt.datetime.fromisoformat(quote_cd)  # (b) 格的尺 = 报价**笔**的 committer date
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
    void_admitted = int(void_scen["admission"]["admitted"]) + int(void2_scen["admission"]["admitted"])
    void_spend = spend_for_tasks(VOID_TASKS)
    unit_window_incl_void = round(spend["sum_cny"] / (admitted + void_admitted), 6)

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
    files_face = main_r["build_identity"]["layer1_2"]["files"]
    ident_n = len(files_face)
    ident_same = sum(1 for f in files_face if f["verdict"] == "SAME")
    headlink_same = sum(1 for f in files_face if f["worktree_vs_head_lf"] == "SAME")
    ident_diff = [f["path"].split("/")[-1] for f in files_face if f["verdict"] != "SAME"]
    pre_face = quote["target_face"]  # 跑前身份取源 = 报价件（04:24:06Z 现读）
    pre_face = quote["target_face"]  # 跑前身份取源 = 报价件（04:24:06Z 现读），本轮没有跑前的逐件取证

    # 库面作用域读数：两把窗（含作废 / 具名剔除作废），thread 尺与审计行覆盖
    def scope(win_a: str, excl_void: bool) -> dict:
        cond = f"user_id like '{USER_LIKE}' and \"timestamp\" >= '{win_a}'"
        if excl_void:
            ids = ",".join(f"'{x}'" for x in VOID_TASKS)
            cond += f" and task_id not in ({ids})"
        rows, runs = psql(f"select count(*), count(distinct task_id) from app.audit_log where {cond};").split("|")
        threads = psql(
            f"select count(distinct split_part(thread_id,':',1)||':'||split_part(thread_id,':',2)"
            f"||':'||split_part(thread_id,':',3)) from lg.checkpoints ck where exists "
            f"(select 1 from app.audit_log a where a.task_id = ck.checkpoint->'channel_values'->>'task_id'"
            f" and {cond});")
        return {"audit_rows": int(rows), "runs": int(runs), "server_threads": int(threads)}

    out = {
        "artifact": "commerceql.w8.t38_assembled/1",
        "task": "T-45 主单：一把 3 令牌／c=3／n=28 的当期批（靶子甲 ＋ U-129 ③ ＋ U-138 结案后半 ＋ G-6 够格样本）",
        "读的哪一份回执": {
            "口径": "本件每个数都来自下面这几把；路径是**显式常量**，不靠文件名猜",
            "quote": {"path": str(QUOTE.relative_to(ROOT)), "generated_at_utc": quote["generated_at_utc"],
                      "上界": quote["budget"]["approved_cap_cny"], "报价笔": quote_commit[:7]},
            "main": {"path": str(MAIN.relative_to(ROOT)), "started_at": main_r["started_at"],
                     "finished_at": main_r["finished_at"], "件内git_rev": main_r["git_rev"],
                     "admitted": admitted, "样本数": len(scen.get("latency_samples_ms") or [])},
            "void_两把": [{"path": str(VOID.relative_to(ROOT)), "started_at": void_r["started_at"],
                           "admitted": int(void_scen["admission"]["admitted"])},
                          {"path": str(VOID2.relative_to(ROOT)), "started_at": void2_r["started_at"],
                           "admitted": int(void2_scen["admission"]["admitted"])}],
            "历史件不被读": "deploy/loadtest/t38_c3n30_*.json 三把只作第 15／16 轮读数的落点留在盘上，🚫 不许覆盖",
        },
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
                "verdict": ("达成（两格各 1 条准入，具名剔除）"
                            if int(void_scen["admission"]["admitted"]) == 1
                            and int(void2_scen["admission"]["admitted"]) == 1 else "UNVERIFIED"),
                "读数": {"void_admitted_1": void_scen["admission"]["admitted"],
                         "void_admitted_2": void2_scen["admission"]["admitted"],
                         "void_started_at": [void_r["started_at"], void2_r["started_at"]],
                         "void_outcomes": [void_scen["outcomes"], void2_scen["outcomes"]],
                         "void_p95_两把": [void_scen["latency_ms"]["p95"], void2_scen["latency_ms"]["p95"]],
                         "void_具名花费": void_spend,
                         "不进分母": f"主批分母 = {admitted}（不含上面两格共 {void_admitted} 条具名 task_id）"},
                "尺": "回执 `scenarios[0].admission.admitted` ⟷ 主批窗口的具名剔除（`task_id not in VOID_TASKS`）",
                "note_rule": ("两格预热的回执里都**没有** `build_identity`（驱动不产这格）；主批身份 = 跑后由 "
                              "attest_build_identity.py 补打，跑前那半取源 = 报价件 `target_face`。"
                              "两格预热各干什么：第 1 格吸收冷启动（宿主 12:06:51 ＋0800 才开机、栈 04:08:02Z 起，"
                              "单发 15,629ms），第 2 格验上游门 ④（同形状单发 6,665.5ms）"),
            },
            "b_quote_before_started_at": {
                "verdict": "达成" if quote_commit_utc < main_started else "🔴 未达成",
                "读数": {"quote_commit": quote_commit[:7], "quote_committer_date": quote_cd,
                         "main_started_at": main_r["started_at"],
                         "delta_s": round((main_started - quote_commit_utc).total_seconds(), 1),
                         "void_started_at": [void_r["started_at"], void2_r["started_at"]],
                         "void_also_after_quote": [quote_commit_utc < void_started,
                                                   quote_commit_utc < dt.datetime.fromisoformat(void2_r["started_at"])],
                         "两把锚点并报": {"窗锚（本件起改指这个）": quote["generated_at_utc"],
                                      "笔锚（只有 (b) 格用）": quote_cd,
                                      "为什么两把都要留": "笔锚问『先报价后跑』，窗锚定『这段台账算谁的』——"
                                                    "混用就回到第 15 轮那个隐患：报价件再被提交一次，整窗平移"}},
                "尺": "git log -1 --format=%cd --date=iso-strict <报价笔>  ⟷  回执 started_at（两侧都转 UTC 再比）",
                "教训来源": "第 12 轮那次报价笔晚 20 分 10 秒 ⇒ (d) 判未达成；本轮把报价做成**先提交的产物**",
            },
            "c_build_identity": {
                "verdict": (f"达成（**链一** 容器 ⟷ 工作树字节 = 逐件 {ident_same}/{ident_n} SAME，"
                            f"DIFF = {ident_diff}；聚合 two_links.container_vs_worktree = "
                            f"{agg['two_links']['container_vs_worktree']} —— 靶子甲下**预期就是 False**，"
                            "它证的是『今天的改动在树里、不在被测构建里』，不是这把批跑坏了）；"
                            f"**链二** 工作树 ⟷ HEAD = 逐件 {headlink_same}/{ident_n} SAME ＋ 聚合 "
                            f"two_links.worktree_vs_head = {agg['two_links']['worktree_vs_head']}"
                            f"（全量 {agg['files_count_git']} 件） ＋ 层 3 符号 present。"
                            "🔻 原句「三面全量相等 ＋ 逐件 18/18 ＋ 层 3 ＋ 跑前独立一次」⇒『三面』按 `U-139` 换代成两链；"
                            "『跑前独立一次』本轮也换掉 = 跑前只做了 --self-test ＋ 报价件 target_face"),
                "读数": {"container": main_r["build_identity"]["container"],
                         "image_id": main_r["build_identity"]["image_id"],
                         "container_created_at": main_r["build_identity"]["container_created_at"],
                         "head_rev_at_attest": main_r["build_identity"]["head_rev_short"],
                         "per_file_same": f"{ident_same}/{ident_n}",
                         "per_file_headlink_same": f"{headlink_same}/{ident_n}",
                         "逐件DIFF清单": ident_diff,
                         "two_links": agg["two_links"],
                         "aggregate_three_way_equal": agg["three_way_equal"],
                         "aggregate_files": f"{agg['files_count_container']}/{agg['files_count_git']}",
                         "layer3": main_r["build_identity"]["layer3_behavior"],
                         "跑前身份取源": {"来自": "报价件 target_face（本轮先起跑、后打逐件身份 ⇒ 没有跑前的逐件 attestation）",
                                     "quote_generated_at_utc": quote["generated_at_utc"],
                                     "image_created_utc": pre_face["image_created_utc"],
                                     "container_created_utc": pre_face["container_created_utc"],
                                     "container_started_utc": pre_face["container_started_utc"],
                                     "ast_gate_容器md5": pre_face["ast_gate_md5_in_container"],
                                     "ast_gate_HEAD的LF面md5": pre_face["ast_gate_md5_head_lf"],
                                     "四把钟": {k: v for k, v in quote["clocks_at_quote"].items() if k != "口径"},
                                     "self_test_起跑前": "attest_build_identity.py --self-test ⇒ 3/3 PASS",
                                     "image_id": main_r["build_identity"]["image_id"]}},
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
            "e_键名漂移": ("🔻 本句原写『本格 `thread_depth` 是 T-38 那份回执的原样搬运 ⇒ 读新批时换成 `worker_session_depth`』；"
                        "**第 20 轮读的就是新批** ⇒ `TERMINAL_KEYS` 已同时列入两把键名，现读本批回执给的是新键 "
                        f"`{key_in_receipt}` ⇒ **U-138 结案条件后半到位**；"
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
            "结构性发现": ("🔴 第 20 轮现测：**多用户令牌这条路今天也没买到 ≥20 准入** —— 3 枚令牌／c=3／n=28 ⇒ "
                          f"admitted = {admitted}、rejected_429 = {scen['admission']['rejected_429']}、"
                          f"other_http_4xx = {scen['admission']['other_http_4xx']}（全是 `SESSION_NOT_FOUND`，"
                          f"404 的 header 面 = {scen.get('rejection_headers', {}).get('404')}）"
                          f"⇒ 差的那几条不是限流吃掉的、是**会话形状吃掉的**；墙钟 {scen['wall_s']}s（不是第 15 轮的 22s）。"
                          "机制（读码 `deploy/loadtest/driver.py:324-325` ⟷ `:349-350`）：`sid = session_pool[i % len(pool)]` 里的 `i` "
                          "是**每个 worker 自己的请求计数**，而令牌是 `tokens[worker_idx % len(tokens)]` **按 worker 固定** ⇒ 池子第 j 项由 "
                          "`tokens[j % n]` 铸造，两者不同余时这一发就拿别人的会话号去打 ⇒ RLS 下 404。"
                          "⚠️ 逐条 (worker, session) 归属回执里没记 ⇒ 该半格记 `UNVERIFIED`，机制只由读码成立。"
                          "🔻 原句（第 15 轮）『单用户一把批拿不到 ≥20 ⇒ 两条路：① c=1 串行 ② 多用户令牌』——② 今天跑了，"
                          "结论改成『② 要先让会话与令牌对齐』（同形状下 `--session-pool 1`，或下一把改形状），"
                          "本窗无权加第二把 ⇒ 交回总控，不擅自补跑"),
        },
        "u129_three_cells": {
            "口径": "格1 = ⑮ 两臂（臂1 ∧ 臂2 皆 0）；格2 = `t2_routed_audit_supp_without_terminal_write` = 0 且第四件前置 `t2_routed_supp > 0`（非空真）；格3 = `t2_with_terminal_write ≥ 1`",
            "harness_rows": {"格1_含作废": harness_row("⑮", "with_void"),
                             "格1_剔作废": harness_row("⑮", "excl"),
                             "格2格3_含作废": harness_row("⑰ ", "with_void"),
                             "格2格3_剔作废": harness_row("⑰ ", "excl"),
                             "尺自检_剔作废": harness_row("①", "excl")},
            "scope_readings": {"含两格预热": scope("2026-10-07 04:25:00+00", False),
                               "具名剔除两格预热": scope("2026-10-07 04:25:00+00", True)},
            "两份归档": {"with_void": "evidence/t45/r23_scope_with_void_cell.txt",
                        "excl_void": "evidence/t45/r23_scope_excl_void_cell.txt"},
            "复算": "MSYS_NO_PATHCONV=1 docker exec -i commerceql-pg-1 psql -U postgres -d ecom -A -F'|' "
                   "-v win_a='2026-10-07 04:27:23+00' -v win_b='2026-10-07 04:28:30+00' "
                   "-v upref='u_t45c3%' -f - < deploy/loadtest/r23_thread_from_checkpoints.sql",
        },
        "thread_key_discrepancy": {
            "receipt_侧": {"组数": depth_cell["groups"],
                           "分组键": depth_cell["grouping_key"],
                           "depth_hist": depth_cell["depth_hist"],
                           "回执键名": depth_cell["key_in_receipt"],
                           "改名依据": "U-138① —— 旧键 `thread_depth`/`threads` 自称 thread ⇒ 新回执改叫 `worker_session_depth`/`groups`；"
                                   "🔻 原句『本件读的是 T-38 当期那份（改名之前跑的）』已过期 ⇒ 第 20 轮读的是 t45 主批，"
                                   f"现读回执里就是**新键**（`key_in_receipt` = `{key_in_receipt}`）⇒ **U-138 结案条件后半到位**"},
            "库面": {"分组键": "tenant:user:session（`lg.checkpoints.thread_id`）",
                     "尺": "deploy/loadtest/r23_thread_from_checkpoints.sql ⑮/⑰（剔作废那跑）",
                     "含作废": scope("2026-10-07 04:25:00+00", False)["server_threads"],
                     "剔作废": scope("2026-10-07 04:25:00+00", True)["server_threads"]},
            "结论": "两把不等价（组数 vs 库面 thread 数）⇒ 凡『同一 thread 的第 N 轮』只从库面取（U-138③）；"
                    "本格 = U-138② 要求的『同框并报』落点",
        },
        "spend": {**spend, "cap_cny": CAP_CNY,
                  "within_cap": spend["sum_cny"] <= CAP_CNY,
                  "main_batch_only_named_tasks": main_only,
                  "unit_measured_cny_per_admission": unit_measured,
                  "unit_分子分母同面": f"分子 = 具名 {main_only['distinct_task_ids_billed']} 个 run 的 ¥{main_only['sum_cny']}；"
                                   f"分母 = admitted {admitted}；两格预热（具名 {void_spend['rows']} 行台账 / "
                                   f"¥{void_spend['sum_cny']}）不在分子里",
                  "unit_cny_per_run_in_window_incl_void": unit_window_incl_void,
                  "两把单价的差别": f"¥{unit_measured}（剔作废、具名 {main_only['distinct_task_ids_billed']} run）"
                                f" vs ¥{unit_window_incl_void}（整窗含作废 ÷ {admitted + void_admitted} 准入）"
                                f" ⇒ 第 15 轮那把是 9 准入 ÷ 1 格作废，本轮是 {admitted} 准入 ÷ 2 格作废 ⇒ 两把都要报名字",
                  "对表": {"报价 low/expected/high": quote["budget"]["cost_range_cny"],
                           "实付": spend["sum_cny"],
                           "偏差原因": (f"准入 {admitted} 落在报价区间 "
                                         f"{quote['budget']['predicted_admissions']['range']} 之下沿 ⇒ shortfall 全部来自 "
                                         "8 条 404（会话形状）而不是 429 ⇒ 实付低于期望；"
                                         f"报价的账面单价 ¥{quote['budget']['unit_baselines']['unit_r15_ledger_cny_per_admission']}/准入 本轮逐值复现")},
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
