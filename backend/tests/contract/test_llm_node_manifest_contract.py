"""LLM 节点清单一致性契约（W8 第 51 轮）。

两份清单必须**双向一致**，且判据是**代码事实**（节点是否触达 LLM 出站），不是人抄：

- 生产侧：`app/graph/build.py::_LLM_NODE_TASKS`（决定 §10.2 客户端硬超时）；
- 评测侧：`eval/harness.py::LLM_CALLING_NODES`（决定评测节点超时下界）。

历史缺陷：`bind` 触达 `deps.llm`（`nodes/bind.py:180` 的 L4 精排）却在其中一份清单里缺席
⇒ 生产侧那一跳只拿 0.2s、评测侧拿 162s（"评测比生产宽松"）。本测试禁止该形态再次出现。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BUILD = REPO / "backend" / "app" / "graph" / "build.py"
HARNESS = REPO / "eval" / "harness.py"
NODES_DIR = REPO / "backend" / "app" / "graph" / "nodes"


def _ensure_import_path() -> None:
    os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://app_rw:x@pg:5432/ecom")
    os.environ.setdefault("ANALYTICS_DB_URL", "postgresql+psycopg://app_ro:x@pg:5432/ecom")
    for p in (str(REPO / "backend"), str(REPO / "eval")):
        if p not in sys.path:
            sys.path.insert(0, p)


def _prod_manifest() -> set[str]:
    """生产清单 —— **运行时导入**（不解析源码字面量，免得正则与实现一起漂）。"""
    _ensure_import_path()
    from app.graph.build import _LLM_NODE_TASKS

    assert _LLM_NODE_TASKS, "生产清单为空"
    return set(_LLM_NODE_TASKS)


def _eval_manifest() -> set[str]:
    """评测清单 —— 同样运行时导入（它现在是生产清单的派生视图）。"""
    _ensure_import_path()
    import importlib

    harness = importlib.import_module("harness")
    assert harness.LLM_CALLING_NODES, "评测清单为空"
    return set(harness.LLM_CALLING_NODES)


#: 出站触达的两种实测形态（都要认，缺一就会把真 LLM 节点误判成"不出站"）：
#: · `deps.llm` / `context.deps.llm` —— 直连网关（`nodes/bind.py:180` 的 L4 精排）；
#: · `deps.planner.*` —— 走 planner 端口（它内部才调网关，`normalize`/`intent`/`plan`/
#:   `gen_sql`/`repair` 五个节点都是这一形态）。
#: ⚠️ **不认** `from app.llm.errors import LlmError` —— 那只是异常类型，不代表出站。
_EGRESS_PATTERNS = (
    r"\bdeps\.llm\b",
    r"\bdeps\.planner\b",
)


def _nodes_touching_llm() -> set[str]:
    """代码判据：节点源文件里是否真的出现 LLM 出站调用（见 `_EGRESS_PATTERNS`）。"""
    hits: set[str] = set()
    for f in sorted(NODES_DIR.glob("*.py")):
        if f.name.startswith("_"):
            continue
        body = f.read_text(encoding="utf-8")
        if any(re.search(pat, body) for pat in _EGRESS_PATTERNS):
            hits.add(f.stem)
    return hits


#: 非 LLM 出站、但 07 §5.3 仍给它"客户端超时"格的节点（**具名白名单，只许减少不许增加**）。
#: `present`：§5.3 第 14 行把它列在 LLM 节点行内（U-104 裁定的"同源缺陷同款修"），
#: 但 `nodes/present.py` 只读 `deps.presenter`、**不触达 `deps.llm`** ⇒ 它是"文档归 LLM 档、
#: 代码无出站"的唯一特例。允许它留在清单里（保住超时包装），但**必须是具名的**：
#: 任何**新增**的此类成员都会让本测试红。
DOC_ONLY_LLM_SLOTS = frozenset({"present"})


def test_production_and_eval_manifests_are_identical() -> None:
    prod, ev = _prod_manifest(), _eval_manifest()
    assert prod, "生产清单解析为空 —— 正则过期了，先修判据"
    assert ev, "评测清单解析为空 —— 正则过期了，先修判据"
    assert prod == ev, (
        f"两份清单漂移：只在生产侧 {sorted(prod - ev)}；只在评测侧 {sorted(ev - prod)}"
    )


def test_manifest_has_no_undocumented_member() -> None:
    """清单成员只许是「真的触达 LLM」或**具名白名单**里的文档例外。"""
    prod = _prod_manifest()
    code = _nodes_touching_llm()
    undocumented = prod - code - DOC_ONLY_LLM_SLOTS
    assert not undocumented, (
        f"清单里有既不出站、也不在具名白名单的节点：{sorted(undocumented)}"
        "（要么删掉它，要么在 DOC_ONLY_LLM_SLOTS 里具名并写理由）"
    )


def test_manifests_match_code_fact_about_touching_llm() -> None:
    prod, ev = _prod_manifest(), _eval_manifest()
    code = _nodes_touching_llm()
    assert code, "代码判据抓不到任何节点 —— 正则过期了，先修判据"
    assert not (code - prod), (
        f"触达 LLM 但不在生产清单（会只拿到契约表超时）：{sorted(code - prod)}"
    )
    assert not (code - ev), f"触达 LLM 但不在评测清单：{sorted(code - ev)}"


def test_bind_gets_client_hard_timeout_not_contract_value() -> None:
    """`bind` 的实效硬超时必须等于客户端超时（§10.2），不是 `NODE_TIMEOUT_S` 的契约值。"""
    _ensure_import_path()
    from app.graph.build import NODE_TIMEOUT_S, _effective_limit_for
    from app.llm.router import hard_timeout_s, resolve_route

    assert "bind" in _prod_manifest()
    effective = _effective_limit_for("bind", None)
    assert effective == hard_timeout_s(resolve_route("l4_score").model_key), (
        f"bind 实效 {effective} != 客户端超时"
    )
    contract = NODE_TIMEOUT_S.get("bind")
    if contract is not None:
        assert effective != contract, (
            "bind 仍拿契约表值（0.2s）—— 生产/评测不一致会复现"
        )


def test_upstream_timeout_never_becomes_no_data_asset_end_to_end() -> None:
    """🔴 节点级（真图）回归：上游超时 ⇒ `error(LLM_UPSTREAM_ERROR)`，**不是**拒答。

    这条补的是"网关改了、节点也改了，但两者接起来仍可能是拒答"的缝：
    真图 + 注入 `LlmTimeout`（零出站），断言终态与审计里都不出现
    `refuse(no_data_asset)`。
    """
    import asyncio

    _ensure_import_path()
    sys.path.insert(0, str(REPO / "backend" / "tests"))  # `tests.contract.*` 包路径
    from app.graph.build import build_graph
    from app.graph.context import clear_run_context, set_run_context
    from app.graph.events import EventRecorder
    from app.api import sse
    from app.llm.errors import LlmTimeout
    from tests.contract._fullchain_deps import _DepsHolder, make_chain, run_chain

    for node, kwargs in (("plan", {"plan_error": LlmTimeout("stub")}),
                         ("normalize", {"understand_error": LlmTimeout("stub")})):
        chain = make_chain(**kwargs)
        frames, outcome = run_chain(chain)
        terminal = [d for e, d in frames if d.get("terminal") is True]
        assert len(terminal) == 1, f"{node}: 终态数 != 1"
        assert terminal[0].get("reason") != "no_data_asset", (
            f"{node} 的上游超时被记成业务拒答：{terminal[0]}"
        )
        assert terminal[0].get("code") == "LLM_UPSTREAM_ERROR", (
            f"{node} 的上游超时应落 LLM_UPSTREAM_ERROR，实得 {terminal[0]}"
        )


def test_timeout_error_code_is_recoverable_and_attributable() -> None:
    """🔴 超时冒到终态时，码必须**可判根因**（不许是 `INTERNAL`）。

    附录 A §A.11 的 28 码里没有"LLM 超时"专用码；超时与 5xx 同族
    （上游侧、✅ 可重试）⇒ 归属 `LLM_UPSTREAM_ERROR`，靠 `error_detail`
    里的 `last_degrade_error` / `reason` 区分具体成因。
    """
    _ensure_import_path()
    from app.llm.errors import LlmCircuitOpen, LlmSaturated, LlmTimeout

    assert LlmTimeout.default_code == "LLM_UPSTREAM_ERROR"
    assert LlmCircuitOpen.default_code == "LLM_UPSTREAM_ERROR"
    assert LlmSaturated.default_code == "LLM_UPSTREAM_ERROR"
