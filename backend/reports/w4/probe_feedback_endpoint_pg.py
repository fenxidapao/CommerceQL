"""`POST /feedback` **端点层** ①②③ 实证（W1B 开工指令 §4 的验收要件）。

用法（在 `backend/` 下，Docker Desktop 起着、`commerceql-pg-1` healthy）：

    python ../.venv/Scripts/python.exe reports/w4/probe_feedback_endpoint_pg.py

⚠️ 与既有证据的分工（为什么这个探针存在）：

| 证据 | 覆盖 | 缺口 |
|---|---|---|
| `tests/integration/test_feedback_store_pg.py`（W1B） | store 层往返 / NULL 成对 / 权限负例（真库） | **不经过 HTTP** |
| `tests/contract/test_api_feedback_contract.py`（W4） | 端点层幂等组合 / 竞态 / 身份字段（替身 store） | **不是真库** |
| **本探针** | **HTTP → 真验签链 → 端点 → 真 `FeedbackStore` → 真 PG** 的整条链 | 进程内 TestClient（不起容器） |

🔴 诚实边界：本探针**不**等于"容器内端到端已验证"（W1B §7 那句话仍然成立）——
它没经过 uvicorn/compose/反代那一层。容器层证据需镜像重建后另测（W0 的 compose 在制品）。

跳过策略：PG 不可达 → skip（exit 3），不伪造输出。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.api import errors  # noqa: E402
from app.api.deps import (  # noqa: E402
    GRAPH_RUNTIME_STATE_KEY,
    RUNTIME_STATE_KEY,
    GraphRuntime,
    RateLimited,
    build_runtime,
    build_token_verifier,
)
from app.api.routers import feedback  # noqa: E402
from app.api.state_store import RedisStateStore  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.graph.build import build_graph  # noqa: E402
from app.repo.feedback import FEEDBACK_TABLE  # noqa: E402
from tests.contract.test_api_runner_contract import _DepsHolder  # noqa: E402
from tests.unit._redis_fake import FakeRedis  # noqa: E402

_RW_DSN = os.environ.get("COMMERCEQL_TEST_RW_DSN", "postgresql+psycopg://app_rw:app_rw_pwd@localhost:5432/ecom")

MINT_SCRIPT = _BACKEND / "scripts" / "mint_dev_token.py"
WORKDIR = _BACKEND.parent / ".w4probe"

TASK_ID = "tk_probe_feedback_0001"
SUBMIT_BODY = {
    "task_id": TASK_ID,
    "is_correct": False,
    "reason_code": "wrong_metric_definition",
    "comment": "GMV 应该剔除运费（probe）",
    "corrected_sql": "SELECT 1",
    "correct_result_hint": "应为 1752.10 万元",
}
NULL_REASON_BODY = {"task_id": TASK_ID, "is_correct": False}


def _mint() -> str:
    """铸一枚开发令牌（公钥写到探针目录，供真验签链读取）。失败即中止 —— 令牌是真链的前提。"""
    WORKDIR.mkdir(parents=True, exist_ok=True)
    pem = WORKDIR / "jwt_public.pem"
    out = subprocess.run(
        [sys.executable, str(MINT_SCRIPT), "--tenant-id", "probe_tenant",
         "--user-id", "probe_user", "--role", "analyst", "--scope", "query:read",
         "--public-key-out", str(pem)],
        capture_output=True, text=True, check=True,
    )
    token = out.stdout.strip().splitlines()[-1]
    assert token.count(".") == 2, f"铸币输出末行不是 JWT：{token[:60]}"
    os.environ["JWT_PUBLIC_KEY_PATH"] = str(pem)
    return token


def _pg_ready() -> bool:
    import psycopg

    try:
        with psycopg.connect(_RW_DSN.replace("postgresql+psycopg://", "postgresql://", 1), connect_timeout=3):
            return True
    except Exception:
        return False


def _select_rows(task_id: str) -> list[dict[str, object]]:
    import psycopg

    with psycopg.connect(_RW_DSN.replace("postgresql+psycopg://", "postgresql://", 1), connect_timeout=3) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT feedback_id, task_id, user_id, is_correct, reason_code, "
                f"corrected_sql, correct_result_hint FROM {FEEDBACK_TABLE} WHERE task_id = %s ORDER BY feedback_id",
                (task_id,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def _build_app() -> TestClient:
    """真链装配：`build_runtime`（真 `FeedbackStore`）+ 真验签器；限流用**放行桩**
    （§A.0.6 的桶语义已有契约测试覆盖，本探针要 30 次/分钟内打完 4 发）。"""
    settings = get_settings()
    app = FastAPI()
    errors.install_exception_handlers(app)
    app.include_router(feedback.router, prefix="/api/v1")

    engine = create_async_engine(_RW_DSN, pool_pre_ping=False)
    runtime = build_runtime(settings=settings, pools=_Pools(engine), redis=FakeRedis())  # type: ignore[arg-type]
    setattr(app.state, RUNTIME_STATE_KEY, runtime)
    setattr(
        app.state,
        GRAPH_RUNTIME_STATE_KEY,
        GraphRuntime(
            graph=build_graph(),
            store=RedisStateStore(FakeRedis()),  # type: ignore[arg-type]
            verifier=build_token_verifier(settings),
            new_deps=_DepsHolder("refuse_intent"),
        ),
    )
    return TestClient(app, raise_server_exceptions=False)


class _Pools:
    """`ThreePools` 的最小替身：本探针只消费 `pools.metadata`（反馈走元数据池）。

    ⚠️ 不用 `build_three_pools(settings)`：那会按 **容器内** DSN（`pg` 主机名）建三个池，
    宿主机上解析不了。探针只需要 metadata 池指向真库。
    """

    def __init__(self, engine: object) -> None:
        self.metadata = engine  # type: ignore[assignment]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sqla(dsn: str) -> str:
    """原生 psycopg DSN → SQLAlchemy 形态（Settings 三 DSN 无默认值，必须进程内自给）。"""
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


def main() -> int:
    if not _pg_ready():
        print("[skip] PG 不可达（起 Docker Desktop / commerceql-pg-1 后重跑）")
        return 3

    # Windows 坑（同 tests 教训）：psycopg async 不能跑在 ProactorEventLoop 上，
    # TestClient 的 anyio portal 会按 policy 建 loop ⇒ 必须在装配前换成 Selector。
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # N-02 读写分离：Settings 校验禁止两 DSN 同值；分析池用 app_ro（探针不触它，仅过校验）。
    os.environ.setdefault("DATABASE_URL", _sqla(_RW_DSN))
    os.environ.setdefault("ANALYTICS_DB_URL", _sqla(_RW_DSN).replace("app_rw:app_rw_pwd", "app_ro:app_ro_pwd", 1))

    token = _mint()
    client = _build_app()
    evidence: dict[str, object] = {}

    # ── 要件①：首次提交 → 落行，id 形如 fb_… ──
    r1 = client.post("/api/v1/feedback", json=SUBMIT_BODY, headers=_auth(token))
    assert r1.status_code == 200, f"① 首次提交应 200，实得 {r1.status_code}: {r1.text}"
    fb1 = r1.json()["data"]["feedback_id"]
    assert fb1.startswith("fb_") and len(fb1) == 35, f"① id 形态不符：{fb1}"
    rows_after_first = _select_rows(TASK_ID)
    assert len(rows_after_first) == 1 and rows_after_first[0]["feedback_id"] == fb1, rows_after_first
    evidence["①首次提交"] = {
        "http": r1.status_code,
        "feedback_id": fb1,
        "queued_for_review": r1.json()["data"]["queued_for_review"],
        "db_row": rows_after_first[0],
    }

    # ── 要件②：同三元组再提交 → 同一条 id，且行数不变 ──
    r2 = client.post("/api/v1/feedback", json=SUBMIT_BODY, headers=_auth(token))
    assert r2.status_code == 200, r2.text
    fb2 = r2.json()["data"]["feedback_id"]
    count_after_second = len(_select_rows(TASK_ID))
    assert fb2 == fb1, f"② 幂等命中应返回同一条：{fb1} vs {fb2}"
    assert count_after_second == 1, f"② 行数应仍为 1，实得 {count_after_second}"
    evidence["②同键重提交"] = {"http": r2.status_code, "feedback_id": fb2, "db_row_count": count_after_second}

    # ── 要件③：reason_code = null 的重复提交也命中（NULLS NOT DISTINCT / IS NOT DISTINCT FROM）──
    r3a = client.post("/api/v1/feedback", json=NULL_REASON_BODY, headers=_auth(token))
    r3b = client.post("/api/v1/feedback", json=NULL_REASON_BODY, headers=_auth(token))
    assert r3a.status_code == 200 and r3b.status_code == 200, (r3a.text, r3b.text)
    fb3a, fb3b = r3a.json()["data"]["feedback_id"], r3b.json()["data"]["feedback_id"]
    assert fb3a == fb3b, f"③ null 归因重复提交应同一条：{fb3a} vs {fb3b}"
    all_rows = _select_rows(TASK_ID)
    assert len(all_rows) == 2, f"③ 应共 2 行（一条 wrong_metric_definition + 一条 NULL），实得 {len(all_rows)}"
    evidence["③null归因重提交"] = {
        "http": (r3a.status_code, r3b.status_code),
        "feedback_id": fb3a,
        "db_rows_total": len(all_rows),
        "reason_codes": sorted(str(r["reason_code"]) for r in all_rows),
    }

    print(json.dumps({"verdict": "PASS", "evidence": evidence}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RateLimited as exc:  # pragma: no cover - 放行桩下不可达，防御性
        print(f"[fail] 被限流（不应发生）：{exc}")
        sys.exit(2)
