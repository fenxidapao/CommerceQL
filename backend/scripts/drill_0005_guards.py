"""0005 契约护栏的负向对照（注入 → 必红 → 还原 → 必绿）。

只跑**离线**单测（`tests/unit/test_migration_0005_runtime_contract.py`），不需要 PG。
每个注入都必须红**且红的是目标断言** —— "邻居红了"不算对照（那是假对照）。

六处注入覆盖 0005 的全部护栏面：列集（双向 + 补列登记）、枚举↔CHECK（含"从 DDL 独立解析"
这一条防假绿的断言）、NULL 语义的两处成对（约束侧 + 回读侧）、禁用列、访问面。

还原后 sha256 必须与注入前逐字节一致（还原路径本身被验证 —— U-45 教训）。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

MIG = BACKEND / "app" / "repo" / "migrations" / "versions" / "0005_feedback_and_gold_query.py"
CHANNEL = BACKEND / "app" / "repo" / "feedback.py"
TEST = "tests/unit/test_migration_0005_runtime_contract.py"

ORIGINALS = {
    MIG: MIG.read_text(encoding="utf-8"),
    CHANNEL: CHANNEL.read_text(encoding="utf-8"),
}
SHA_BEFORE = {path: hashlib.sha256(text.encode()).hexdigest() for path, text in ORIGINALS.items()}

#: (说明, 目标文件, 锚点, 替换, 必须红的断言)
INJECTIONS: list[tuple[str, Path, str, str, set[str]]] = [
    (
        "① feedback 多出未登记列 extra_col",
        MIG,
        "            is_correct           boolean NOT NULL,",
        "            is_correct           boolean NOT NULL,\n            extra_col            text,",
        {
            "test_feedback_columns_match_channel_and_migration",
            "test_feedback_extra_columns_are_registered",
        },
    ),
    (
        "② _FEEDBACK_REASON_CODES 追加不存在于枚举的取值",
        MIG,
        '''    "data_quality",
    "other",
)''',
        '''    "data_quality",
    "other",
    "bogus_reason",
)''',
        # ⚠️ embedding 测试**不该**红：DDL 由同一元组渲染，两边同源，它红才是假的。
        {"test_reason_code_tuple_matches_enums"},
    ),
    (
        "③ DDL 里的 CHECK 占位符被换成手写字面清单（漏一个值）",
        MIG,
        "            reason_code          text CHECK (reason_code IN ({_REASONS})),",
        "            reason_code          text CHECK (reason_code IN ('wrong_metric_definition', 'other')),",
        # 元组↔枚举仍一致 ⇒ 枚举测试绿；只有"从 DDL 独立解析"的断言必红。
        {"test_reason_code_check_literals_are_embedded_in_ddl"},
    ),
    (
        "④ 去掉 UNIQUE NULLS NOT DISTINCT（唯一键对空归因失效）",
        MIG,
        "                UNIQUE NULLS NOT DISTINCT (task_id, user_id, reason_code)",
        "                UNIQUE (task_id, user_id, reason_code)",
        {"test_feedback_unique_constraint_is_nulls_not_distinct"},
    ),
    (
        "⑤ 回读从 IS NOT DISTINCT FROM 退回 =（空归因永远查不到）",
        CHANNEL,
        "AND reason_code IS NOT DISTINCT FROM :reason_code ",
        "AND reason_code = :reason_code ",
        {"test_channel_read_back_uses_is_not_distinct_from"},
    ),
    (
        "⑥ gold_query 加 tier 列（同一事实的第二份真相）",
        MIG,
        "            bundle_version   text NOT NULL,",
        "            bundle_version   text NOT NULL,\n            tier             text,",
        {"test_gold_query_has_no_tier_column", "test_gold_query_columns_match_section_12_3_plus_registered"},
    ),
    (
        "⑦ 写入通道被扩大（多一个 update 方法）",
        CHANNEL,
        "    async def find_feedback_id(",
        "    async def update_feedback(self) -> None:\n        pass\n\n    async def find_feedback_id(",
        {"test_channel_exposes_only_insert_and_find"},
    ),
]


def _run_tests() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", TEST, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=BACKEND, capture_output=True, text=True, timeout=180,
    )
    return r.returncode, r.stdout + r.stderr


try:
    for idx, (label, path, old, new, targets) in enumerate(INJECTIONS, 1):
        original = ORIGINALS[path]
        assert old in original, f"注入 {idx} 的锚点不存在 —— 源码被改动，演练脚本过期：{label}"
        path.write_text(original.replace(old, new, 1), encoding="utf-8")
        try:
            code, out = _run_tests()
            assert code != 0, f"注入 {idx}（{label}）后护栏竟全绿 —— 它是装饰，不是护栏"
            for target in targets:
                assert target in out, (
                    f"注入 {idx}（{label}）红了，但红的不是目标断言 {target}（邻居红 = 假对照）:\n"
                    f"{out[-2000:]}"
                )
            print(f"[{idx}] {label} -> red as expected ({', '.join(sorted(targets))})")
        finally:
            path.write_text(original, encoding="utf-8")
finally:
    for path, sha in SHA_BEFORE.items():
        now = hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()
        assert now == sha, f"还原后 sha256 不一致！{path.name} 注入前={sha} 还原后={now}"
    print("restored, sha256 identical for all files")

code, out = _run_tests()
assert code == 0, f"还原后应全绿，实为红:\n{out[-2000:]}"
print("after restore -> all green")
