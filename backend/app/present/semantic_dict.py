"""L3 语义字典投影 —— `GET /semantic/metrics`（§A.7.1）与 `GET /semantic/assets`（§A.7.2）。

层号：L3｜归属窗口：W8（T-37，2026-10-05）｜判据与契约落笔权：本窗（架构窗 10-04 停用）

--------------------------------------------------------------------------
一、本文件为什么存在（不写会怎样）
--------------------------------------------------------------------------
`app/semantics/` 是 L1，它给的是**模型对象**（`Metric` / `Asset`，带 `tuple`、`Literal`、
`default_binding` 这类内部结构）。契约 §A.7.1／§A.7.2 要的是**扁平 JSON**。
中间这层翻译如果写进 router（L5），就出现"聚合与投影在接入层"的第二份真相 ——
`admin_eval.py` 的文件头已经为同一件事立过规矩（网格必须在 L3 算），这里照那条规矩走。

--------------------------------------------------------------------------
二、四件"契约有、包里没有"的事（这是本文件存在的主要理由）
--------------------------------------------------------------------------
现算（`load_bundle(semantic/bundle_2026.09.14.1.yaml)`，2026-10-05 16:0x）：
metrics **9** 条、active assets **8** 条，键集实测如下 ——

| 契约键 | 包内 | 本文件怎么给 |
|---|---|---|
| `bundle_version` | ❌ 逐条没有（只有 `meta.version`） | 由**运行时激活版本**统一填（`runtime.active_version()`），逐条同值 ⇒ 引用它等于引用"这批读的是哪个包"，不是"这条指标改过" |
| `updated_at` | ❌ 0/9 | **如实 `null`**。包里有 `created_at`／`version`，但**不拿它们冒充** `updated_at`（改了名 = 造第二份真相）；`created_at` 与 `version` 另作为**契约外附加键**如实透出（§A.7.1 补记登记） |
| `column_count` | ❌ 0/8（有 `columns[]`） | 现算 `len(asset.columns)` —— 是**派生量**不是包内字段，补记里点名 |
| `denied_columns` | ❌ 0/8（在 `policies.deny_columns`，形态 `<logical>.<col>`） | 由 `runtime.policy()["deny_columns"]` **按前缀分组去前缀**得到 ⇒ 同一份 deny 事实只有一个来源（loader 步骤③ 还断言它与列上的 `sensitive` 双向一致） |

🔴 **draft 指标**（`sell_through_rate`）按 `models.py:174-194` 的校验可以缺
`expression`／`default_aggregation`／`unit`／`owner`／`default_predicates`／`time_basis`
⇒ 这些一律如实 `null`，并靠附加键 `status` 让前端能说"这条是 draft、口径未定"，
而不是把"没定"显示成"空公式"。`runtime.metrics()` 刻意**不过滤 draft**（`runtime.py:349-359`
的理由：过滤掉 = 让消费方只剩"当它不存在"一种处理），本投影沿用同一立场。

--------------------------------------------------------------------------
三、多租户口径（§A.7.1／§A.7.2 那段 10-05 裁定的代码形态）
--------------------------------------------------------------------------
口径字典 = **平台级共享面** ⇒
① 响应里**没有** `scope` 键（既不是 `"cross_tenant"` 也不是别的）——那标量属于"读了别人的私有数据"
   那一类面（§A.9.4／§A.9.5），挂在这里会把"同一份共享定义"说成"跨租户读取"；
② 文案与键名不出现"本租户口径"；
③ `tenant_id`／`user_id` **不是**参数（传了也不改变任何东西，见契约测试的对照臂）。

--------------------------------------------------------------------------
四、匹配口径（契约只写"模糊搜索／过滤数据域"，代码必须把它定死）
--------------------------------------------------------------------------
`domain` = **大小写敏感的精确匹配**（包内 `domain` 是枚举形态的短串，做子串匹配会让
`order` 命中 `orders` 之类的意外命中）；`q` = **大小写不敏感的子串**，metrics 匹配
`name`／`display_name`／`synonyms[]`，assets 匹配 `logical_name`／`physical_asset`／`description`。
分页 = §A.0.5（`limit` 默认 50、上限 500，`offset` ≥ 0），`total` = **过滤后的条数**。
"""

from __future__ import annotations

from typing import Any

from app.semantics.models import Asset, Metric
from app.semantics.runtime import SemanticBundleRuntime

__all__ = ["assets", "metrics"]


def _page(items: list[dict[str, Any]], limit: int, offset: int) -> dict[str, Any]:
    """§A.0.5 的分页壳（`total` 是过滤后的总数，与 `items` 的长度分开）。"""
    window = items[offset : offset + limit]
    return {
        "items": window,
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(window) < len(items),
    }


def _hit(needle: str | None, *haystacks: str) -> bool:
    """`q` 的匹配口径：大小写不敏感子串；空串 = 不过滤。"""
    if not needle:
        return True
    low = needle.lower()
    return any(low in h.lower() for h in haystacks)


def _deny_map(runtime: SemanticBundleRuntime) -> dict[str, list[str]]:
    """`<logical>.<col>` 形态的 deny 列 → `{logical: [col, …]}`（保持包内序、去重）。"""
    out: dict[str, list[str]] = {}
    for ref in runtime.policy().get("deny_columns") or ():
        logical, _, col = str(ref).partition(".")
        if col and col not in out.setdefault(logical, []):
            out[logical].append(col)
    return out


def _metric_row(m: Metric, bundle_version: str | None) -> dict[str, Any]:
    return {
        "name": m.name,
        "display_name": m.display_name,
        "expression": m.expression,
        "default_aggregation": m.default_aggregation,
        "unit": m.unit,
        "owner": m.owner,
        "domain": m.domain,
        "definition_note": m.definition_note,
        "default_predicates": list(m.default_predicates),
        "synonyms": list(m.synonyms),
        "bundle_version": bundle_version,
        "updated_at": None,
        # ---- 契约外附加键（§A.7.1 补记登记；来源 = 包内实有字段，不是自造）----
        "status": m.status,
        "created_at": m.created_at,
        "version": m.version,
        "time_basis": m.time_basis,
    }


def _asset_row(a: Asset, denied: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "logical_name": a.logical_name,
        "physical_asset": a.physical_asset,
        "grain": a.grain,
        "freshness_sla": a.freshness_sla,
        "owner": a.owner,
        "certified": a.certified,
        "domain": a.domain,
        "column_count": len(a.columns),
        "denied_columns": list(denied.get(a.logical_name, [])),
    }


def metrics(
    runtime: SemanticBundleRuntime,
    *,
    domain: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """§A.7.1：指标口径字典（含 draft，逐条如实给可用性状态）。"""
    version = runtime.active_version()
    rows = [
        _metric_row(m, version)
        for m in runtime.metrics()
        if (domain is None or m.domain == domain) and _hit(q, m.name, m.display_name, *m.synonyms)
    ]
    return _page(rows, limit, offset)


def assets(
    runtime: SemanticBundleRuntime,
    *,
    domain: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """§A.7.2：认证资产清单（只列**通过质量准入**的资产，`runtime.assets()` 已过滤）。"""
    denied = _deny_map(runtime)
    rows = [
        _asset_row(a, denied)
        for a in runtime.assets()
        if (domain is None or a.domain == domain) and _hit(q, a.logical_name, a.physical_asset, a.description)
    ]
    return _page(rows, limit, offset)
