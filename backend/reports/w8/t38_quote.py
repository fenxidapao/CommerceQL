"""T-38 主单 (b) 的前半：**报价先落盘**，再花那笔钱。

为什么单独成件（不是"跑完补一个报价"）：第 12 轮那次被 QA 判 (d) 未达成 ——
报价笔 `b496d7b` 的 **commit date 05:11:24Z** 晚于作废格 `started_at 04:51:14Z` 二十分十秒 ⇒
"先报价后跑"在账面上无法证明。本轮把这句话变成一件**可以被时间戳证伪的产物**：

1. 本件写 `deploy/loadtest/t38_c3n30_quote.json`（含几何、两个单价基线、金额区间、上界、超限处置、样本下限）；
2. **它必须先被 commit**（该笔 = 报价笔）；
3. 之后才允许起预热格与主批；
4. 结案尺 = `git log -1 --format=%cd <报价笔>` **早于** 主批回执 `started_at`（两侧都是 ISO-8601 带时区，可直接字符串比序）。

口径（缺一项这格就不可手算）：
- **单价不是常数**：一条准入的调用数随题面变（1～4 次），所以这里给**两个实测基线**而不是一个"均价"：
  · `unit_r12_ledger` = 第 12 轮账面 = 该窗台账 `sum(cost_cny) / admitted`（分子分母都从库与回执现取）；
  · `unit_dispatch`   = 来件给的 `¥0.00753/准入`（**照引来件、不自行改**，本窗复核见 §十六）。
- **上界 ¥0.25 是总控批的**，所以报价必须给出"在什么条件下会撞界"的可判伪式子，而不是只给一个期望值。
- `MIN_ADMITTED_FOR_P95` 从 `deploy/loadtest/driver.py` **现读**（不抄文档）⇒ 样本不足时 G-6 只能写 null ＋ caveat 原文。

复算（cwd = 仓库根；**零额度、零写库**，psql 那段在 `begin; … rollback;` 里）：
    PYTHONUTF8=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w8/t38_quote.py
产物：`deploy/loadtest/t38_c3n30_quote.json`（内容除 `generated_at_utc` 外逐字幂等；重跑只在几何或库内台账变了才动）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

#: 本件在 `backend/reports/w8/` ⇒ 仓库根 = parents[**3**]（w8 → reports → backend → 根）。
#: ⚠️ 这一格本窗写错过一次（取成 parents[2] ⇒ 拼出 `backend/deploy/loadtest/driver.py` ⇒ "尺坏"分支自己炸），
#: 与本窗《本机环境坑》记的 cwd≠仓库根 同族 ⇒ 深度必须现打印再断言。
ROOT = Path(__file__).resolve().parents[3]
DRIVER = ROOT / "deploy" / "loadtest" / "driver.py"
OUT = ROOT / "deploy" / "loadtest" / "t38_c3n30_quote.json"

#: 已批几何（逐字 = 派单那一行；改动它 = 换靶子，要重新批）
GEOMETRY = {
    "scenario": "steady",
    "concurrency": 3,
    "max_requests": 30,
    "reuse_sessions": True,
    "session_pool": 3,
    "command": ("python deploy/loadtest/driver.py --scenario steady --concurrency 3 "
                "--max-requests 30 --reuse-sessions --session-pool 3 "
                "--tokens <仓库外一次性令牌文件> --out <回执路径>"),
}
CAP_CNY = 0.25
UNIT_DISPATCH = 0.00753
#: 第 12 轮那把批的窗（用来现取"账面单价"的分子分母；窗与时点逐字点名）
R12_WINDOW = "2026-10-05 04:45:00+00"
R12_ADMITTED = 6  # 三对 pair1/pair2/pair3 = 2+2+2，回执侧 admission.admitted 相加


def psql(sql: str) -> str:
    """共享 `ecom` 只读取证（本件只 SELECT；凭据在容器里，不进对话也不进仓库）。

    ⚠️ 必须带 `-q`：`begin; … rollback;` 包一层时 psql 会把 `BEGIN` / `ROLLBACK` 两个命令标签
    也打到 stdout（`-t` 挡不住），不加 `-q` 就会把 `BEGIN` 当第一列去 `int()`。
    """
    p = subprocess.run(["docker", "exec", "-i", "commerceql-pg-1", "psql", "-U", "postgres",
                        "-d", "ecom", "-q", "-t", "-A", "-c", f"begin; {sql} rollback;"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit(f"psql rc={p.returncode}: {(p.stderr or '')[-300:]}")
    return (p.stdout or "").strip()


def min_admitted() -> int:
    src = DRIVER.read_text(encoding="utf-8")
    m = re.search(r"^MIN_ADMITTED_FOR_P95: Final\[int\] = (\d+)$", src, re.M)
    if not m:
        raise SystemExit("尺坏：driver.py 里读不到 MIN_ADMITTED_FOR_P95 那一行（不要退回抄文档值）")
    return int(m.group(1))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-db", action="store_true", help="不读台账（离线核对几何与算式用）")
    args = ap.parse_args(argv)

    if not DRIVER.exists():
        raise SystemExit(f"尺坏：driver.py 不在 {DRIVER}（ROOT = {ROOT}，本件深度应取 parents[3]）")
    print(f"[ROOT] {ROOT}")

    ledger = None
    unit_r12 = None
    if not args.no_db:
        rows, total, maxc = psql("select count(*), sum(cost_cny), max(created_at) "
                                 "from app.cost_ledger;").split("|")
        ledger = {"rows": int(rows), "sum_cny": float(total),
                  "max_created_at": maxc,
                  "captured_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
        r12_rows, r12_sum = psql(f"select count(*), sum(cost_cny) from app.cost_ledger "
                                 f"where created_at >= '{R12_WINDOW}';").split("|")
        unit_r12 = round(float(r12_sum) / R12_ADMITTED, 6)
        ledger["r12_window"] = {"since": R12_WINDOW, "rows": int(r12_rows),
                                "sum_cny": float(r12_sum), "admitted": R12_ADMITTED,
                                "unit_cny_per_admission": unit_r12}

    floor = min_admitted()
    # 期望准入 21 = 来件给的数；区间 18–30 的来由：单用户 QUERY 桶 = 10/分钟（`ratelimit.py:203`
    # 现读 RateLimitRule(QUERY, 10, 100)），本几何在 ~150s 墙钟（第 12 轮 pair1 = 2 条 / 29.97s ⇒ 单条 ≈15s）
    # 下允许 15～30 条准入；来件按 ≈21 估 ⇒ 区间只作为"撞界/欠样本"的判据边界，不作为读数。
    expected, lo, hi = 21, 18, 30
    quote = {
        "schema": "commerceql.loadtest.quote/1",
        "task": "T-38 主单（U-129 ③ ＋ G-6 首个可引用 P95）",
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git_rev_at_quote": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                           capture_output=True, text=True).stdout.strip(),
        "worktree_dirty_at_quote": bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                                       capture_output=True, text=True).stdout.strip()),
        "geometry": GEOMETRY,
        "budget": {
            "approved_cap_cny": CAP_CNY,
            "approved_by": "总控（第 15 轮 T-38 派单：已批花费，上界 ¥0.25，超过就停并把报价交回）",
            "unit_baselines": {
                "unit_dispatch_cny_per_admission": UNIT_DISPATCH,
                "unit_r12_ledger_cny_per_admission": unit_r12,
                "口径": ("两个数都保留：`unit_dispatch` 照引来件不改；`unit_r12_ledger` = "
                          f"第 12 轮那把批（窗 ≥ {R12_WINDOW}）的 `sum(cost_cny) ÷ admitted`"
                          f" = {float(ledger['r12_window']['sum_cny']) if ledger else '—'} ÷ {R12_ADMITTED}"
                          "。一条准入的调用数随题面变（1～4 次），所以不得把任一数当'均价'外推。"),
            },
            "predicted_admissions": {"expected": expected, "range": [lo, hi],
                                     "依据": "见本件 docstring 的桶算式；实际准入由回执 `admission.admitted` 读数，不由本行认定"},
            "cost_range_cny": {"low": round(lo * UNIT_DISPATCH, 6),
                               "expected": round(expected * UNIT_DISPATCH, 6),
                               "high": round(hi * (unit_r12 or UNIT_DISPATCH), 6)},
            "cap_breach_condition": (f"实付 > {CAP_CNY} ⇒ 立即停：不补跑、不为凑样本加批，"
                                     "把回执与差值交回 QA 转总控"),
            "cap_breach_threshold_admissions": (None if not unit_r12 else
                                                int(CAP_CNY / unit_r12)),
        },
        "sample_floor": {
            "MIN_ADMITTED_FOR_P95": floor,
            "read_from": "deploy/loadtest/driver.py 的 `MIN_ADMITTED_FOR_P95` 那一行（本件现读，不抄文档）",
            "若不足": f"admitted < {floor} ⇒ G-6 继续 `g6_p95_le_8s = null` ＋ `g6_caveat` 原文，"
                      "🚫 不得把该批的 P95 引用为达标或不达标",
        },
        "void_cell": {
            "purpose": "预热一格（硬要求 a）⇒ 不进任何分母、不进 P95 样本、不进 U-129 的分子",
            "geometry_override": {"max_requests": 1},
            "note_rule": "作废格回执的 `note` 必须点名其构建身份是跑前取还是跑后补打",
        },
        "reading_surface_required": ["admission.admitted", "admission.terminal", "outcomes",
                                     "codes", "codes_task_ids", "thread_depth", "p95_scope",
                                     "g6_caveat", "latency_samples_ms", "build_identity"],
        "ledger_baseline": ledger,
        "clock_caveat": ("跨面比时间前必须先对表：本轮起每把批都记 `host date -u` ⟷ 容器 `date -u` ⟷ "
                         "外部 HTTP `Date` 头三处（同机曾出现主机钟与容器钟差 11h39m 的一次实测）"),
        "ruler_b": ("git log -1 --format=%cd --date=iso-strict <报价笔>  <  主批回执 started_at"
                    "（报价笔 = 本件 JSON 的入库笔，不是本件生成时刻）"),
    }
    OUT.write_text(json.dumps(quote, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"报价已落 {OUT.relative_to(ROOT)} ｜ git_rev_at_quote={quote['git_rev_at_quote'][:7]}"
          f" dirty={quote['worktree_dirty_at_quote']}")
    print(f"几何 = steady c=3 n=30 pool=3 ｜ 上界 ¥{CAP_CNY} ｜ 期望准入 {expected}（区间 {lo}–{hi}）")
    print(f"单价基线：来件 ¥{UNIT_DISPATCH}/准入 ｜ 第 12 轮账面 "
          f"{unit_r12 if unit_r12 else '—'}/准入")
    rng = quote["budget"]["cost_range_cny"]
    print(f"金额区间：低 {rng['low']} / 期望 {rng['expected']} / 高 {rng['high']}")
    print(f"撞界阈值：admitted ≥ {quote['budget']['cap_breach_threshold_admissions']}"
          f"（按账面单价）｜ 样本下限 MIN_ADMITTED_FOR_P95 = {floor}")
    print(f"台账基线 = {ledger}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
