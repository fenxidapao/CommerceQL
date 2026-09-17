"""结果指纹（07 §8.8）—— 缓存/去重/repair 无效重试检测的判据源。

归属窗口：W2D（docs/08 §4.1：`app/exec/**`）。

口径（07 §8.8 逐字）：
`fingerprint = sha256(规范化列名有序表 + 规范化行数据 + 生效参数)`，**不含 tenant_id**
（指纹只用于同租户内去重与幂等 —— 含 tenant_id 反而让"跨租户同数据"无法对账，
且 tenant_id 已在缓存键层隔离，`cache/keys.py` 的铁律 1）。

⚠️ 输入必须是**归一化后**的列与行 —— 指纹要在"同一份逻辑数据"上稳定：
`Decimal('1.50')` 与 `"1.50"` 必须产出同一指纹，否则 repair 前后的等价比对会假性漂移。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

__all__ = ["result_fingerprint"]


def _canonical(value: Any) -> Any:
    """递归转成 JSON 可序列化的规范形态。

    ⚠️ 防御性覆盖 `Decimal`（→ str 保精度）：口径要求输入是**归一化后**的行，
    但 params 是调用方给的原始映射 —— params 里出现 Decimal 不能炸，
    且其字符串形态必须与归一化路径一致（同一数值 = 同一指纹）。
    """
    if isinstance(value, Decimal):
        return None if value.is_nan() else str(value)
    if isinstance(value, tuple):
        return [_canonical(v) for v in value]
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    return value


def result_fingerprint(
    *,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    params: Mapping[str, Any] | None = None,
) -> str:
    """sha256(规范化列名有序表 + 规范化行数据 + 生效参数)。

    - 列名**有序**（"同数据不同列序"是不同的结果集，07 口径如此）；
    - 行**有序**（未 ORDER BY 的结果集行序本就不稳定 —— 那是上游问题，
      指纹如实反映它，恰好能让"无序结果被二次消费"暴露出来）；
    - `params` 键名排序后并入（生效参数变了，指纹必须变）。
    """
    payload = json.dumps(
        {
            "columns": [str(c) for c in columns],
            "rows": [_canonical(tuple(row)) for row in rows],
            "params": _canonical(dict(params or {})),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
