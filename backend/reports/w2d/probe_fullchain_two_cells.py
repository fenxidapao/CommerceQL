"""总控"GATE3 与 EXECUTE 至今一帧未见"的读数探针 —— **离线全链夹具能不能兑现这两格？**

归属窗口：W2D（`backend/reports/w2d/**`）。只读、不写库、不改被测代码。

--------------------------------------------------------------------------
读数（PG/Redis 都不需要，纯替身）
--------------------------------------------------------------------------
默认绿档夹具（`make_chain()`）一轮的 stage 序列：

    intent → schema_linking → plan_ready → sql_ready → gate_passed → executing

且 `executing` 之后确有 `data` 帧、`ScriptExecutor.fetch_calls == 1`、
`explain_calls == 1`（gate3 真走了 EXPLAIN 入口）。

⇒ **两格的判据在离线侧今天就可立** —— 不需要 W2D 再开任何口子。
两格在生产为 0 的成因**不在 exec 侧**，是 `U-121`（gate1 因端口形状恒 R05 ⇒ 图到不了 gate3）。

--------------------------------------------------------------------------
本探针顺带量出的**判据不完整**（不是"不可立"）
--------------------------------------------------------------------------
| 断言 | 条数 |
|---|---|
| `"executing" in stages`（肯定） | **2**（`test_decision_table_d_e.py:147/162`） |
| `"gate_passed" in stages`（肯定） | **0** |
| `"gate_passed" not in stages`（否定） | 2（同上文件 `:146/161`，warn/skipped 路径） |

⇒ **`gate_passed` 只有否定面，没有肯定面** —— "三闸门全 PASS ⇒ 发 `gate_passed`"
这条正路径在契约层无人钉。而本探针证明它**离线可达**（今天就能写）。

跑法（**必须用真 PG 之外的环境也行**，本探针不连库）：
    cd backend && ../.venv/Scripts/python.exe reports/w2d/probe_fullchain_two_cells.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

#: `backend/`（`reports/w2d/xxx.py` → parents[2]）。
_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND))

# `tests/conftest.py` 的占位环境（本探针不经 pytest，必须自己注入）
_PLACEHOLDER_ENV: dict[str, str] = {
    "APP_ENV": "dev",
    "DEEPSEEK_API_KEY": "sk-placeholder-not-a-real-key",
    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
    "DATABASE_URL": "postgresql+psycopg://app_rw:placeholder@pg:5432/ecom",
    "ANALYTICS_DB_URL": "postgresql+psycopg://app_ro:placeholder@pg:5432/ecom",
    "REDIS_URL": "redis://redis:6379/0",
    "JWT_PUBLIC_KEY": "placeholder-public-key",
    "JWT_ISSUER": "https://issuer.invalid/",
    "OAUTH_TENANT_ID": "placeholder-tenant",
    "OAUTH_CLIENT_ID": "placeholder-client",
    "OAUTH_CLIENT_SECRET": "placeholder-secret",
    "CORS_ALLOWED_ORIGINS": "",
    "ENABLE_RESULT_CACHE_CONFIRMED": "false",
}

for _key, _value in _PLACEHOLDER_ENV.items():
    os.environ.setdefault(_key, _value)

if sys.platform == "win32":  # 沿 conftest 的 U-39 处置（SelectorEventLoop）
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from tests.contract._fullchain_deps import GREEN_EXPLAIN, make_chain, run_chain  # noqa: E402


def _stages(frames: list[tuple[str, dict[str, object]]]) -> list[str]:
    return [str(payload.get("stage")) for event, payload in frames if event == "stage"]


def main() -> int:
    chain = make_chain()
    frames, outcome = run_chain(chain)
    stages = _stages(frames)

    print("=" * 78)
    print("离线全链夹具（默认绿档）一轮")
    print("=" * 78)
    print(f"  事件序列   = {[e for e, _ in frames]}")
    print(f"  stage 序列 = {stages}")
    print(f"  outcome    = {outcome.status}")
    print()
    print(f"  『gate_passed』出现 = {'gate_passed' in stages}")
    print(f"  『executing』出现   = {'executing' in stages}")
    print(f"  fetch_calls   = {chain.executor.fetch_calls}   ← 真走到了 execute")
    print(f"  explain_calls = {chain.executor.explain_calls}   ← gate3 真走了 EXPLAIN 入口（U-63）")
    print(f"  GREEN_EXPLAIN = {GREEN_EXPLAIN}")
    print()
    print("  结论：两格在离线侧可立判据；生产为 0 的成因在 U-121（gate1 端口形状），不在 exec。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
