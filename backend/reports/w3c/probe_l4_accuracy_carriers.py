"""W3C 探针：核 W7 转述的「L4 更准」口径——**三处载体**到底存不存在（2026-09-29）。

背景：W3A 查明"L4 在场 ≠ L4 更准"这件事，W7 转述它"已有现成口径、无需新建载体"，
请 W3C 认领。本探针把这件事从**转述**变成**读数**：零 LLM、零 DB、零服务，
只读代码与两个 eval 资产（`eval/dataset_v1_frozen.json` / `eval/gold_query_seed_v1.json`）。

用法（工作目录必须 = `backend/`）：

    .venv/Scripts/python.exe reports/w3c/probe_l4_accuracy_carriers.py

四节，逐条对应 W7 的四句声称：

| 节 | W7 声称 | 本节回答 |
|---|---|---|
| ① | 期望列在 `eval/gold_query_seed_v1.json` | 那个文件里有没有"期望绑定"这类字段 |
| ② | 实际绑出的列在 `query_plan.plan_summary` 的 dimensions/metrics | 那两格记的是 **PLAN 的意图** 还是 **BIND 的结果** |
| ③ | `CandidateRef` 无打分器标识 ⇒ 绑后分不出 L1/L4 | 层分不分得开、缺的到底是哪个标识 |
| ④ | 计数器每查询一个标量 ⇒ 归不到具体错列 | 一次判定的**产出形态**（几条绑定、覆盖几个概念） |

⚠️ 本探针**不改任何生产件**，也不出 G-1…G-8（那归 W6）。
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/

from app.binding.filters import ConceptResolution, FilterOutcome
from app.binding.four_layer import TauConfig, decide
from app.binding.grain import GrainIndex
from app.binding.scores import RerankScore, ScoreOutcome
from app.core.contracts import CandidateRef
from app.planner.schemas import Plan
from app.repo.query_plan import QUERY_PLAN_COLUMNS

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
BUNDLE = ROOT / "semantic" / "bundle_2026.09.14.1.yaml"

MODEL_ID = "deepseek-flash"
PROMPT_VERSION = "l4-score-v1"


def _line(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def _load(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _section_expected() -> None:
    """① 期望侧：两个 eval 资产里到底有什么字段。"""
    _line("① 期望侧 —— `gold_query_seed_v1.json` / 冻结集里有没有『期望绑定』")
    frozen = _load(ROOT / "eval" / "dataset_v1_frozen.json")
    seed = _load(ROOT / "eval" / "gold_query_seed_v1.json")
    cases = frozen["cases"]
    seeds = seed["seeds"]
    print(f"冻结集：{len(cases)} 条，字段集 = {sorted(cases[0])}")
    print(f"gold  ：{len(seeds)} 条，字段集 = {sorted(seeds[0])}")

    for name, rows in (("冻结集", cases), ("gold  ", seeds)):
        tokens = sorted({t for r in rows for t in r.get("must_contain", ())})
        with_signal = sum(1 for r in rows if r.get("must_contain"))
        print(
            f"\n{name} `must_contain`：带信号的题 = {with_signal}/{len(rows)}，"
            f"全部取值 = {tokens}"
        )
        shapes = sorted({type(r.get("gold_result_cols")).__name__ for r in rows})
        values = sorted({r.get("gold_result_cols") for r in rows}, key=repr)
        print(f"{name} `gold_result_cols` 的类型 = {shapes}，取值 = {values[:8]}")

    print(
        "\n⇒ 结论：两个资产里**没有**『概念 X 应绑到列 Y』这种字段；"
        "最接近列名的只有 `must_contain`（**SQL 文本子串**，词表见上），"
        "以及 `gold_result_cols`（**结果列的个数**，连列名都不是）。"
    )


def _section_actual() -> None:
    """② 实际侧：`plan_summary` 是谁写的、记的是什么。"""
    _line("② 实际侧 —— `query_plan.plan_summary` 记的是 PLAN 的意图还是 BIND 的结果")
    plan = Plan.model_validate(
        {
            "metrics": [{"name": "gmv", "caliber": "已支付订单金额合计"}, {"name": "order_cnt"}],
            "dimensions": ["stat_date"],
            "grain": "day",
        }
    )
    print("喂给 `Plan` 的概念：metrics[].name = ['gmv','order_cnt']，dimensions = ['stat_date']")
    print(f"`Plan.to_summary()` → {plan.to_summary().model_dump()}")
    print(
        "\n⚠️ `to_summary()` 的实现 = `metrics=[m.name for m in self.metrics]` + "
        "`dimensions=list(self.dimensions)`（`planner/schemas.py:334-345`）"
        "\n   ⇒ 这里出现的字符串**就是模型写进计划的概念名**，与绑定结果无关。"
    )
    print(f"\n`query_plan` 的列集（`repo/query_plan.py`）= {QUERY_PLAN_COLUMNS}")
    print(
        "⇒ 落库面里**没有** `bindings` 一列 ⇒ 真正的绑定结果（被选中的列 ref + 层）"
        "\n   只活在 graph state 的 `bindings` 键里（`nodes/bind.py:135`），**零落库**。"
    )


def _tau() -> TauConfig:
    return TauConfig(
        value=0.20,
        epsilon=0.05,
        model_id=MODEL_ID,
        prompt_version=PROMPT_VERSION,
        calibrated_at="2026-09-29T00:00:00Z",
        report_ref="reports/w3c/calibration.md",
    )


def _index() -> GrainIndex:
    from app.semantics import SemanticBundleRuntime, load_bundle

    return GrainIndex.build(SemanticBundleRuntime(load_bundle(BUNDLE)))


def _section_layer() -> None:
    """③ 层归属侧：L1/L4 分不分得开；缺的是哪个标识。"""
    _line("③ 层归属侧 —— 绑后分不分得开 L1/L4；`CandidateRef` 缺的是什么")
    index = _index()
    tau = _tau()

    l1 = decide(
        ConceptResolution(concept="客单价", source="alias", refs=("order_paid.pay_amount",)),
        FilterOutcome(ordered=("order_paid.pay_amount",)),
        grain_index=index,
        question_grain=None,
        tau=tau,
        l4=ScoreOutcome(failed=True, reason="no_l4_scores_injected"),
    )
    l4 = decide(
        ConceptResolution(
            concept="客单价",
            source="alias",
            refs=("order_paid.pay_amount", "order_paid.goods_amount"),
        ),
        FilterOutcome(ordered=("order_paid.pay_amount", "order_paid.goods_amount")),
        grain_index=index,
        question_grain=None,
        tau=tau,
        l4=ScoreOutcome(
            scores=(
                RerankScore(
                    candidate_id="order_paid.pay_amount",
                    value=0.91,
                    model_id=MODEL_ID,
                    prompt_version=PROMPT_VERSION,
                ),
                RerankScore(
                    candidate_id="order_paid.goods_amount",
                    value=0.36,
                    model_id=MODEL_ID,
                    prompt_version=PROMPT_VERSION,
                ),
            )
        ),
    )
    for label, decision in (("L1 路径", l1), ("L4 路径", l4)):
        ref = decision.bindings[0] if decision.bindings else None
        print(
            f"{label}：state={decision.state.value} layer={decision.layer.value} "
            f"bindings={decision.bindings}"
        )
        print(f"    ⇒ 记录层 = {decision.layer.value}，被选列 ref = {ref.asset_id if ref else None}")

    unresolved = decide(
        None,
        FilterOutcome(),
        grain_index=index,
        question_grain=None,
        tau=tau,
        l4=ScoreOutcome(failed=True, reason="no_l4_scores_injected"),
    )
    print(
        f"\n未解析路径：state={unresolved.state.value} layer={unresolved.layer.value} "
        f"bindings={unresolved.bindings} reason={unresolved.reason}"
        "\n    ⚠️ ⇒ `unresolved` 也把 layer 记成 **L1** ⇒ `binding_layer_total{L1}` 的分母"
        "\n       混进了『概念根本没解析出来』，不是纯粹的『L1 定稿』。"
    )

    print(
        f"\n`CandidateRef` 字段集 = "
        f"{[f.name for f in dataclasses.fields(CandidateRef)]}"
        "\n⇒ **层是有的**（每条 binding 都带决定层）；缺的是**打分器标识**"
        "\n   （`RerankScore` 有 `model_id`/`prompt_version`，转成 `CandidateRef` 时被丢掉）"
        "\n   ⇒ 分不开的不是 L1/L4，而是『这个 L4 分是哪个模型/prompt 产的』。"
    )


def _section_metrics() -> None:
    """⑤ 计量面：两个 Counter 能不能推出"L4 且判成唯一"。"""
    _line("⑤ 计量面 —— 两个 Counter 是边际分布，联合分布不可得")
    source = (BACKEND / "app" / "api" / "deps.py").read_text(encoding="utf-8")
    for lineno, line in enumerate(source.splitlines(), 1):
        if "observe_binding_" in line and "metrics." in line:
            print(f"deps.py:{lineno}: {line.strip()}")
    print(
        "\n⇒ `BindingEvent` 上 `state` 与 `layer` 是**同一个对象**的两个字段，"
        "\n   但适配器把它们喂进**两个独立 Counter** ⇒ 只有两个边际分布，"
        "\n   『L4 且 resolved_unique』这种联合口径**算不出来**（要联合就得改计量面）。"
    )


def _section_grain() -> None:
    """④ 粒度：一次判定绑几个概念。"""
    _line("④ 粒度 —— 一次 `bind` 判定到底绑几个概念、覆盖谁")
    source = (BACKEND / "app" / "graph" / "nodes" / "bind.py").read_text(encoding="utf-8")
    for lineno, line in enumerate(source.splitlines(), 1):
        if "_concept_of(plan" in line or "plan.metrics[0].name" in line:
            print(f"bind.py:{lineno}: {line.strip()}")

    plan = Plan.model_validate({"metrics": [{"name": "gmv"}, {"name": "order_cnt"}]})
    try:
        from app.graph.nodes.bind import _concept_of

        picked = _concept_of(plan, "T_A 的 GMV 和订单数")
        print(f"\n实测 `_concept_of(plan with metrics=['gmv','order_cnt'])` = {picked!r}")
    except Exception as exc:  # 探针：导入失败只影响这一格，如实打印
        print(f"\n`_concept_of` 导入失败（只影响本格）：{type(exc).__name__}: {exc}")

    print(
        "\n⇒ 每请求只判 **1 个概念** = `plan.metrics[0].name`（无指标时退回归一化问句），"
        "\n   `dimensions` 与其余指标**完全不参与绑定**（W4 自定并已登记待裁："
        "`nodes/bind.py` §二）。"
    )


def main() -> int:
    print("W3C 探针：核「L4 更准」口径的三处载体（零 LLM / 零 DB）")
    _section_expected()
    _section_actual()
    _section_layer()
    _section_grain()
    _section_metrics()
    _line("小结（读数，不是结论）")
    print(
        "① 期望侧：**不存在**（无『期望绑定』字段；`must_contain` 是 SQL 文本子串弱代理，"
        "词表仅 3 个 token）\n"
        "② 实际侧：`plan_summary` = PLAN 的概念名，**不是**绑定结果；绑定结果零落库\n"
        "③ 层归属：绑定输出**带层**；缺的是打分器标识（不是 L1/L4 之分）\n"
        "④ 粒度：每请求只判 1 个概念（`metrics[0]`）\n"
        "⑤ 计量：两 Counter 是**边际分布**，联合分布不可得；且 `unresolved` 也算 L1"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
