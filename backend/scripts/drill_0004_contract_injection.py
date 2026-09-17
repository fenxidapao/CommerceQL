"""0004 契约护栏的负向对照（注入 → 必红 → 还原 → 必绿）。

注入两处漂移，各自必须红**且红的是目标断言**：
  ① CostEntry↔列：给 _DDL_COST_LEDGER 注入一个多余列 `extra_col` →
     test_cost_entry_fields_and_migration_columns_match 必红（列集不一致）；
  ② enums↔CHECK：给 _BINDING_STATES 追加 'bogus_state' →
     test_binding_state_check_matches_enums 必红。
还原后全绿 + sha256 与注入前一致（还原路径本身被验证 —— U-45 教训）。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIG = BACKEND / "app" / "repo" / "migrations" / "versions" / "0004_cost_ledger_and_query_plan.py"
TEST = "tests/unit/test_migration_0004_runtime_contract.py"

original = MIG.read_text(encoding="utf-8")
sha_before = hashlib.sha256(original.encode()).hexdigest()

INJECTIONS = [
    (
        # ① 多余列：CostEntry 没有它 → 列集比对必红
        "            is_peak          boolean NOT NULL,",
        "            is_peak          boolean NOT NULL,\n            extra_col        text,",
        {"test_cost_entry_fields_and_migration_columns_match"},
    ),
    (
        # ② CHECK 字面多出 bogus 态：enums 比对必红
        #    （embedding 测试**不该**红 —— DDL 由同一元组渲染，两边同源，它红才是假的）
        '_BINDING_STATES = ("resolved_unique", "resolved_default", "ambiguous", "unresolved")',
        '_BINDING_STATES = ("resolved_unique", "resolved_default", "ambiguous", "unresolved", "bogus_state")',
        {"test_binding_state_check_matches_enums"},
    ),
    (
        # ③ DDL 里的 CHECK 占位符被换成**手写字面清单**（漏一个态）：
        #    元组↔枚举仍一致 → enum 测试绿；只有"从 DDL 独立解析"的 embedding 测试必红。
        "            binding_state   text NOT NULL CHECK (binding_state IN ({_STATES})),",
        "            binding_state   text NOT NULL CHECK (binding_state IN ('resolved_unique', 'resolved_default', 'ambiguous')),",
        {"test_ddl_embedding_of_check_literals"},
    ),
]

try:
    for idx, (old, new, targets) in enumerate(INJECTIONS, 1):
        assert old in original, f"注入锚点 {idx} 不存在 —— 源码被改动，演练脚本过期"
        MIG.write_text(original.replace(old, new), encoding="utf-8")
        r = subprocess.run(
            [sys.executable, "-m", "pytest", TEST, "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=BACKEND, capture_output=True, text=True, timeout=120,
        )
        out = r.stdout + r.stderr
        assert r.returncode != 0, f"注入 {idx} 后护栏竟全绿 —— 它是装饰，不是护栏"
        for t in targets:
            assert t in out, f"注入 {idx} 红 了，但红的不是目标断言 {t}（邻居红 = 假对照）:\n{out[-2000:]}"
        print(f"[{idx}] injected -> red as expected ({', '.join(sorted(targets))})")
finally:
    MIG.write_text(original, encoding="utf-8")
    sha_after = hashlib.sha256(MIG.read_text(encoding="utf-8").encode()).hexdigest()
    assert sha_after == sha_before, f"还原后 sha256 不一致！注入前={sha_before} 还原后={sha_after}"
    print("restored, sha256 identical")

# 还原后必须全绿
r = subprocess.run(
    [sys.executable, "-m", "pytest", TEST, "-q", "--no-header", "-p", "no:cacheprovider"],
    cwd=BACKEND, capture_output=True, text=True, timeout=120,
)
assert r.returncode == 0, f"还原后仍有红：\n{r.stdout[-1500:]}"
print("post-restore: all green")
