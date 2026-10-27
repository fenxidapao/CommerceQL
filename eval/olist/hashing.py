"""Olist 轨的两个哈希：共享 `content_hash` + Olist 自定 `full_hash`。

为什么需要两个
--------------
`build_frozen_set.case_content_hash` 的 keep-list 只有 10 个语义字段
（`case_id/question/domain/expected_behavior/gold_sql/business_knowledge_required/
must_contain/must_not_contain/clarify_expected/refuse_reason`），
**盖不住** 口径期望（`expect`）、指标/资产声明（`metrics`/`assets`）与 `eval_tenant`
—— 改这些字段时共享哈希不变。W2 的 N-13 验真因此并列第二个 Olist 自定的
`full_hash`，两者都查；**不改共享 `case_content_hash` 本体**（避免制造第二份共享口径）。

边界
----
· 只复用 `build_frozen_set` 的纯函数；不调用其 `main()`。
· 源 YAML 的 stamp 写在文件头注释：`# content_hash: sha256:...` / `# full_hash: ...`；
  冻结件写顶层同名字段。本模块只**读/算**，写盘归 `build_dataset.py`（它有 P0 守卫）。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Final

#: 与 `build_frozen_set.case_content_hash` 的 keep-list 逐字一致；
#: `test_olist_dataset_contract` 会用一次 `case_content_hash` 复算对账，防漂移。
CONTENT_FIELDS: Final[tuple[str, ...]] = (
    "case_id",
    "question",
    "domain",
    "expected_behavior",
    "gold_sql",
    "business_knowledge_required",
    "must_contain",
    "must_not_contain",
    "clarify_expected",
    "refuse_reason",
)

#: Olist 自定的补充字段：口径期望 + 指标/资产声明 + 租户。
EXTRA_FIELDS: Final[tuple[str, ...]] = ("expect", "metrics", "assets", "eval_tenant")

FULL_FIELDS: Final[tuple[str, ...]] = CONTENT_FIELDS + EXTRA_FIELDS

STAMP_RE: Final = re.compile(r"^# (content_hash|full_hash): (sha256:[0-9a-f]{64})$")


def _canonical(obj: Any) -> str:
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def case_full_hash(cases: Iterable[Mapping[str, Any]]) -> str:
    """Olist 口径完整性哈希：10 个共享字段 + expect/metrics/assets/eval_tenant。"""
    canon = [
        {key: case.get(key) for key in FULL_FIELDS}
        for case in sorted(cases, key=lambda item: str(item["case_id"]))
    ]
    return "sha256:" + hashlib.sha256(_canonical(canon).encode("utf-8")).hexdigest()


def read_stamps(path: str | Path) -> dict[str, str]:
    """读源 YAML 头部的两个 stamp（只扫前 40 行，避免误吃正文里的同名文本）。"""
    stamps: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for index, line in enumerate(fh):
            if index >= 40:
                break
            match = STAMP_RE.match(line.strip())
            if match:
                stamps[match.group(1)] = match.group(2)
    return stamps


def stamp_lines(content_hash: str, full_hash: str) -> tuple[str, str]:
    """`build_dataset --stamp` 要写进文件头的两行（不含换行）。"""
    return f"# content_hash: {content_hash}", f"# full_hash: {full_hash}"
