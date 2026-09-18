"""`app/repo/query_plan.py` 护栏的负向对照（注入 → 必红 → 还原 → 必绿）。

注入四处漂移，各自必须红**且红的是目标断言**：
  ① 加一个 `update_query_plan` 方法 → `test_only_insert_method_is_exposed` 必红
     （"只写"是表语义，权限层也只给 INSERT/SELECT）；
  ② `_binding()` 去掉 `CAST(... AS jsonb)` → `test_plan_json_binds_as_jsonb_cast` 必红
     （psycopg3 `text → jsonb` 无隐式转换）；
  ③ 给 `QUERY_PLAN_COLUMNS` 追加一个迁移里不存在的列 `extra` →
     `test_columns_match_migration_ddl_bidirectionally` 必红
     （同时验证**列解析器不瞎**：只认已知列名的解析器会在这里放过）；
  ④ `_INSERT_SQL` 追加 `ON CONFLICT (task_id) DO NOTHING` →
     `test_module_source_has_no_on_conflict` 必红（撞重不许被静默）。

还原后全绿 + sha256 与注入前一致（还原路径本身被验证 —— U-45 教训）。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
STORE = BACKEND / "app" / "repo" / "query_plan.py"
TEST = "tests/unit/test_query_plan_store.py"

original = STORE.read_text(encoding="utf-8")
sha_before = hashlib.sha256(original.encode()).hexdigest()

_VALUES_LINE = """f"VALUES ({', '.join(_binding(c) for c in QUERY_PLAN_COLUMNS)})"
)"""

#: ④ 的注入形态：语句尾部追加 ON CONFLICT（静默撞重）
_VALUES_WITH_CONFLICT = """f"VALUES ({', '.join(_binding(c) for c in QUERY_PLAN_COLUMNS)})"
    " ON CONFLICT (task_id) DO NOTHING"
)"""

INJECTIONS: list[tuple[str, str, set[str]]] = [
    (
        # ① 越权方法面
        "    async def insert_query_plan(",
        '    async def update_query_plan(self, task_id: str) -> None:\n'
        '        """非法：计划行不可改。"""\n\n'
        "    async def insert_query_plan(",
        {"test_only_insert_method_is_exposed"},
    ),
    (
        # ② 去掉 jsonb CAST
        '    return f"CAST(:{name} AS jsonb)" if name in _JSONB_COLUMNS else f":{name}"',
        '    return f":{name}"',
        {"test_plan_json_binds_as_jsonb_cast"},
    ),
    (
        # ③ 写入面多出一列（迁移里没有）
        '    "confidence",\n)',
        '    "confidence",\n    "extra",\n)',
        {"test_columns_match_migration_ddl_bidirectionally"},
    ),
    (
        # ④ ON CONFLICT（静默撞重）
        _VALUES_LINE,
        _VALUES_WITH_CONFLICT,
        {"test_module_source_has_no_on_conflict"},
    ),
]

try:
    for idx, (old, new, targets) in enumerate(INJECTIONS, 1):
        assert old in original, f"注入锚点 {idx} 不存在 —— 源码被改动，演练脚本过期"
        STORE.write_text(original.replace(old, new, 1), encoding="utf-8")
        r = subprocess.run(
            [sys.executable, "-m", "pytest", TEST, "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=BACKEND, capture_output=True, text=True, timeout=120,
        )
        out = r.stdout + r.stderr
        assert r.returncode != 0, f"注入 {idx} 后护栏竟全绿 —— 它是装饰，不是护栏"
        for t in targets:
            assert t in out, f"注入 {idx} 红了，但红的不是目标断言 {t}（邻居红 = 假对照）:\n{out[-2000:]}"
        print(f"[{idx}] injected -> red as expected ({', '.join(sorted(targets))})")
finally:
    STORE.write_text(original, encoding="utf-8")
    sha_after = hashlib.sha256(STORE.read_text(encoding="utf-8").encode()).hexdigest()
    assert sha_after == sha_before, f"还原后 sha256 不一致！注入前={sha_before} 还原后={sha_after}"
    print("restored, sha256 identical")

r = subprocess.run(
    [sys.executable, "-m", "pytest", TEST, "-q", "--no-header", "-p", "no:cacheprovider"],
    cwd=BACKEND, capture_output=True, text=True, timeout=120,
)
assert r.returncode == 0, f"还原后仍有红：\n{r.stdout[-1500:]}"
print("post-restore: all green")
