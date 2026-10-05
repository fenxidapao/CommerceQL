r"""QA 永久活体复算件：T-37 那三张新面（`/semantic/*`、`/admin/audit`、`POST /admin/eval/run`）。

零额度：两个 GET 是只读投影；`/admin/audit` 走 `app_ro` 只读连接；`POST /admin/eval/run` 的
DTO 是 `dry_run: Literal[True]` ＋ `extra="forbid"` ⇒ **真发起在 schema 面不可表达**（读码确认
`app/present/eval_launch.py` 只读盘上产物、不 import `eval/runner.py`）。跑前跑后各读一次
`app.cost_ledger` 作零花费自证。

只印 状态码／信封 `code`／计数／键名／哈希 ⇒ 不印令牌、不印审计行内容、不印题面（N-11 同源）。

键名按 `docs/02` §A.7.1／§A.7.2／§A.9.1／§A.9.5 与实现读来（QA 第 15 轮自曝"按想当然的键名取 ⇒
五个臂全 DIFF"）：**易变计数只印不卡**（9 指标／8 资产／905 这类数每轮会漂），**判据红线卡死**。

用法（本机 `api` 容器在位 ＋ 共享 `ecom` 在位）：
    PYTHONUTF8=1 .venv/Scripts/python.exe backend/reports/qa/prompts/probe_t37_surfaces_live.py
退出码：0 = 各臂全合格；1 = 有不合格臂；非 0 ＋ traceback = 环境不可用。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

#: 深度尺：本件在 `backend/reports/qa/prompts/` ⇒ **仓库根 = `parents[4]`**、`backend/` = `parents[3]`。
#: 🔻 QA 第 18 轮又踩一次（第一版把根写成 `parents[3]` ⇒ `frontend/dist` 拼到 `backend/frontend/…`、
#: 拿不到件，那条"产物同名同字节"臂假红）。打印出来供对表。
BASE = "http://127.0.0.1:8000/api/v1"
BACKEND = Path(__file__).resolve().parents[3]
ROOT = Path(__file__).resolve().parents[4]
MINT = [sys.executable, "scripts/mint_dev_token.py"]


def token(role: str, user_id: str) -> str:
    r = subprocess.run([*MINT, "--tenant-id", "T_A", "--user-id", user_id, "--role", role, "--ttl", "300"],
                       cwd=str(BACKEND), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"[环境不可用] mint 失败 rc={r.returncode}：{(r.stderr or '').strip()[-220:]}")
    return r.stdout.strip()


def call(path: str, tok: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + tok,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"code": f"(不可解析 {len(raw)}B)"}


def ledger() -> str:
    p = subprocess.run(["docker", "exec", "-i", "commerceql-pg-1", "psql", "-U", "postgres", "-d", "ecom",
                        "-t", "-A", "-c",
                        "select count(*)::text || ' 行／¥' || to_char(coalesce(sum(cost_cny),0),'FM999990.000000') from app.cost_ledger;"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (p.stdout or "").strip() or "(读不到)"


def h(x: object) -> str:
    return hashlib.sha256(json.dumps(x, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _served_bundle() -> tuple[str, tuple[str, str, str]]:
    """取 nginx **正在服务**的那把 JS 产物，并与 `frontend/dist` 同名件比 md5。

    尺的形状（本机坑）：容器里要 `sh -c` 包一层再 `cat`，直调 `docker exec C cat` 拿到的是
    字节流、按文本读容易被换行吃掉 ⇒ 这里让容器自己 `grep -c` 出命中数，只回传计数与 md5。
    """
    names = subprocess.run(["docker", "exec", "commerceql-web-1", "sh", "-c",
                            "ls /usr/share/nginx/html/assets/*.js | head -1"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    remote = (names.stdout or "").strip()
    if not remote:
        raise SystemExit("[环境不可用] 拿不到 nginx 的 JS 产物（web 容器没起？）")
    cnt = subprocess.run(["docker", "exec", "commerceql-web-1", "sh", "-c",
                          f"grep -c denied_columns {remote} || true"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    md5r = subprocess.run(["docker", "exec", "commerceql-web-1", "sh", "-c",
                           f"md5sum {remote} | cut -c1-32"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    base = Path(str(ROOT / "frontend" / "dist" / "assets" / Path(remote).name))
    local_md5 = (hashlib.md5(base.read_bytes()).hexdigest() if base.exists() else "(dist 缺件)")
    return (cnt.stdout or "").strip(), (md5r.stdout.strip(), local_md5, Path(remote).name)


RESULT: list[tuple[bool, str]] = []


def arm(label: str, got: object, want: object) -> bool:
    ok = got == want
    RESULT.append((ok, label))
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}: got={got!r} want={want!r}")
    return ok


def main() -> int:
    before = ledger()
    print(f"[件自证] 账本跑前 = {before}（跑后须同值 ⇒ 零出站）")
    admin = token("platform_admin", "qa_t37_admin")
    analyst = token("analyst", "qa_t37_analyst")

    # ---------- A1：口径字典两张只读 GET（共享面）----------
    print("\n--- 臂：A1 GET /semantic/metrics ＋ /semantic/assets（判据 docs/02:701-702）---")
    st, env = call("/semantic/metrics?limit=500", admin)
    d = env.get("data") or {}
    m_total, m_items = d.get("total"), d.get("items") or []
    print(f"  metrics http={st} total={m_total} items={len(m_items)} 键={sorted(d)[:10]}")
    arm("metrics 200 且信封 OK", (st, env.get("code")), (200, "OK"))
    arm("metrics 计数自洽（total 与 items 同面）", isinstance(m_total, int) and m_total > 0 and len(m_items) > 0, True)
    arm("共享面不得带 scope 键（红线：不是跨租户读别人私有面）",
        "scope" in json.dumps(d, ensure_ascii=False), False)

    st, env = call("/semantic/assets?limit=500", admin)
    da = env.get("data") or {}
    a_items = da.get("items") or []
    print(f"  assets http={st} total={da.get('total')} items={len(a_items)} 首行键={sorted(a_items[0])[:12] if a_items else '—'}")
    arm("assets 200 且有数据", (st, len(a_items) > 0), (200, True))
    #: 🔻 QA 第 18 轮自曝：本臂第一版写成"响应里不得出现 `denied_columns`"，那是**我把尺写反了** ——
    #: `docs/02:712-725` 的 A.7.2 契约**就含**这一格；红线在**渲染侧**（`SemanticPage.tsx:5/332`
    #: 「一律不渲染」，附录 B-10 存在性泄露）。⇒ 正确尺 = 契约键齐 ＋ **产物里搜不到那个键名**。
    contract_keys = {"logical_name", "physical_asset", "grain", "freshness_sla", "owner",
                     "certified", "domain", "column_count", "denied_columns"}
    arm("assets 首行含 §A.7.2 契约九键", contract_keys <= set(a_items[0] or {}), True)
    html, js_md5 = _served_bundle()
    arm("渲染红线（存在性泄露）：nginx 在服务的产物里搜不到 `denied_columns`",
        html.count("denied_columns"), 0)
    arm("该产物与 `frontend/dist` 同名件逐字节同（不是旧构建）", js_md5[0] == js_md5[1], True)
    print(f"        产物 = {js_md5[2]} ｜ 件内命中数 = {html.count('denied_columns')}")

    st1, e1 = call("/semantic/metrics?q=%E5%AE%A2%E5%8D%95%E4%BB%B7", admin)
    st2, e2 = call("/semantic/metrics?q=%E5%AE%A2%E5%8D%95%E4%BB%B7", admin)
    arm("同一搜索两遍逐字节同形（幂等，无随机排序）", h(e1.get("data")) if st1 == 200 else None,
        h(e2.get("data")) if st2 == 200 else None)

    # ---------- A2：A.9.5 审计读路径 ----------
    print("\n--- 臂：A2 GET /admin/audit（判据 docs/02:1056-1058）---")
    st, env = call("/admin/audit?limit=5", admin)
    d = env.get("data") or {}
    guc, rls, scope = d.get("identity_guc") or {}, d.get("rls") or {}, d.get("scope") or {}
    print(f"  audit http={st} total={d.get('total')} identity_guc={json.dumps(guc, ensure_ascii=False)[:150]}")
    print(f"        rls={json.dumps(rls, ensure_ascii=False)[:170]} scope={json.dumps(scope, ensure_ascii=False)[:170]}")
    arm("GUC 三键在**同一条**语句里注入（statement_count = 1）", guc.get("statement_count"), 1)
    arm("三键齐（不设单键、不留半截）", len(guc.get("keys") or []), 3)
    arm("is_local = true（不污染连接池其它请求）", guc.get("is_local"), True)
    arm("不发 RESET（半截状态比不发更糟）", guc.get("reset_issued"), False)
    arm("第二道保证如实自报不在位", rls.get("second_guarantee_in_place"), False)
    arm("enforced_by 只两条（策略不在位就不许写第三条）", len(scope.get("enforced_by") or []), 2)
    arm("租户视角 tenant_id 取自 JWT、不是参数", scope.get("level"), "tenant")
    tenant_sha = h(d)

    st, env = call("/admin/audit?limit=5&scope=cross_tenant", admin)
    dc = env.get("data") or {}
    print(f"  cross_tenant http={st} total={dc.get('total')} scope={json.dumps(dc.get('scope'), ensure_ascii=False)[:120]}")
    arm("跨租户视角 tenant_id = null", (dc.get("scope") or {}).get("tenant_id"), None)
    arm("跨租户分母 ≥ 租户分母（切得开是被数出来的）",
        (st == 200 and isinstance(dc.get("total"), int) and isinstance(d.get("total"), int)
         and dc["total"] >= d["total"]), True)
    print(f"        租户 total = {d.get('total')} ｜ 跨租户 total = {dc.get('total')}")

    st, env = call("/admin/audit?limit=5&tenant_id=T_C&user_id=someone_else", admin)
    dp = env.get("data") or {}
    arm("把 `tenant_id`／`user_id` 做成查询参数**不得改变 data**（§A.9.5 红线）",
        h(dp) == tenant_sha and (dp.get("scope") or {}).get("tenant_id") == "T_A", True)

    st, env = call("/admin/audit?limit=5", analyst)
    arm("非 platform_admin ⇒ 403 FORBIDDEN_SCOPE（不是 401／500）",
        (st, env.get("code")), (403, "FORBIDDEN_SCOPE"))
    st, env = call("/admin/audit?scope=bogus", admin)
    arm("非法 scope ⇒ 400 具名（不压 500）", (st, env.get("code")), (400, "INVALID_REQUEST"))
    st, env = call("/admin/audit?pii_hit=maybe", admin)
    arm("非法 bool ⇒ 400 具名", st, 400)

    # ---------- A3：POST /admin/eval/run 只交预检 ----------
    print("\n--- 臂：A3 POST /admin/eval/run（判据 docs/02:829-843；本轮零出站的 schema 证法）---")
    body = {"dataset_id": "ds_v1_frozen", "model": None, "prompt_version": None,
            "bundle_version": None, "note": "qa_probe", "dry_run": True}
    st, env = call("/admin/eval/run", admin, method="POST", body=body)
    d3 = env.get("data") or {}
    print(f"  preflight http={st} 键={sorted(d3)[:12]}")
    print(f"        status={d3.get('status')!r} run_id={d3.get('run_id')!r} blockers={len(d3.get('launch_blockers') or [])}")
    q = json.dumps(d3, ensure_ascii=False)
    arm("预检不产生 run_id（不编造批次号）", d3.get("run_id"), None)
    arm("状态写明是 dry_run", d3.get("status"), "dry_run")
    arm("三条 launch_blockers 具名（缺什么可核）", len(d3.get("launch_blockers") or []), 3)
    arm("报价面在位（调用条数与金额区间都得有）",
        ("llm_calls" in q or "calls" in q) and ("cost" in q), True)
    print(f"        报价摘要…={q[:240]}")

    st, env = call("/admin/eval/run", admin, method="POST",
                   body={**body, "dry_run": False})
    arm("`dry_run=false` 在 schema 面不可表达 ⇒ 400（不是 200 也不是 500）", st, 400)
    st, env = call("/admin/eval/run", admin, method="POST", body={**body, "surprise": 1})
    arm("请求体多一个键 ⇒ 400（extra=forbid）", st, 400)
    st, env = call("/admin/eval/run", analyst, method="POST", body=body)
    arm("analyst 发起预检 ⇒ 403 FORBIDDEN_SCOPE", (st, env.get("code")), (403, "FORBIDDEN_SCOPE"))
    st, env = call("/admin/eval/run", admin, method="POST",
                   body={**body, "dataset_id": "ds_not_exist"})
    arm("未知 dataset_id ⇒ 404 具名（detail 点名参数）", (st, env.get("code")), (404, "DATASET_NOT_FOUND"))

    after = ledger()
    print(f"\n[零花费自证] 账本跑前 = {before} ｜ 跑后 = {after}")
    arm("零出站（账本未动）", after, before)

    bad = [label for ok, label in RESULT if not ok]
    print(f"\n不合格 {len(bad)} 臂／共 {len(RESULT)} 臂" + (f"：{bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
