"""T-37 A1 单变量对照：证明新契约臂会红（不是摆设）。

每条 = 把生产件改坏（可多处联动）→ 跑指定测试 → 期望 rc≠0 → 还原（md5 对撞）。
零额度、零库、零出站。产物只打在 stdout。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]          # reports/w8 -> backend -> CommerceQL
DICT = REPO / "backend/app/present/semantic_dict.py"
ROUTER = REPO / "backend/app/api/routers/semantic.py"
T = "tests/contract/test_semantic_dict_contract.py::"

MUTATIONS = [
    (
        "updated_at 拿 created_at 冒充",
        [(DICT, '"updated_at": None,', '"updated_at": m.created_at,')],
        T + "test_metrics_shape_covers_contract_and_does_not_invent_updated_at",
    ),
    (
        "denied_columns 硬编造（脱离 policy 同源）",
        [(DICT, "list(denied.get(a.logical_name, []))", '["invented_col"]')],
        T + "test_assets_column_count_and_denied_columns_have_one_source",
    ),
    (
        "限流桶 READ → QUERY（渲染字典页吃问答额度）",
        [(ROUTER, "RateLimitBucket.READ", "RateLimitBucket.QUERY")],
        T + "test_bucket_is_read_not_query",
    ),
    (
        "给共享面加角色门禁（analyst 得 403）",
        [
            (ROUTER, "from app.core.enums import RateLimitBucket", "from app.core.enums import RateLimitBucket, Role"),
            (
                ROUTER,
                "from app.api.exceptions import NoDataAsset",
                "from app.api.exceptions import ForbiddenScope, NoDataAsset",
            ),
            (
                ROUTER,
                "        quota = await check_rate_limit(request, RateLimitBucket.READ, ctx)\n        data = semantic_dict.metrics(",
                "        if token.role is not Role.PLATFORM_ADMIN:\n            raise ForbiddenScope(\"x\")\n"
                "        quota = await check_rate_limit(request, RateLimitBucket.READ, ctx)\n        data = semantic_dict.metrics(",
            ),
        ],
        T + "test_analyst_and_admin_get_the_same_dictionary",
    ),
    (
        "缺装载时压成内部错误（不具名）",
        [(ROUTER, "raise NoDataAsset(", "raise RuntimeError(")],
        T + "test_missing_bundle_is_named_422_not_500",
    ),
    (
        "分页壳把 total 报成当前页条数",
        [(DICT, '"total": len(items),', '"total": len(window),')],
        T + "test_filter_and_pagination_are_reconcilable",
    ),
]

PRISTINE = {p: p.read_bytes() for p in (DICT, ROUTER)}
MD5 = {p: hashlib.md5(v).hexdigest() for p, v in PRISTINE.items()}
TEXT = {p: v.decode("utf-8") for p, v in PRISTINE.items()}


def run(test: str) -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", test],
        cwd=str(REPO / "backend"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    print(f"    rc={proc.returncode}  {lines[-1][:80] if lines else (proc.stderr or '')[:80]}")
    return proc.returncode


def restore() -> bool:
    ok = True
    for path, raw in PRISTINE.items():
        path.write_bytes(raw)
        if hashlib.md5(path.read_bytes()).hexdigest() != MD5[path]:
            print(f"    🔴 还原失败：{path.name}")
            ok = False
    return ok


def main() -> int:
    print(f"cwd={REPO}")
    bad = 0
    for label, edits, test in MUTATIONS:
        work = dict(TEXT)
        missing = [old for _p, old, _n in edits if work[_p].count(old) < 1]
        if missing:
            print(f"[尺坏] 锚点不存在：{label} :: {missing[0][:44]!r}")
            bad += 1
            continue
        for path, old, new in edits:
            work[path] = work[path].replace(old, new, 1)
        try:
            for path in {p for p, _o, _n in edits}:
                path.write_bytes(work[path].encode("utf-8"))
            print(f"[变异] {label}")
            if run(test) == 0:
                print("    🔴 改坏了还绿 ⇒ 该臂是摆设")
                bad += 1
        finally:
            if not restore():
                bad += 1
    print(f"[汇总] 不闭合条数 = {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
