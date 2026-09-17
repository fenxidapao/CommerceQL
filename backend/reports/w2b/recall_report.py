"""W2B 检索黄金集 recall 报告（DoD②，2026-09-16）。

黄金集 = eval/gold_query_seed_v1.json（119 条，派生自冻结集，只读）。
期望集：从 gold_sql 解析——
  - 资产：gold_sql 中出现 `logical_name` 或 `v_logical_name`（物理视图名）；
  - 列：gold_sql 中以词边界出现 bundle 列名（排除 tenant_id —— 租户谓词
    按口径在执行层注入，difficulty 计算的 gold_sql 本就不含租户过滤）。

指标：
  - asset_recall@5   = |期望资产 ∩ candidates(Top5)| / |期望资产|，宏平均；
  - column_recall@30 = |期望列 ∩ columns(Top30)| / |期望列|，宏平均（仅统计有期望列的 seed）。

⚠️ 如实声明（2026-09-16 实测）：
  - 生产 app.embed_doc 的 tsv 与 embedding **均为空**（W2A 已建表未填充，
    embedding 还缺 bge-m3 模型）→ sparse/dense 两路本轮贡献为 0，
    本报告数值 = value + graph 两路的真实召回，**不是**四路完整形态的成绩；
  - Ollama 宿主无 bge-m3（只有 nomic-embed-text 768d），dense 每问显式降级。

运行：../../.venv/Scripts/python.exe backend/reports/w2b/recall_report.py
输出：recall_results.json + recall_report.md（本目录）
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.contracts import IdentityContext, Role  # noqa: E402
from app.core.enums import RetrievalMode  # noqa: E402
from app.retrieval.dense import OllamaEmbedder, PgVectorStore  # noqa: E402
from app.retrieval.search import RetrievalService  # noqa: E402
from app.retrieval.sparse import SparseSearch  # noqa: E402
from app.retrieval.view import BundleView  # noqa: E402

BUNDLE_VERSION = "2026.09.14.1"
OLLAMA_URL = "http://127.0.0.1:11434"
PROD_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/ecom"


def sync_fetch_factory():
    """生产库同步取数（psycopg 直连；评测脚本非在线路径，逐连接即可）。"""

    async def fetch(sql: str, params: dict[str, object]):
        for key in params:
            sql = sql.replace(f":{key}", f"%({key})s")
        import psycopg

        with psycopg.connect(PROD_DSN, connect_timeout=5) as conn, conn.cursor() as cur:
            cur.execute(sql, dict(params))  # type: ignore[arg-type]
            if cur.description is None:
                return []
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    return fetch


def parse_expected(view: BundleView, gold_sql: str) -> tuple[set[str], set[str]]:
    """gold_sql → (期望资产, 期望列)。词边界匹配，逻辑名兼容 `v_` 物理前缀。"""
    expected_assets: set[str] = set()
    for a in view.assets:
        name = a.logical_name
        if re.search(rf"\b(v_)?{re.escape(name)}\b", gold_sql):
            expected_assets.add(name)
    expected_cols: set[str] = set()
    for a in view.assets:
        for c in a.columns:
            if c.name == "tenant_id":
                continue
            if re.search(rf"\b{re.escape(c.name)}\b", gold_sql):
                expected_cols.add(c.name)
    return expected_assets, expected_cols


async def main() -> None:
    import yaml

    bundle_path = REPO_ROOT / "semantic" / "bundle_2026.09.14.1.yaml"
    view = BundleView.from_mapping(
        yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
    )
    embedder = OllamaEmbedder(
        base_url=OLLAMA_URL, model=view.embedding_model, dim=view.embedding_dim,
        timeout_s=30,
    )
    fetch = sync_fetch_factory()
    service = RetrievalService(
        view=view,
        embedder=embedder,
        vector_store=PgVectorStore(fetch),
        sparse=SparseSearch(fetch, rank_normalization=32, score_min=0.05),
        weights={"dense": 0.40, "sparse": 0.35, "value": 0.15, "graph": 0.10},
        rrf_k=60,
        cache=None,
    )

    seeds = json.loads(
        (REPO_ROOT / "eval" / "gold_query_seed_v1.json").read_text(encoding="utf-8")
    )["seeds"]

    asset_recalls: list[float] = []
    col_recalls: list[float] = []
    routes = {"value": 0, "graph": 0, "degraded": 0}
    misses: list[dict[str, object]] = []

    for seed in seeds:
        ctx = IdentityContext(
            trace_id="recall", task_id="recall", session_id="recall",
            tenant_id="T_A", user_id="eval", role=Role.ANALYST,
        )
        result = await service.search_full(
            seed["question"], ctx, RetrievalMode.HYBRID
        )
        got_assets = {c.asset_id for c in result.candidates}
        got_cols = {ref.split(".", 1)[1] for ref, _ in result.columns if "." in ref}
        exp_assets, exp_cols = parse_expected(view, seed["gold_sql"])

        if result.value_hits:
            routes["value"] += 1
        if result.graph_hits:
            routes["graph"] += 1
        if result.degraded:
            routes["degraded"] += 1

        a_recall = (
            len(exp_assets & got_assets) / len(exp_assets) if exp_assets else None
        )
        c_recall = len(exp_cols & got_cols) / len(exp_cols) if exp_cols else None
        if a_recall is not None:
            asset_recalls.append(a_recall)
        if c_recall is not None:
            col_recalls.append(c_recall)
        if (a_recall is not None and a_recall < 1.0) or (
            c_recall is not None and c_recall < 1.0
        ):
            misses.append(
                {
                    "seed_id": seed["seed_id"],
                    "question": seed["question"],
                    "expected_assets": sorted(exp_assets),
                    "got_assets": sorted(got_assets),
                    "expected_cols": sorted(exp_cols),
                    "got_cols_sample": sorted(got_cols)[:10],
                }
            )

    n_a = len(asset_recalls)
    n_c = len(col_recalls)
    summary = {
        "n_seeds": len(seeds),
        "asset_recall_at5_macro": (
            round(sum(asset_recalls) / n_a, 4) if n_a else None
        ),
        "asset_recall_seeds_counted": n_a,
        "column_recall_at30_macro": (
            round(sum(col_recalls) / n_c, 4) if n_c else None
        ),
        "column_recall_seeds_counted": n_c,
        "route_attribution": routes,
        "caveat": (
            "sparse/dense 两路因生产 embed_doc 的 tsv/embedding 未填充而贡献为 0；"
            "本数值 = value+graph 两路的真实召回，非四路完整形态。"
        ),
    }

    out_dir = Path(__file__).resolve().parent
    (out_dir / "recall_results.json").write_text(
        json.dumps({"summary": summary, "misses": misses}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    md = [
        "# W2B 检索黄金集 Recall 报告（DoD②）",
        "",
        f"- 日期：2026-09-16｜黄金集：eval/gold_query_seed_v1.json（{len(seeds)} 条）",
        f"- **asset_recall@5（宏平均）= {summary['asset_recall_at5_macro']}**"
        f"（计入 {n_a} 条有资产期望的 seed）",
        f"- **column_recall@30（宏平均）= {summary['column_recall_at30_macro']}**"
        f"（计入 {n_c} 条有列期望的 seed）",
        f"- 路由归因：value 命中 {routes['value']} 题｜graph 命中 {routes['graph']} 题"
        f"｜显式降级 {routes['degraded']} 题",
        "",
        "## ⚠️ 如实声明（未解决的风险）",
        "",
        "1. 生产 `app.embed_doc` 197 行中 `tsv` 与 `embedding` **全部为空**"
        "（W2A 已建表未填充；宿主 Ollama 亦无 bge-m3 模型）→ sparse/dense 两路本轮贡献 0。",
        "2. 本报告数值是 **value+graph 两路的真实召回**，不得对外宣称为四路完整成绩；",
        "   W2A 填充 tsv/embedding 后须重跑本脚本取得完整口径。",
        f"3. 未满分 seed {len(misses)} 条，明细见 recall_results.json 的 misses。",
        "",
        "## 复现方式",
        "",
        "```",
        "cd backend && ../.venv/Scripts/python.exe reports/w2b/recall_report.py",
        "```",
    ]
    (out_dir / "recall_report.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
