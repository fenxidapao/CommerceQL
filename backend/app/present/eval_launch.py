"""L3 评测发起预检投影 —— `POST /api/v1/admin/eval/run` 的 **dry-run 面**（§A.9.1）。

层号：L3｜归属窗口：W8（T-37，2026-10-05）｜判据与契约落笔权：本窗

--------------------------------------------------------------------------
一、本轮交付的是"预检"，不是"发起"（这条线必须写在代码里）
--------------------------------------------------------------------------
§A.9.1 原文（`docs/02:829-843`）给的是 `{"run_id": "run_01J8XA", "status": "queued"}` ——
那要求**服务端真有一个运行登记表＋一条会把 166 题打完的通道**。现读盘上两件都不存在：

- 没有评测运行表：`backend/app/repo/migrations/versions/` 里的迁移**没有一张**建 eval／run
  关系（尺：`grep -ic "create table" versions/*.py` 逐件看表名），而本模块落笔时新增的 0006
  是审计**读**授权 ⇒ 计数一律现读（`_migration_inventory`），不写死在上一次读数里；
- 跑批通道在进程外：执行体是仓库根 `eval/runner.py:538 main()`（argparse CLI），
  `backend/app/**` 里不 import 它（排除本文件后 `grep -rn "import runner|from eval|eval\\.runner" backend/app` ⇒ 0 命中）。

所以本模块**只回答两个问题**：这批要发多少条调用、大概多少钱。
真发起在代码面上**不可表达**（router 的 DTO 里 `dry_run` 只接受字面 `true`），
而不是"实现了、运行时拒绝"—— 前者不需要新错误码，后者必然要发明第 29 个码。

--------------------------------------------------------------------------
二、报价的两个口径互相**对撞**，不是一个数
--------------------------------------------------------------------------
| 口径 | 来源 | 用途 |
|---|---|---|
| **观测外推**（本模块给的主口径） | 盘上 `config.live = true` 的真打批次：每案成本分位、每案 LLM 节点访问数 | 与"这批实际会花多少"同源，含 repair 轮次与提前拒答的真实形状 |
| **价表乘数** | `app/llm/budget.py:122-131` 的 `PRICES`（峰 / 非峰两档，逐格） | 把"非峰实测"推到"峰档上界" |

⚠️ 观测批次**不自报模型**（`config` 键集里没有 `model`，逐份可核）⇒
"这些钱是哪个模型花的"不可证 ⇒ 输出里 `model_attribution.evidenced_by_basis` 恒 `False`，
并且价表乘数只用 `deepseek-flash` 的两档比（该模型的峰档 = 非峰档的 **2 倍**，逐格可核）。
每份批次用 `classify_tier(它自己的 generated_at)` 现算档位 ⇒ 只有基准批全落非峰时，
"峰档上界"这一格才有意义（把非峰实测当峰档报价 = 少报一倍）。

⚠️ **文件数 ≠ 批次数**：盘上 `live=true` 的产物里存在同一批次的两份副本
（同 `git_rev` ＋ 同 `generated_at` ＋ 同总成本，只是文件名不同）。
⇒ 批次数按这三元组去重（`distinct_batches`），文件数另给（`artifacts_available`），
两个数都进响应 —— 只报一个就会让读的人以为是两批**独立**观测。

--------------------------------------------------------------------------
三、`LLM_NODE_NAMES` 是**第二份抄本**，由测试钉住而不是由 import 保证
--------------------------------------------------------------------------
权威来源是 `app/graph/build.py:395` 的 `_LLM_NODE_TASKS`（7 个走 DeepSeek 的节点）。
本模块**不 import 它**：`app.present` 是 L3、`app.graph` 是 L4，
向上 import 会直接违反 `.importlinter` 的 R-DEP-1 层序（那才是真的架构问题）。
⇒ 抄本留在本地，等值由 `tests/contract/test_eval_launch_dryrun_contract.py` 钉：
`LLM_NODE_NAMES == frozenset(_LLM_NODE_TASKS)`。测试文件可以跨层 import（它不是产品代码）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any, Final

from app.llm import budget
from app.present import artifacts, eval_report

__all__ = ["dry_run", "launch_blockers", "quote"]

#: 走 LLM 的节点名（= 一次问答会产生几条上游调用）。权威源见文件头第三节。
LLM_NODE_NAMES: Final[frozenset[str]] = frozenset(
    {"normalize", "intent", "plan", "gen_sql", "present", "repair", "bind"}
)

#: 用于"峰 / 非峰乘数"的模型（§A.9.1 的默认档，也是价表里唯一给全两档且被实测用过的）。
_RATIO_MODEL: Final[str] = "deepseek-flash"

#: 迁移目录（`_migration_inventory` 的唯一取数面）。
_MIGRATIONS_DIR: Final[Path] = Path(__file__).resolve().parents[1] / "repo" / "migrations" / "versions"


def _migration_inventory() -> tuple[int, str, str]:
    """现读 `versions/` 下的四位前缀迁移数与首末号（不写死）。

    🔴 这条自述的上一版写的是「只有 `0001`–`0005` 五个文件」，而 0006（审计读授权）
    一落地它就成了假事实 —— 而且红得很难看：端点照旧 200、报价照旧对，只有这句话在骗人。
    ⇒ 自描述计数只许现读，不许抄上一次读数。
    """
    revs = sorted(p.name[:4] for p in _MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.py"))
    if not revs:
        return 0, "—", "—"
    return len(revs), revs[0], revs[-1]


def launch_blockers() -> list[dict[str, str]]:
    """真发起这一支今天缺什么（逐条给"可核的事实"，不是待办情绪）。"""
    count, first, last = _migration_inventory()
    return [
        {
            "missing": "eval_run_registry",
            "detail": f"库里没有评测运行表：`app/repo/migrations/versions/` 现读 {count} 个迁移"
                      f"（{first}–{last}），逐件 `grep -i 'create table'` 里没有 eval／run 关系"
                      f" ⇒ §A.9.1 的 `run_id`／`status=queued` 无出处，不许编一个",
        },
        {
            "missing": "in_process_runner",
            "detail": "执行体是仓库根的 `eval/runner.py:538 main()`（argparse CLI），`app/**` 不 import 它"
                      " ⇒ 端点若『看起来发起了』就必然是在骗调用方",
        },
        {
            "missing": "approved_spend",
            "detail": "本端点一次真跑 = 出站打到 LLM；派单本轮为**零额度** ⇒ 代码面上不可表达该分支"
                      "（`dry_run` 只接受字面 `true`）",
        },
    ]


def _live_batches() -> list[dict[str, Any]]:
    """只取**真打过**的批次（`config.live is True`），逐份自带出处。"""
    out: list[dict[str, Any]] = []
    for run_id in artifacts.run_ids():
        doc = artifacts.load_run(run_id)
        cfg = doc.get("config") or {}
        if cfg.get("live") is not True:
            continue
        records = doc.get("records") or []
        costs = [
            float(r["cost_cny"])
            for r in records
            if isinstance(r.get("cost_cny"), int | float)
        ]
        calls = sum(
            1 for r in records for node in (r.get("nodes") or []) if node in LLM_NODE_NAMES
        )
        summary = doc.get("summary") or {}
        frozen = doc.get("frozen_evidence") or {}
        hash_check = ((frozen.get("checks") or {}).get("dataset_content_hash") or {}).get("actual")
        out.append(
            {
                "artifact": run_id,
                "generated_at": doc.get("generated_at"),
                "git_rev": doc.get("git_rev"),
                "cases": len(records),
                "llm_calls": calls,
                "cost_cny_total": summary.get("cost_cny_total"),
                "cost_cny_per_case": (
                    {"min": min(costs), "median": float(median(costs)), "max": max(costs)} if costs else None
                ),
                "dataset_content_hash": hash_check,
                "tier_observed": budget.classify_tier(_as_aware(doc["generated_at"])).value,
            }
        )
    return out


def _as_aware(iso: str) -> datetime:
    dt = datetime.fromisoformat(str(iso))
    if dt.tzinfo is None:  # classify_tier 明文拒绝 naive（会随机器时区漂）
        raise ValueError(f"批次 generated_at 不带时区，无法定档：{iso!r}")
    return dt


def _peak_ratio() -> dict[str, Any]:
    """峰 / 非峰乘数：逐格取 `PRICES[deepseek-flash]` 的两档 `cache_miss` 价现算。"""
    off = budget.PRICES[_RATIO_MODEL][budget.Tier.OFF_PEAK].cache_miss
    peak = budget.PRICES[_RATIO_MODEL][budget.Tier.PEAK].cache_miss
    return {
        "model": _RATIO_MODEL,
        "off_peak_cache_miss_usd_per_mtok": str(off),
        "peak_cache_miss_usd_per_mtok": str(peak),
        "multiplier": str((peak / off).quantize(Decimal("0.01"))),
        "source": "app/llm/budget.py 的 PRICES（逐格照抄 PRD §12.3）",
    }


def _dataset_row(dataset_id: str) -> dict[str, Any] | None:
    """走 §A.9.2 的公开投影（`eval_report.datasets()`），不在这里再开第二次读文件。"""
    for raw in eval_report.datasets()["items"]:
        row: dict[str, Any] = raw
        if row["dataset_id"] == dataset_id:
            return row
    return None


def quote(dataset_id: str, *, requested_model: str | None = None) -> dict[str, Any]:
    """这批题要发多少条调用、大概多少钱 —— **只读盘上产物，零出站**。"""
    ds = _dataset_row(dataset_id)
    if ds is None:
        raise LookupError(dataset_id)
    cases_total = int(ds["case_count"])
    batches = _live_batches()
    same = [b for b in batches if b["dataset_content_hash"] == ds.get("content_hash")]
    basis = same or batches
    per_case_calls = [b["llm_calls"] / b["cases"] for b in basis if b["cases"]]
    per_case_max_cost = [
        b["cost_cny_per_case"]["max"] for b in basis if b["cost_cny_per_case"]
    ]  # 量纲 = ¥/案（批内最贵那一案），不再除条数
    mean_case_cost = [
        b["cost_cny_total"] / b["cases"] for b in basis if b["cost_cny_total"] is not None and b["cases"]
    ]
    ratio = Decimal(_peak_ratio()["multiplier"])
    low = round(min(mean_case_cost) * cases_total, 6) if mean_case_cost else None
    high = round(max(mean_case_cost) * cases_total, 6) if mean_case_cost else None
    conservative = round(max(per_case_max_cost) * cases_total, 6) if per_case_max_cost else None
    now_tier = budget.classify_tier(datetime.now(UTC))
    return {
        "dataset_id": dataset_id,
        "cases_total": cases_total,
        "basis": {
            "mode": (
                "same_dataset" if same else ("extrapolated_from_other_dataset" if batches else "no_live_batch")
            ),
            "why": (
                "基准批次的 `frozen_evidence` 与被请求集内容哈希一致 ⇒ 可直接比"
                if same
                else (
                    "被请求集没有真打批次 ⇒ 按另一集的每案口径外推；"
                    "红队题多在闸门／计划层早退，每案调用数预计**低于**外推值 ⇒ 这是**上界**"
                    "（保守方向 = 多估，同 `budget.py` 未知模型按最贵计价的既有裁定）"
                    if batches
                    else "盘上没有 `config.live = true` 的批次产物 ⇒ 没有任何观测口径，"
                         "estimate 逐格给 `null`，不许拿价表乘一个猜测的条数当报价"
                )
            ),
            "artifacts": basis,
            "artifacts_available": len(batches),
            "distinct_batches": len(
                {(b["git_rev"], b["generated_at"], b["cost_cny_total"], b["cases"]) for b in batches}
            ),
        },
        "estimate": {
            "llm_calls_low": round(min(per_case_calls) * cases_total) if per_case_calls else None,
            "llm_calls_high": round(max(per_case_calls) * cases_total) if per_case_calls else None,
            "cost_cny_off_peak_low": low,
            "cost_cny_off_peak_high": high,
            "cost_cny_off_peak_conservative": conservative,
            "cost_cny_peak_upper_bound": (
                None if high is None else float((Decimal(str(high)) * ratio).quantize(Decimal("0.000001")))
            ),
            "method": "每案实测值 × cases_total（批内求和／条数，不是模型侧估算）",
        },
        "tier": {
            "now": now_tier.value,
            "at_peak_now": now_tier is budget.Tier.PEAK,
            "rule": "app/llm/budget.classify_tier（北京工作日 09–12／14–18 = 峰）",
            "peak_multiplier": _peak_ratio(),
        },
        "model_attribution": {
            "requested_model": requested_model,
            "evidenced_by_basis": False,
            "detail": "观测批次的 `config` 不自报 model ⇒ 这些钱对应哪个模型**不可证**；"
                      "引用本报价不得写成『某模型的单价 × 条数』",
        },
    }


def dry_run(request_body: dict[str, Any]) -> dict[str, Any]:
    """§A.9.1 的 **dry-run** 响应体（`data` 那一层）。

    ⚠️ `status` 取 `"dry_run"` 是**本窗自订的子状态**（§A.9.1 原文只有 `queued`），
    已随端点一起写进 `docs/02 §A.9.1 补记`；`code` 仍是 `OK`（业务子状态不进 `code`，
    理由见 `app/api/dto/common.py` 模块头）。
    """
    dataset_id = str(request_body["dataset_id"])
    return {
        "run_id": None,
        "status": "dry_run",
        "launched": False,
        "echo": request_body,
        "quote": quote(dataset_id, requested_model=request_body.get("model")),
        "launch_blockers": launch_blockers(),
        "how_to_launch": "评测运行登记表 ＋ 进程内执行通道 ＋ 已批额度三件齐 ⇒ 见 docs/02 §A.9.1 补记",
    }
