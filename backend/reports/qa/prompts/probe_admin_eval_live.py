r"""QA 永久活体复算件：`A.9.2／A.9.3／A.9.4` 三个只读端点（T-34 交付面）。

零额度：三端点的数据源是**已入库产物**（`eval/results_*.json` ＋ `backend/reports/w6/eval_metrics.json`），
端点内不重跑评测、不出站调模型 ⇒ 本件不产生 `app.cost_ledger` 行（跑前跑后各读一次作自证）。

只印 状态码／信封 `code`／计数／键名／哈希 —— **不印令牌、不印题面、不印结果行**（N-11 同源）。
⚠️ 键名一律按 `docs/02 §A.9.2–§A.9.4` 的契约名取（QA 第 15 轮自曝：第一版按"想当然"的键名取 ⇒
    五个臂全 `DIFF`，差点把尺误写成别窗缺陷；读别人的实现先读契约，再读码，最后才读数）。

用法（本机 `api` 容器在位，compose 挂了 `/eval_artifacts` 与 `/eval_reports` 两个只读卷）：
    PYTHONUTF8=1 .venv/Scripts/python.exe backend/reports/qa/prompts/probe_admin_eval_live.py
退出码：0 = 各臂全合格；1 = 有不合格臂；非 0 ＋ traceback = 环境不可用（容器没起／mint 失败）。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000/api/v1"
BACKEND = Path(__file__).resolve().parents[3]
MINT = [sys.executable, "scripts/mint_dev_token.py"]
WORDSET = {"pass", "fail", "partial", "unverified", "not_available"}
EXPECTED = {"datasets_total": 2, "runs_items": 5, "cells": 12, "unavailable": 6, "gates": 8}


def token(role: str, user_id: str) -> str:
    r = subprocess.run([*MINT, "--tenant-id", "T_A", "--user-id", user_id, "--role", role, "--ttl", "120"],
                       cwd=str(BACKEND), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"[环境不可用] mint 失败 rc={r.returncode}：{(r.stderr or '').strip()[-200:]}")
    return r.stdout.strip()


def call(path: str, tok: str) -> tuple[int, dict]:
    req = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"code": f"(不可解析 {len(raw)}B)"}


def ledger() -> str:
    p = subprocess.run(["docker", "exec", "-i", "commerceql-pg-1", "psql", "-U", "postgres", "-d", "ecom",
                        "-t", "-A", "-v", "ON_ERROR_STOP=1", "-c",
                        "select count(*)::text || ' 行／¥' || "
                        "to_char(coalesce(sum(cost_cny),0),'FM999990.000000') from app.cost_ledger;"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (p.stdout or "").strip() or "(读不到)"


def h(data: object) -> str:
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def main() -> int:
    before = ledger()
    print(f"账本跑前 = {before}")
    admin, analyst = token("platform_admin", "u_qa_live"), token("analyst", "u_qa_live_x")
    bad: list[str] = []

    def arm(label: str, got: object, want: object) -> None:
        ok = got == want
        if not ok:
            bad.append(label)
        print(f"[{'OK  ' if ok else 'DIFF'}] {label}: got={got} want={want}")

    print("\n--- A.9.2 datasets（契约 `data.items` ＋ `data.total`）---")
    code, b = call("/admin/eval/datasets", admin)
    d = b.get("data") or {}
    items = d.get("items") or []
    print(f"  http={code} 信封code={b.get('code')} total={d.get('total')} items={len(items)} "
          f"字段={sorted(items[0]) if items else '-'} status 值集={sorted({str(i.get('status')) for i in items})}")
    arm("A.9.2 信封 OK", (code, b.get("code")), (200, "OK"))
    arm("A.9.2 total 与 items 同值", d.get("total"), EXPECTED["datasets_total"])
    arm("A.9.2 每条带 content_hash（冻结纪律）",
        all(str(i.get("content_hash", "")).startswith("sha256:") for i in items), True)
    arm("A.9.2 无 draft 混进门禁依据", {str(i.get("status")) for i in items} <= {"frozen"}, True)

    print("\n--- A.9.3 runs（分页三件 ＋ status 词表）---")
    code, b = call("/admin/eval/runs", admin)
    d = b.get("data") or {}
    runs = d.get("items") or []
    print(f"  http={code} 信封code={b.get('code')} items={len(runs)} total={d.get('total')} "
          f"limit={d.get('limit')} offset={d.get('offset')} has_more={d.get('has_more')} "
          f"status 值集={sorted({str(r.get('status')) for r in runs})}")
    arm("A.9.3 items 条数", len(runs), EXPECTED["runs_items"])
    arm("A.9.3 分页三件齐备", {"limit", "offset", "has_more"} <= set(d), True)
    arm("A.9.3 status 落在契约词表",
        {str(r.get("status")) for r in runs} <= {"queued", "running", "complete", "failed"}, True)
    code2, b2 = call("/admin/eval/runs?limit=2&offset=0", admin)
    d2 = b2.get("data") or {}
    arm("A.9.3 limit 生效（不是一律全给）", (code2, len(d2.get("items") or []), d2.get("has_more")), (200, 2, True))

    print("\n--- A.9.4 runs/{run_id}（网格由后端聚合 ＋ 五值 ＋ 缺口如实）---")
    code, b = call("/admin/eval/runs/results_v1", admin)
    d = b.get("data") or {}
    cells = ((d.get("grid") or {}).get("cells")) or []
    gates = ((d.get("gate") or {}).get("items")) or []
    unav = d.get("unavailable") or []
    prov = d.get("provenance") or {}
    cell_v = sorted({str(c.get("verdict")) for c in cells})
    gate_v = sorted({str(g.get("verdict")) for g in gates})
    print(f"  http={code} 信封code={b.get('code')} data keys={sorted(d)}")
    print(f"  grid.cells={len(cells)}（axes={sorted({str(c.get('axis')) for c in cells})[:4]}…）"
          f" 格 verdict 值集={cell_v}")
    print(f"  gate.items={len(gates)} 门禁 verdict 值集={gate_v} passed={ (d.get('gate') or {}).get('passed') }")
    print(f"  unavailable={len(unav)} 字段={sorted(unav[0]) if unav else '-'}")
    print(f"  provenance={sorted(prov)} rerun_in_endpoint={prov.get('rerun_in_endpoint')} "
          f"batch_git_rev={prov.get('batch_git_rev')} dirty={prov.get('batch_git_dirty')}")
    print(f"  scope={d.get('scope')} run_id={(d.get('run') or {}).get('run_id')}")
    arm("A.9.4 信封 OK", (code, b.get("code")), (200, "OK"))
    arm("A.9.4 网格 12 格（后端聚合，非前端自算）", len(cells), EXPECTED["cells"])
    arm("A.9.4 门禁八格", len(gates), EXPECTED["gates"])
    arm("A.9.4 五值词表闭合且不被折叠成两色",
        set(cell_v) | set(gate_v) <= WORDSET and len(set(cell_v) | set(gate_v)) >= 3, True)
    arm("A.9.4 缺口如实列（§十一.3 验收位 = 6 行）", len(unav), EXPECTED["unavailable"])
    arm("A.9.4 端点内未重跑评测", prov.get("rerun_in_endpoint"), False)
    arm("A.9.4 跨租户标注恒在", d.get("scope"), "cross_tenant")

    print("\n--- 臂：角色门禁 fail-closed（analyst 令牌）---")
    for path in ("/admin/eval/datasets", "/admin/eval/runs", "/admin/eval/runs/results_v1"):
        code, b = call(path, analyst)
        print(f"  {path:34s} http={code} 信封code={b.get('code')}")
        arm(f"非管理员 403 FORBIDDEN_SCOPE @ {path.split('/')[-1]}",
            (code, b.get("code")), (403, "FORBIDDEN_SCOPE"))

    print("\n--- 臂：`tenant_id`／`user_id` 做成查询参数不得改变 data（`附录A:600` 禁令）---")
    _, base_runs = call("/admin/eval/runs", admin)
    _, q_runs = call("/admin/eval/runs?tenant_id=T_B&user_id=u_other", admin)
    print(f"  runs(data) 无参={h(base_runs.get('data'))} 带参={h(q_runs.get('data'))}")
    arm("runs 带参 data 全等", h(q_runs.get("data")), h(base_runs.get("data")))
    _, base_rep = call("/admin/eval/runs/results_v1", admin)
    _, q_rep = call("/admin/eval/runs/results_v1?tenant_id=T_B", admin)
    arm("report 带参 data 全等", h(q_rep.get("data")), h(base_rep.get("data")))

    print("\n--- 臂：错误语义（未知批次 = 404 RUN_NOT_FOUND，不是 500）---")
    code, b = call("/admin/eval/runs/qa_probe_absent_batch", admin)
    print(f"  未知 run_id http={code} 信封code={b.get('code')} detail={json.dumps(b.get('detail'), ensure_ascii=False)[:80]}")
    arm("未知 run_id 必 404 RUN_NOT_FOUND", (code, b.get("code")), (404, "RUN_NOT_FOUND"))

    after = ledger()
    print(f"\n账本跑后 = {after}（与跑前同值 ⇒ 本件零花费）")
    arm("零花费自证（账本未动）", after, before)
    print(f"\n不合格 {len(bad)} 臂" + ("".join(f"\n  · {x}" for x in bad) if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
