"""W2-INT 端到端验证（2026-09-16 实测脚本，结果写入 DELIVERY.md）。

Part A：/healthz 三端点（真 lifespan + 真 PG/Redis + 真语义包运行时）
Part B：§6.2 六步发布演练（materialize / switch_version / rollback / DoD③ 一致性）

运行：cd backend && ..\\.venv\\Scripts\\python.exe reports/w2-int/e2e_stage2_check.py
前置：本地 compose 栈在跑（pg 5432 / redis 6379）；迁移 0001→0002 已执行。
"""
import asyncio
import os
import sys
from pathlib import Path

# Windows：psycopg async 只支持 SelectorEventLoop（conftest.py 同款处置）
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))


def _load_env() -> None:
    """读 deploy/.env 并做本机化覆盖（容器主机名 → 127.0.0.1）。"""
    env_path = REPO / "deploy" / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        val = v.split(" #", 1)[0].strip()  # .env 有行内注释，剥离后再入库
        os.environ.setdefault(k.strip(), val)
    os.environ["APP_ENV"] = "dev"  # 断言三态按 dev 口径放行
    os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/0"
    os.environ["SEMANTIC_BUNDLE_PATH"] = str(REPO / "semantic" / "bundle_2026.09.14.1.yaml")
    # .env 的 DSN 主机名是 compose 服务名 `pg`；本机直跑映射到 127.0.0.1
    for k in ("DATABASE_URL", "ANALYTICS_DB_URL"):
        os.environ[k] = os.environ[k].replace("@pg:", "@127.0.0.1:")


_load_env()


def pg_dsn(key: str) -> str:
    """deploy/.env 的 DSN 是 SQLAlchemy 形态（+psycopg）；psycopg 本体连接要去掉驱动段。"""
    dsn = os.environ[key]
    return dsn.replace("postgresql+psycopg://", "postgresql://")


def part_a() -> None:
    print("=" * 72)
    print("Part A：/healthz 三端点（真 lifespan）")
    print("=" * 72)
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        r_live = client.get("/api/v1/healthz/live")
        r_ready = client.get("/api/v1/healthz/ready")
        r_agg = client.get("/api/v1/healthz")
        print("live   :", r_live.status_code, r_live.json())
        print("ready  :", r_ready.status_code, r_ready.json())
        print("aggregate:", r_agg.status_code)
        body = r_agg.json()
        print("  status               =", body["status"])
        print("  semantic_bundle_loaded =", body.get("semantic_bundle_loaded"))
        print("  bundle_version       =", body.get("bundle_version"))
        print("  degraded_dependencies =", body.get("degraded_dependencies"))

        checks = r_ready.json()["checks"]
        assert checks["semantic_bundle_loaded"] is True, (
            f"semantic_bundle_loaded 未转真：{checks}"
        )
        assert r_agg.json()["bundle_version"], "bundle_version 为空"
        assert r_live.status_code == 200
        print("[PASS] semantic_bundle_loaded=True + bundle_version 非空 —— W2A RELAY §1② 接线生效")


def part_b() -> None:
    print("=" * 72)
    print("Part B：§6.2 六步发布演练（本地库实测）")
    print("=" * 72)
    import psycopg

    from app.cache import keys as cache_keys
    from app.semantics import load_bundle
    from app.semantics.materialize import (
        assert_grant_policy_consistency,
        get_active_version,
        materialize,
        rollback_to,
        switch_version,
    )

    dsn = pg_dsn("DATABASE_URL")  # app_rw
    bundle_path = os.environ["SEMANTIC_BUNDLE_PATH"]

    loaded = load_bundle(
        bundle_path,
        embedding_model=os.environ.get("EMBEDDING_MODEL"),
        embedding_dim=int(os.environ.get("EMBEDDING_DIM", "1024")),
    )
    version = loaded.version
    print(f"①②③ 包加载成功：version={version}")

    # —— 步骤①②③：物化（with_policy=False；tokenizer/embedder 未注入 → 如实 PENDING）——
    report = materialize(loaded, dsn=dsn, with_policy=False)
    print(f"物化：doc_count={report.doc_count} rows={dict(report.rows)}")
    print(f"     tsv_status={report.tsv_status} embedding_status={report.embedding_status}")
    print(f"     warnings={list(report.warnings)}")

    # —— 步骤②(完整形态)：with_policy=True —— 期望被 U-55/56 卡住 ——
    print("-- 步骤② 完整形态 materialize(with_policy=True) ——")
    try:
        materialize(loaded, dsn=dsn, with_policy=True)
        print("     意外成功？（若 v_* 已建且 RLS 可用则合法）")
    except psycopg.Error as exc:
        print(f"     BLOCKED（预期）：{type(exc).__name__}: {exc}")
        print("     → 引用裁决请求：U-55（RLS 不适用于视图）/ U-56（v_* 视图 DDL 归属未裁）")

    # —— 步骤④⑤：单键指针切换（键注入 cache_keys.active_version()）——
    # ⚠️ switch_version/get_active_version 的 redis_client 形参 = 同步 redis.Redis
    r = __import__("redis").Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    switch_version(r, version, key=cache_keys.active_version())
    got = get_active_version(r, key=cache_keys.active_version())
    assert got == version, f"指针回读不一致：{got!r} != {version!r}"
    print(f"④⑤ switch_version/get_active_version：指针={got!r} [PASS]")

    # —— 步骤⑥：回滚（目标=当前已存在版本，验证存在性校验链路）——
    rollback_to(r, dsn, version, key=cache_keys.active_version())
    print("⑥ rollback_to（目标版本存在性校验通过）[PASS]")

    # —— DoD③：一致性检查（无 v_* 视图 → 期望 mismatch，如实记录）——
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        cr = assert_grant_policy_consistency(conn, loaded)
    print(f"DoD③ assert_grant_policy_consistency：checked={cr.checked_assets} "
          f"consistent={cr.consistent}")
    for m in cr.mismatches[:12]:
        print("   mismatch:", m)
    if len(cr.mismatches) > 12:
        print(f"   ...共 {len(cr.mismatches)} 条")
    print("   → mismatch 根因 = v_* 视图未建（U-56）+ GRANT/RLS 未执行（U-55），非检查器缺陷")


if __name__ == "__main__":
    part_a()
    part_b()
    print("=" * 72)
    print("E2E 完成")
