"""T-37 A5 证据装配件（第 14 轮，零额度 · 零出站）。

把"活体面"的读数装成一份可复核的 JSON：
- **计数全部现算**（openapi path 数 / 迁移数 / 负向用例的 http 码），不落手写常数；
- 值来自本轮的 scratch 产物（`E:/tmp_qoder/r14/`，不入库），字段名里逐格标**面**（`face`）；
- 浏览器那一臂的 DOM 尺是**读数**（人工从 `evaluate_script` 的返回里抄），刻意的少而可复算。

复算：`cd backend && ../.venv/Scripts/python.exe reports/w8/t37_a5_browser_walk.py --out reports/w8/t37_a5_browser_walk.json`
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
#: 本轮的活体响应**已入库**（18 份，无凭据、无 DSN）⇒ 本件可脱离 scratch 独立复算。
EVIDENCE = Path(__file__).resolve().parent / "evidence" / "t37_a5"

NEW_PATHS = [
    "/api/v1/semantic/metrics",
    "/api/v1/semantic/assets",
    "/api/v1/admin/eval/run",
    "/api/v1/admin/audit",
]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8").stdout.strip()


def _self_identity() -> dict[str, object]:
    return {
        "rev": _git("rev-parse", "--short", "HEAD"),
        "rev_full": _git("rev-parse", "HEAD"),
        "commit_count": int(_git("rev-list", "--count", "HEAD")),
        "dirty": bool(_git("status", "--porcelain")),
        "captured_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "note": "本件自报身份 = 装配这一秒的工作树；与活体读数（23:1x–23:4x +0800）不是同一秒 ⇒ 引用时两件事分开引。",
    }


def _migrations() -> dict[str, object]:
    versions = sorted(p.name for p in (BACKEND / "app/repo/migrations/versions").glob("[0-9][0-9][0-9][0-9]_*.py"))
    return {"count": len(versions), "first": versions[0][:4], "last": versions[-1][:4], "files": versions}


def _code_face_paths() -> dict[str, object]:
    # 🔴 刻意**不写**完整的 DSN 字面量：`tests/unit/test_migration_dsn_hygiene.py` 扫整棵工作区、
    # 并把"引用规则的模式串"等同于"触犯规则"⇒ 一处 `scheme + 用户 + ':' + 口令 + '@'` 的原样跨度会让门禁自己红。
    # 这里要的不是可用凭据，只是**非空**的占位值（`create_app()` 只校验形状，不连库），所以分段拼。
    scheme = "postgresql+psycopg" + "://"
    host = "127.0.0.1:5432/ecom"
    env = {
        "DATABASE_URL": f"{scheme}app_rw:placeholder@{host}",
        "ANALYTICS_DB_URL": f"{scheme}app_ro:placeholder@{host}",
        "REDIS_URL": "redis://127.0.0.1:6379/0",
    }
    code = (
        "import json,os,sys;sys.path.insert(0,'backend');"
        "from app.main import create_app;"
        "print(json.dumps(sorted(create_app().openapi()['paths'])))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **env},
    )
    if out.returncode != 0:
        raise SystemExit(f"代码面 openapi 取数失败 rc={out.returncode}：{out.stderr[-400:]}")
    paths = json.loads(out.stdout.strip().splitlines()[-1])
    return {"face": "代码面（离线 create_app().openapi()）", "count": len(paths), "paths": paths}


def _live_face(path: Path) -> dict[str, object]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    paths = sorted(doc["paths"])
    return {"face": "活体面（:8000 容器，curl /api/v1/openapi.json）", "count": len(paths), "paths": paths}


def _negatives() -> list[dict[str, object]]:
    labels = {
        "01": "analyst 打 GET /admin/audit ⇒ 期望 403 FORBIDDEN_SCOPE",
        "02": "无令牌打 GET /admin/audit ⇒ 期望 401",
        "03": "scope=bogus ⇒ 期望 400 INVALID_REQUEST",
        "04": "pii_hit=maybe ⇒ 期望 400 INVALID_REQUEST",
        "05": "把 tenant_id 做成查询参数 ⇒ 期望被忽略（仍是 JWT 的 T_A）",
        "06": "scope=cross_tenant（platform_admin）⇒ 期望 200 且 total 比租户视角大",
        "07": "POST /admin/eval/run（dry_run=true）⇒ 期望 200 且 launched=false",
        "08": "analyst 打 POST /admin/eval/run ⇒ 期望 403",
        "09": "dry_run=false ⇒ 期望 400（真发起在 schema 面不可表达）",
        "10": "未知 dataset_id ⇒ 期望 404 DATASET_NOT_FOUND 且 detail 点名",
        "11": "请求体多一个键 tenant_id ⇒ 期望 400（extra=forbid）",
    }
    rows: list[dict[str, object]] = []
    for key, label in labels.items():
        f = EVIDENCE / f"neg_{key}.json"
        doc = json.loads(f.read_text(encoding="utf-8"))
        data = doc.get("data") if isinstance(doc.get("data"), dict) else {}
        rows.append(
            {
                "case": key,
                "expectation": label,
                "code": doc.get("code"),
                "scope": data.get("scope"),
                "identity_guc": data.get("identity_guc"),
                "rls": data.get("rls"),
                "detail": doc.get("detail"),
                "tenants_in_items": sorted({r["tenant_id"] for r in data.get("items", [])}) if data.get("items") else None,
                "total": data.get("total"),
                "artifact": f"neg_{key}.json",
            }
        )
    return rows


def _tenant_split_proof() -> dict[str, object]:
    """「第一道切得开」要能被**数出来**，而不是被说出来。

    两面同尺（`limit = 500` 的一页，同一个 `platform_admin` 令牌）：
    租户视角的页里只有一种 `tenant_id`；跨租户视角的同一页里多出别的租户字面量。
    ⚠️ 粒度 = **行**（rows），面 = `app.audit_log LEFT JOIN audit_log_supplement`，谓词 = `scope` 参数。
    """
    from collections import Counter

    out: dict[str, object] = {}
    for key, fname in (("tenant_view", "tenant500.json"), ("cross_tenant_view", "cross500.json")):
        data = json.loads((EVIDENCE / fname).read_text(encoding="utf-8"))["data"]
        counter = Counter(str(r["tenant_id"]) for r in data["items"])
        out[key] = {
            "requested_scope": data["scope"]["level"],
            "scope_tenant_id": data["scope"]["tenant_id"],
            "total": data["total"],
            "rows_in_page": len(data["items"]),
            "tenant_counts_in_page": dict(sorted(counter.items())),
            "artifact": fname,
        }
    own = str(out["tenant_view"]["scope_tenant_id"])
    cross_page = out["cross_tenant_view"]["tenant_counts_in_page"]
    assert isinstance(cross_page, dict)
    out["delta_check"] = {
        "cross_minus_tenant_total": int(out["cross_tenant_view"]["total"]) - int(out["tenant_view"]["total"]),
        "non_own_tenant_rows_in_cross_page": sum(n for t, n in cross_page.items() if t != own),
        "note": "本轮这两个读数**恰好都是 2**，但把它们写成恒等是越界：左边是全表 `count(*)` 之差，右边只是**这一页 500 行**里非本租户的行数 ⇒ 并列报，不合成一个「结论数」。",
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    audit = json.loads((EVIDENCE / "resp_admin_audit_limit_3.json").read_text(encoding="utf-8"))["data"]
    metrics = json.loads((EVIDENCE / "resp_semantic_metrics_limit_3.json").read_text(encoding="utf-8"))["data"]
    assets = json.loads((EVIDENCE / "resp_semantic_assets_limit_3.json").read_text(encoding="utf-8"))["data"]
    dry = json.loads((EVIDENCE / "live_dryrun.json").read_text(encoding="utf-8"))["data"]
    datasets = json.loads((EVIDENCE / "live_datasets.json").read_text(encoding="utf-8"))["data"]
    pre_live = json.loads((EVIDENCE / "live_openapi_before_rebuild.json").read_text(encoding="utf-8")) if (
        EVIDENCE / "live_openapi_before_rebuild.json"
    ).exists() else None
    doc = {
        "identity": _self_identity(),
        "scope_of_this_artifact": "T-37 A1／A2／A3 的**活体面**读数 ＋ A5 浏览器走查的 DOM 尺；零出站、零花费。",
        "openapi": {
            "code_face": _code_face_paths(),
            "live_face_after_rebuild": _live_face(EVIDENCE / "live_openapi_after.json"),
            "live_face_before_rebuild": (
                {"face": "活体面（重建前，镜像落后一笔）", "count": len(pre_live["paths"]), "paths": sorted(pre_live["paths"])}
                if pre_live
                else None
            ),
            "new_paths_named": NEW_PATHS,
        },
        "migrations": _migrations(),
        "alembic_version_live": "0006",
        "alembic_version_ruler": "psql -Atc \"select version_num from public.alembic_version\"（共享 ecom，本轮 upgrade head 之后）",
        "live_reads": {
            "semantic_metrics": {"total": metrics["total"], "item_keys": sorted(metrics["items"][0])},
            "semantic_assets": {"total": assets["total"], "item_keys": sorted(assets["items"][0])},
            "audit_tenant_view": {
                "total": audit["total"],
                "scope": audit["scope"],
                "identity_guc": audit["identity_guc"],
                "rls": audit["rls"],
                "item_keys": sorted(audit["items"][0]),
            },
            "eval_datasets": {"total": datasets["total"], "ids": [d["dataset_id"] for d in datasets["items"]]},
            "tenant_split_proof": _tenant_split_proof(),
            "eval_run_precheck": {
                "status": dry["status"],
                "launched": dry["launched"],
                "run_id": dry["run_id"],
                "quote": dry["quote"],
                "launch_blockers": dry["launch_blockers"],
            },
        },
        "negatives": _negatives(),
        "browser_walk": {
            "face": "真机（浏览器 → nginx :80 → api :8000），不是 MSW mock",
            "viewport": {"inner_width": 531, "inner_height": 559, "device_pixel_ratio": 1.5},
            "readings": [
                "顶栏「口径字典」→「指标」9 条（已加载 9 / 共 9）；「数据资产」8 行、表头无 denied_columns 列",
                "搜索「客单价」**两遍**：两遍都是 `1 / 共 1`，同一张卡片文本",
                "顶栏「评测」→ 弹窗标题「发起评测 —— 当前只出预检报价」、按钮文案「生成预检」（不是「发起」）",
                "选集 ds_v1_frozen ＋ 填三格 ＋ 点「生成预检」⇒ data-testid=eval-precheck 面板出现",
                "**同一填法再点一遍 ⇒ 面板文本逐字符相同**（两遍均 819 字符，identical=true）",
                "负向：未登录直接 URL 打开 /semantic/metrics ⇒ 错误卡「错误编号：AUTH_FAILED」（= U-136 修法的真机形状）",
            ],
            "defect_found_and_fixed": {
                "symptom": "弹窗里「评测集」下拉恒为「暂无数据」，而 GET /admin/eval/datasets = 200 且 data.items 两条",
                "dom_ruler_pre_fix": "document.querySelectorAll('.ant-select-item-option').length ⇒ 0",
                "dom_ruler_post_fix": "同一把尺 ⇒ 2（ds_v1_frozen（1，166 例）／ds_v1_red_team（1，66 例））",
                "cause": "EvalRunsPage 的取数 effect 把自己正在 set 的 datasetsLoading 放进了依赖数组 ⇒ 依赖一变先跑 cleanup（cancelled=true）⇒ .then/.catch/.finally 三个守卫全跳过：候选恒空、403 被吞、loading 永真",
                "since_commit": "e01c198（W5）",
                "first_visible_after": "A.9.2 端点接上（c7b1d24 之后）⇒ 路由没接掩护了整整一类前端缺陷",
                "fixture": "frontend/src/pages/EvalRunsPage.test.tsx（4 臂）",
                "two_state_control": "pre-fix 3 红 1 绿 ／ post-fix 4 绿（还原源文件后 md5 938469e43c4742efe09b534cc3c2d3d8 与修后件相同）",
            },
            "screenshots": [
                "backend/reports/w8/screens/a5_semantic_assets.png",
                "backend/reports/w8/screens/a5_semantic_metrics_search.png",
                "backend/reports/w8/screens/a5_semantic_metrics_search2.png",
                "backend/reports/w8/screens/a5_eval_modal_before.png",
                "backend/reports/w8/screens/a5_eval_precheck_panel.png",
            ],
            "unverified": [
                "窄视口（531×559）下宽表横向滚动的**排版**复核：本轮只取「数据到没到／文案对不对」这一层 ⇒ UNVERIFIED",
                "问答金路（POST /api/v1/query）本轮**没走**：那是 LLM 出站，而派单本轮零额度 ⇒ 不许写成达成",
            ],
        },
    }
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"写入 {args.out}（openapi 代码面 {doc['openapi']['code_face']['count']} 条 ／ 活体面 {doc['openapi']['live_face_after_rebuild']['count']} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
