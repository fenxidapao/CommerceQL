"""W2B · `U-112` issue② —— 给 `app.embed_doc` 灌文档向量与 `tsv`（一次性脚本，**不属于交付物**）。

## 它做什么

调 `app.semantics.materialize.materialize()` —— **W2A 的模块，本脚本只调用、不改一行** ——
补上两个从来没被注入过的东西：

| 参数 | 注入物 | 为什么之前是空的 |
|---|---|---|
| `tokenizer=` | `app.retrieval.tokenizer.tokenize` | N-24 要求写入侧与查询侧**同一函数**；物化那次没注入 ⇒ `tsv` 全 NULL、`tsv_status="pending_tokenizer"` |
| `embedder=` | `OllamaEmbedder`（宿主 Ollama / `bge-m3`）的**同步适配器** | `materialize` 要 `Callable[[list[str]], list[list[float]]]`，而 `OllamaEmbedder.embed` 是 `async`；查询侧（`deps.py:727`）一直有它，**写入侧从来没有** |

## ⚠️ 跑之前必须知道的四件事（爆炸半径）

1. **幂等**：`materialize()` 对同一 `bundle_version` 是 `DELETE` 相关行 → `INSERT` 重建，
   **全在一个事务里**（`materialize.py:296-299`）⇒ 重复跑不产生重复行；中途失败整体回滚。
2. **写的是共享 dev 库**：DSN 取自 `deploy/.env` 的 `DATABASE_URL`（元数据 R/W，角色 `app_rw`），
   库名 `ecom` —— **所有窗口共用**。本机最近一次"共享表被别窗口改掉"的事故是 `U-113`。
3. **默认 `with_policy=False`**：只写数据，**不碰 GRANT/POLICY**（把权限面爆炸半径降为零）。
   需要完整 §6.2 六步发布时再加 `--with-policy`（ADR-10 纯函数，重派生同语句集）。
4. **跑完必须自证**：`embed_doc` 的 `embedding` 非空计数与 `tsv` 非空计数都应 = 197。
   本脚本自动打印（`--verify-only` 可单独复核）。

跑法：
    python _w2b_u112_materialize.py --dry-run      # 只读预演：不写一个字，报告就绪状态
    python _w2b_u112_materialize.py               # 真跑（数据 only）
    python _w2b_u112_materialize.py --verify-only  # 只查当前库里的三项计数
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(r"E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL")
sys.path.insert(0, str(REPO / "backend"))

import psycopg  # noqa: E402

BUNDLE = REPO / "semantic" / "bundle_2026.09.14.1.yaml"
OLLAMA = "http://127.0.0.1:11434"
OLLAMA_MODEL = "bge-m3"
DIM = 1024
VERSION = "2026.09.14.1"


def rw_dsn() -> str:
    """`deploy/.env` 的 DATABASE_URL → 宿主可用的 libpq DSN。

    ⚠️ `.env` 里的 host 是 **compose 服务名 `pg`**（容器内视角），宿主跑要换 `127.0.0.1`。
    """
    for line in (REPO / "deploy" / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return (
                line.partition("=")[2]
                .strip()
                .replace("postgresql+psycopg://", "postgresql://")
                .replace("@pg:", "@127.0.0.1:")
            )
    raise SystemExit("deploy/.env 里找不到 DATABASE_URL")


def counts() -> tuple[int, int, int]:
    with psycopg.connect(rw_dsn(), connect_timeout=5) as conn:
        return conn.execute(
            "SELECT count(*), count(embedding), count(*) FILTER (WHERE tsv IS NOT NULL"
            " AND tsv::text <> '') FROM app.embed_doc WHERE bundle_version = %s",
            (VERSION,),
        ).fetchone()  # type: ignore[return-value]


def report_counts(tag: str) -> None:
    total, emb, tsv = counts()
    print(f"  {tag}: embed_doc 行数={total} | embedding 非空={emb} | tsv 非空={tsv}")
    if total and emb == total and tsv == total:
        print("     ⇒ 两项就绪 ✅")
    else:
        print(f"     ⇒ 未就绪（缺 embedding {total - emb} 行 / tsv {total - tsv} 行）")


def check_ollama() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=4) as resp:
            import json

            names = [m.get("name") for m in json.loads(resp.read().decode()).get("models", [])]
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"  Ollama 不可达 ❌ {type(exc).__name__}: {exc}")
        return False
    hit = [n for n in names if n and n.startswith(OLLAMA_MODEL)]
    print(f"  Ollama 可达 ✅ | {OLLAMA_MODEL} {'在册 ✅' if hit else '**不在册** ❌'} {hit}")
    return bool(hit)


def build_embedder() -> object:
    """`OllamaEmbedder` → `materialize` 要的同步回调用适配器。

    `OllamaEmbedder.embed` 内部已按 ≤32 分片（`EMBED_BATCH_SIZE`），197 篇 → 7 批。
    """
    from app.retrieval.dense import OllamaEmbedder

    embedder = OllamaEmbedder(
        base_url=OLLAMA, model=OLLAMA_MODEL, dim=DIM, timeout_s=120,
    )

    def sync_embed(texts: list[str]) -> list[list[float]]:
        return asyncio.run(embedder.embed(texts))

    return sync_embed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只读预演，不写库")
    ap.add_argument("--verify-only", action="store_true", help="只查当前计数")
    ap.add_argument("--with-policy", action="store_true", help="同时执行 §6.2 步骤②（GRANT/POLICY）")
    args = ap.parse_args()

    print(f"目标库 (app_rw) : {rw_dsn().rsplit('@', 1)[-1]}")
    print(f"目标版本        : {VERSION}")
    print(f"语义包          : {BUNDLE}  (exists={BUNDLE.exists()})")
    print()

    if args.verify_only:
        report_counts("当前")
        return

    print("[1] 前置检查")
    ollama_ok = check_ollama()
    try:
        from app.semantics.loader import load_bundle
        from app.semantics.materialize import _build_docs

        loaded = load_bundle(BUNDLE)
        docs = _build_docs(loaded)
        print(f"  语义包已加载 ✅ version={loaded.version} | 将写入 embed_doc 的文档数={len(docs)}")
    except Exception as exc:  # noqa: BLE001 — 预演阶段把一切失败摊开
        print(f"  语义包加载失败 ❌ {type(exc).__name__}: {exc}")
        return

    print()
    print("[2] 写入前计数")
    report_counts("写入前")

    if args.dry_run:
        print()
        print("[3] DRY-RUN —— 到此为止，**没有写任何一行**")
        print(f"  若真跑：会先 DELETE 该版本全部行，再 INSERT {len(docs)} 行"
              "（含 embedding + tsv），单事务。")
        if not ollama_ok:
            print("  ⚠️ Ollama 未就绪 —— 现在真跑只能拿到 tsv、embedding 仍会 NULL。")
        return

    if not ollama_ok:
        raise SystemExit("Ollama 未就绪 ⇒ 拒绝真跑（灌一半比不灌更难查）")

    print()
    print(f"[3] 物化（with_policy={args.with_policy}）…… 197 篇 × 1024 维，7 批")
    from app.semantics.materialize import materialize

    report = materialize(
        loaded,
        dsn=rw_dsn(),
        tokenizer=__import__("app.retrieval.tokenizer", fromlist=["tokenize"]).tokenize,
        embedder=build_embedder(),
        with_policy=args.with_policy,
    )
    print(f"  version            = {report.version}")
    print(f"  doc_count          = {report.doc_count}")
    print(f"  embedding_status   = {report.embedding_status}")
    print(f"  tsv_status         = {report.tsv_status}")
    print(f"  grant_policy_done  = {report.grant_policy_executed}")
    for w in report.warnings:
        print(f"  warning            : {w}")

    print()
    print("[4] 写入后自证")
    report_counts("写入后")


if __name__ == "__main__":
    main()
