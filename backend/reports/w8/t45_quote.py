"""T-45 主单的前半：**报价先落盘**，再花那一把钱（形状 = `t38_quote.py`，几何与基线换成第 20 轮的）。

为什么还要一件报价而不是"来件已经给了数"：装配件的 (b) 格要求「报价笔早于主批 `started_at`」，
这句话只有做成**先入库的产物**才可判伪；而 D 件把 `spend_window` 的锚点从 `git log %cd`
换成报价件的 `generated_at_utc` ⇒ 本件的生成时刻就是新批那把窗的左边界（不是某笔提交的时刻）。

口径（缺一项这格就不可手算）：
- **单价现取**：`unit_r15_ledger` = 第 15 轮那把主批（具名 9 个 `task_id`）的 `sum(cost_cny) ÷ admitted`
  ⟷ `unit_dispatch` = 来件给的 `¥0.00655／准入`（照引来件，不自行改）。两个数都保留，🚫 不当"均价"外推。
- **桶算术从代码现读**：`app/api/ratelimit.py` 的 `RateLimitBucket.QUERY` 那一行（每用户 N/分钟 ⟷ 每租户 M/分钟），
  不是抄文档 —— 3 枚令牌 ⇒ 每分钟准入上限 = `3 × N`。
- **样本下限从 `driver.py` 现读**（`MIN_ADMITTED_FOR_P95`）⇒ 不足则 G-6 只能 `null` ＋ caveat 原文。
- **上界 ¥0.30 是总控 10-07 00:40 点的句**，所以必须给出"什么条件撞界"的可判伪式子。

复算（cwd = 仓库根；零额度、零写库，psql 那段在 `begin; … rollback;` 里）：
    PYTHONUTF8=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w8/t45_quote.py
产物：`deploy/loadtest/t45_3u_c3_n28_quote.json`（除 `generated_at_utc` 与台账基线外逐字幂等）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

#: 本件在 `backend/reports/w8/` ⇒ 仓库根 = parents[**3**]（w8 → reports → backend → 根）；深度必须现打印再断言。
ROOT = Path(__file__).resolve().parents[3]
DRIVER = ROOT / "deploy" / "loadtest" / "driver.py"
Ratelimit = ROOT / "backend" / "app" / "api" / "ratelimit.py"
OLD_MAIN = ROOT / "deploy" / "loadtest" / "t38_c3n30_main.json"
OUT = ROOT / "deploy" / "loadtest" / "t45_3u_c3_n28_quote.json"

#: 已批几何（逐字 = T-45 派单那一行；改动它 = 换靶子，要重新批）
GEOMETRY = {
    "scenario": "steady",
    "concurrency": 3,
    "max_requests": 28,
    "reuse_sessions": True,
    "session_pool": 3,
    "user_tokens": 3,
    "target": "http://127.0.0.1:8000/api/v1（共享栈 `commerceql-api-1`，镜像 `ca34ea791a81` = 靶子甲）",
    "command": ("../.venv/Scripts/python.exe driver.py --scenario steady --concurrency 3 "
                "--max-requests 28 --reuse-sessions --session-pool 3 "
                "--tokens <仓库外一次性三枚令牌文件> --out ../deploy/loadtest/t45_3u_c3_n28_main.json"),
    "warm_cell_command": ("同上，但 --max-requests 1 ⇒ 具名作废件 t45_3u_c3_n28_warm.json，不进任何分母"),
}
CAP_CNY = 0.30
UNIT_DISPATCH = 0.00655
#: 第 15 轮那把主批的分母（用来现取账面单价；窗与具名集合逐字点名）
R15_ADMITTED = 9


def sh(args: list[str]) -> str:
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit(f"命令失败 rc={p.returncode}: {args[-1] if args else ''}")
    return (p.stdout or "").strip()


def psql(sql: str) -> str:
    """共享 `ecom` 只读取证（只 SELECT；🔴 `-q` 必带，否则 `BEGIN` 会被当第一列）。"""
    return sh(["docker", "exec", "-i", "commerceql-pg-1", "psql", "-U", "postgres", "-d", "ecom",
               "-q", "-t", "-A", "-c", f"begin; {sql} rollback;"])


def read_floor() -> int:
    src = DRIVER.read_text(encoding="utf-8")
    m = re.search(r"^MIN_ADMITTED_FOR_P95: Final\[int\] = (\d+)", src, re.M)
    if not m:
        raise SystemExit(f"尺坏：driver.py 读不到 MIN_ADMITTED_FOR_P95（ROOT = {ROOT}）")
    return int(m.group(1))


def read_buckets() -> dict:
    src = Ratelimit.read_text(encoding="utf-8")
    m = re.search(r"RateLimitBucket\.QUERY:\s+RateLimitRule\(\s*RateLimitBucket\.QUERY,\s*(\d+),\s*(\d+)", src)
    if not m:
        raise SystemExit("尺坏：ratelimit.py 读不到 QUERY 那一行（不要退回抄 10/100）")
    per_user, per_tenant = int(m.group(1)), int(m.group(2))
    ln = 1 + src[:m.start()].count("\n")
    return {"per_user_per_min": per_user, "per_tenant_per_min": per_tenant,
            "read_from": f"backend/app/api/ratelimit.py:{ln}", "window_s": 60}


def clocks() -> dict:
    host = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    return {"host_utc": host,
            "pg_container_utc": sh(["docker", "exec", "commerceql-pg-1", "date", "-u", "+%Y-%m-%dT%H:%M:%S"]),
            "api_container_utc": sh(["docker", "exec", "commerceql-api-1", "date", "-u", "+%Y-%m-%dT%H:%M:%S"]),
            "db_now": psql("select now();"),
            "口径": "跨面比时间前四把钟同秒才允许引用窗（本项目 09-20 曾实测主机钟与容器钟差 11h39m）"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-db", action="store_true", help="不读台账（离线核对几何与算式用）")
    args = ap.parse_args(argv)
    for req in (DRIVER, Ratelimit, OLD_MAIN):
        if not req.exists():
            raise SystemExit(f"尺坏：{req} 不在（ROOT = {ROOT}，深度应取 parents[3]）")
    print(f"[ROOT] {ROOT}")

    buckets, floor = read_buckets(), read_floor()
    quote = OLD_MAIN.read_text(encoding="utf-8")
    task_ids = [str(s["task_id"]) for s in
                json.loads(quote)["scenarios"][0].get("latency_samples_ms") or []]
    unit_r15 = None
    ledger = None
    if not args.no_db:
        rows, total, maxc = psql("select count(*), sum(cost_cny), max(created_at) from app.cost_ledger;").split("|")
        ledger = {"rows": int(rows), "sum_cny": float(total), "max_created_at": maxc,
                  "captured_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
        ids = ",".join(f"'{t}'" for t in task_ids)
        r15_rows, r15_sum, r15_runs = psql(
            f"select count(*), sum(cost_cny), count(distinct task_id) from app.cost_ledger "
            f"where task_id in ({ids});").split("|")
        if int(r15_runs) != len(task_ids):
            raise SystemExit(f"尺坏：具名 {len(task_ids)} 个 task_id 只命中 {r15_runs} 个 run")
        unit_r15 = round(float(r15_sum) / R15_ADMITTED, 6)
        ledger["r15_named_runs"] = {"task_ids": len(task_ids), "rows": int(r15_rows),
                                    "sum_cny": float(r15_sum), "admitted": R15_ADMITTED,
                                    "unit_cny_per_admission": unit_r15}

    per_user = buckets["per_user_per_min"]
    tokens = GEOMETRY["user_tokens"]
    n = GEOMETRY["max_requests"]
    lo, hi = min(floor, n), n
    expected = min(n, per_user * tokens)
    rng = {"low": round(lo * (unit_r15 or UNIT_DISPATCH), 6),
           "expected": round(expected * (unit_r15 or UNIT_DISPATCH), 6),
           "high": round(hi * max(unit_r15 or 0, UNIT_DISPATCH) * 1.5, 6)}
    out = {
        "artifact": "commerceql.w8.t45_quote/1",
        "task": "T-45 主单：一把 3 令牌／c=3／n=28 的出站批（靶子甲 ＋ U-138 结案条件后半 ＋ G-6 够格样本）",
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git_rev_at_quote": sh(["git", "rev-parse", "HEAD"]),
        "commit_count_at_quote": int(sh(["git", "rev-list", "--count", "HEAD"])),
        "worktree_dirty_at_quote": bool(sh(["git", "status", "--porcelain"])),
        "approved_by": "总控 10-07 00:40 ＋0800 点句（T-45 派单 0′）：上界 ¥0.30、靶子 = 甲、禁第二把／禁改限流／禁 c>3",
        "geometry": GEOMETRY,
        "budget": {
            "approved_cap_cny": CAP_CNY,
            "unit_baselines": {
                "unit_dispatch_cny_per_admission": UNIT_DISPATCH,
                "unit_r15_ledger_cny_per_admission": unit_r15,
                "口径": (f"`unit_dispatch` 照引来件不改；`unit_r15_ledger` = 第 15 轮那把主批具名 {len(task_ids)} 个 run"
                          f" 的 `sum(cost_cny) ÷ admitted` = {ledger['r15_named_runs']['sum_cny'] if ledger else '—'}"
                          f" ÷ {R15_ADMITTED}。一条准入的调用数随题面变 ⇒ 两个数都保留，不得当均价外推。"),
            },
            "rate_bucket_arithmetic": {
                **buckets,
                "推论": (f"3 枚令牌 × 每用户 {per_user}/min ⇒ 一把分钟窗内准入上限 {per_user * tokens}；"
                          f"本批 n = {n} ⇒ 期望准入 ≤ {expected}，429 只在某用户被连发时才可能出现"),
            },
            "predicted_admissions": {"expected": expected, "range": [lo, hi],
                                     "依据": "见上面两格；实际准入由回执 `admission.admitted` 读数认定，不由本行认定"},
            "cost_range_cny": rng,
            "cap_breach_condition": (f"实付 > {CAP_CNY} ⇒ 立即停：不补跑、不为凑样本加批，"
                                     "把回执与差值交回 QA 转总控"),
            "cap_breach_threshold_admissions": (None if not unit_r15 else int(CAP_CNY / unit_r15)),
        },
        "sample_floor": {
            "MIN_ADMITTED_FOR_P95": floor,
            "read_from": "deploy/loadtest/driver.py 的 `MIN_ADMITTED_FOR_P95` 那一行（本件现读，不抄文档）",
            "若不足": f"admitted < {floor} ⇒ G-6 继续 `g6_p95_le_8s = null` ＋ `g6_caveat` 原文，"
                      "🚫 不得把该批 P95 引用为达标或不达标",
        },
        "void_cell": {
            "purpose": "预热一格 ⇒ 不进任何分母、不进 P95 样本（宿主 12:06:51 ＋0800 才开机、栈热机约 8 分钟 ⇒ 冷启动由这格吸收）",
            "geometry_override": {"max_requests": 1},
            "note_rule": "作废格回执的 `note` 必须点名其构建身份是跑前取还是跑后补打",
        },
        "target_face": {
            "container": "commerceql-api-1",
            "image_created_utc": sh(["docker", "image", "inspect", "--format", "{{.Created}}", "commerceql-api:latest"]),
            "container_created_utc": sh(["docker", "inspect", "--format", "{{.Created}}", "commerceql-api-1"]),
            "container_started_utc": sh(["docker", "inspect", "--format", "{{.State.StartedAt}}", "commerceql-api-1"]),
            "host_boot": "2026-10-07T12:06:51+08:00（`Get-CimInstance Win32_OperatingSystem.LastBootUpTime` 现读）",
            "ast_gate_md5_in_container": sh(["docker", "exec", "commerceql-api-1", "md5sum",
                                             "/srv/app/guard/ast_gate.py"]).split()[0],
            "ast_gate_md5_head_lf": hashlib.md5(
                subprocess.run(["git", "show", "HEAD:backend/app/guard/ast_gate.py"],
                               capture_output=True).stdout.replace(b"\r\n", b"\n")).hexdigest(),
            "口径": ("靶子甲 = 10-05 那个构建 ⇒ 链一（容器 ⟷ 工作树）对 `guard/**` **预期就是 DIFF**（今天落的两件不在镜像里），"
                      "🚫 不得写「当期构建已含本轮改动」，判词必须挂 image id"),
        },
        "clocks_at_quote": clocks(),
        "ledger_baseline": ledger,
        "ruler_b": ("git log -1 --format=%cd --date=iso-strict <报价笔>  <  主批回执 started_at；"
                    "本件的 `generated_at_utc` 同时是装配件 `spend_window` 的左锚点（D 件改锚后）"),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"报价已落 {OUT.relative_to(ROOT)} ｜ git_rev_at_quote={out['git_rev_at_quote'][:7]}"
          f"／{out['commit_count_at_quote']} 笔 dirty={out['worktree_dirty_at_quote']}")
    print(f"几何 = steady c=3 n={n} pool=3 tokens={tokens} ｜ 上界 ¥{CAP_CNY} ｜ 期望准入 {expected}（区间 {lo}–{hi}）")
    print(f"桶算术现读 = {buckets['read_from']} ⇒ 每用户 {per_user}/min ⟂ 每租户 {buckets['per_tenant_per_min']}/min")
    print(f"单价基线：来件 ¥{UNIT_DISPATCH}/准入 ｜ 第 15 轮具名账面 {unit_r15}/准入")
    print(f"金额区间：低 {rng['low']} / 期望 {rng['expected']} / 高 {rng['high']}")
    print(f"撞界阈值：admitted ≥ {out['budget']['cap_breach_threshold_admissions']} ｜ 样本下限 {floor}")
    print(f"台账基线 = {ledger}")
    tf = out["target_face"]
    print(f"靶子面 = {tf['container']} 镜像 Created {tf['image_created_utc']} ｜ ast_gate 容器 {tf['ast_gate_md5_in_container'][:8]}… "
          f"⟷ HEAD {tf['ast_gate_md5_head_lf'][:8]}…")
    print(f"四把钟 = {out['clocks_at_quote']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
