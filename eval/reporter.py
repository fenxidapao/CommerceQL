"""W6 评测报告**装配器**（08 §3.8 产出⑤⑥ 的落地：`评测报告与门禁判定.md` 由本文件生成）。

归属窗口：W6。**本窗口是唯一有权宣布门禁通过/不通过的窗口。**

为什么报告由代码生成、而不是手写
--------------------------------------------------------------------------
`gap_table.py` 的文档头已经给过同一个理由，这里只补一句更狠的：
**手抄的数字会在第二轮里悄悄变成上一轮的数字。** 本轮实测已经撞过一次 ——
5 条 live 记录的 `verdict.hash_matches` 全为 `None`、diffs 全是「列数不同：金标 N / 预测 0」，
即**那一批没有任何用例真正走到执行层**（终态是 refuse/clarify/error）。
这个事实一旦被手抄进第二轮报告，就会长成「执行层已验证」。

⇒ 本文件把**全部数字**从产物 JSON 复算，把**解释性文字**作为常量放在代码里：
要改结论就得改代码，改代码就会进 diff。这是唯一能防住「报告自己变好看」的机制。

两个 `consistency` 不是同一个东西
--------------------------------------------------------------------------
`gates.evaluate_gates(consistency=…)` 的 `consistency` 是 **G-7 核心指标口径一致性**
（附录 C §C.4.3，需要 `total/consistent/unattributed`，由 `probe_metric_values.py` 产出），
**不是** §17.6 的一致性三测，也**不是** `probe_metric_coverage.py`（那份只有覆盖度）。
⚠️ 上一版本就把覆盖度探针喂在了这个位置 —— 覆盖度里没有 `total` 键，G-7 于是"恰好"落成
`NOT_AVAILABLE`：一个喂错件的调用被一个保守的判定掩盖了，看起来像"跑了但没数据"。
本文件分开装：G-7 缺输入 ⇒ `NOT_AVAILABLE`；覆盖度单独成节解释 EX 分母；§17.6 三测又是 §6。

跑法（CommerceQL 根目录，零 LLM / 零成本；只读已有产物）
--------------------------------------------------------------------------
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/reporter.py
产物：`backend/reports/w6/eval_metrics.json` + `backend/reports/w6/评测报告与门禁判定.md`
退出码：0 = 门禁全 PASS；1 = 未全过（**报告仍然会写出来**，失败不是不报告的理由）。
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import _bootstrap

_bootstrap.bootstrap()

import gap_table as gaps_mod  # noqa: E402
import gates as gates_mod  # noqa: E402
import grid as grid_mod  # noqa: E402

__all__ = [
    "build_payload",
    "collect_coverage",
    "loadtest_pressure",
    "main",
    "parse_pytest_summary",
    "pg_facts",
    "pg_statement",
    "render_markdown",
    "replay_reproducibility",
    "timeout_snapshot_drift",
]

W6_DIR = os.path.join(_bootstrap.ROOT, "backend", "reports", "w6")
DEFAULT_RESULTS = os.path.join(_bootstrap.HERE, "results_v1.json")
DEFAULT_REDPATH = os.path.join(W6_DIR, "redteam_results.json")
DEFAULT_CONSPATH = os.path.join(W6_DIR, "consistency_results.json")
#: G-1 的读数来源 = **本轮**的全量套件日志（含 `tests/eval/`）。
#: `_baseline_pytest.log` 是开工前的基线快照，只用于对比"有没有被我改坏"，不得当 G-1 输入。
DEFAULT_PYTEST_LOG = os.path.join(W6_DIR, "_full_pytest_w6.log")
DEFAULT_METRIC_PROBE = os.path.join(W6_DIR, "probe_metric_coverage.json")
#: §C.4.3 核心指标**权威值比对**产物 —— G-7 的唯一合法输入（覆盖率探针不是）。
DEFAULT_METRIC_VALUES = os.path.join(W6_DIR, "probe_metric_values.json")
DEFAULT_PG_PROBE = os.path.join(W6_DIR, "_probe_pg_real.json")
DEFAULT_INTEGRATION_LOG = os.path.join(W6_DIR, "_integration_pytest.log")
#: 匣带**可复算性**探针（同一批 20 题、`--mode replay`、只测命中率）。
#: 它不是批次读数 —— 它回答的是"报告里那些回放读数今天还能不能零成本重算"。
DEFAULT_CASSETTE_PROBE = os.path.join(W6_DIR, "cassette_replay_probe.json")
DEFAULT_JSON_OUT = os.path.join(W6_DIR, "eval_metrics.json")
DEFAULT_MD_OUT = os.path.join(W6_DIR, "评测报告与门禁判定.md")

#: W7 压测回执的 schema（`deploy/loadtest/driver.py` 的 `SCHEMA_VERSION`）。
#: schema 串写错 = 静默读不到 P95 ⇒ G-6 永远是 NOT_AVAILABLE，故两个常量放一起、可 grep。
LOADTEST_SCHEMA = "w7.loadtest.receipt/1"
#: W7 `--out` 的默认文件名；路径未在对方文档钉死 ⇒ 本窗口按此读，RELAY 请 W7 确认。
DEFAULT_LOADTEST_RECEIPT = os.path.join(_bootstrap.ROOT, "deploy", "loadtest", "receipt.json")
#: W7 的人类可读报告（只用于「没拿到回执时说明谁欠、去哪查」，**不是** G-6 的判定输入）。
DEFAULT_PRESSURE_REPORT = os.path.join(_bootstrap.ROOT, "backend", "reports", "w7", "压测报告.md")

#: §C.7 的 12 类之外、本窗口新增的归因类别。报告必须单列，
#: 否则读者会把「沙箱方言差距」当成模型能力 —— 那正是 §C.7 要防的事。
W6_EXTRA_CATEGORIES = ("sandbox_dialect_gap", "gate_policy_gap", "terminal_shape_gap", "unattributed")

_L4_STAGE = "bind.l4"


# ---------------------------------------------------------------------------
# 一、产物读取（缺失不假装存在，字段缺了不猜默认值）
# ---------------------------------------------------------------------------

def _load(path: str | None) -> Any | None:
    if not path or not os.path.exists(path):
        return None
    return _bootstrap.load_json(path)


def _rel(path: str | None) -> str:
    """报告是**共享产物** ⇒ 里面不该出现本机绝对路径（含用户名/盘符/中文目录）。

    仓库外的路径不硬凑相对形式（`../..` 连三格会让人以为能点开），原样给出并注明。
    """
    if not path:
        return "未记录"
    try:
        rel = os.path.relpath(path, _bootstrap.ROOT).replace("\\", "/")
    except ValueError:      # 跨盘符：relpath 直接抛，不是本仓库能表达的相对路径
        return f"{path}（仓库外，按绝对路径给出）"
    return rel if not rel.startswith("..") else f"{path}（仓库外）"


def pg_facts(path: str | None = DEFAULT_PG_PROBE) -> dict[str, Any] | None:
    """真 PG 只读探测的结论（`_probe_pg_real.py` 的产物）。没探测 ⇒ `None`。

    ⚠️ 本函数是**读产物**，不连库：报告器必须能在无 PG 环境下照常生成，
    而且"没探测"要写成"本轮未探测"，不能写成"不可达"—— 那是两回事。
    """
    raw = _load(path)
    if not isinstance(raw, Mapping):
        return None
    pg = raw.get("pg") or {}
    parity = raw.get("parity") or {}
    return {
        "reachable": bool(pg.get("reachable")),
        "version": pg.get("version"),
        "alembic_version": pg.get("alembic_version"),
        "n_app_tables": len(pg.get("pg_base_tables") or []),
        "n_app_views": len(pg.get("pg_views") or []),
        "rls_policies_n": parity.get("pg_rls_policies_n", 0),
        "rls_forced_relations": parity.get("pg_rls_forced_relations") or [],
        "app_ro_visible_objects": pg.get("app_ro_visible_objects"),
        "app_ro_reads_view": pg.get("app_ro_can_read_view"),
        "pg_fact_rows": parity.get("pg_business_fact_rows", 0),
        "sqlite_fact_rows": parity.get("sqlite_business_fact_rows", 0),
        # 有效性（不只是存在性）的证据：本轮探针新增的三项。缺任何一项 ⇒ 缺口表不许说"已实测有效"。
        "rls_partition_ok": bool(pg.get("rls_partition_ok")),
        "rls_per_tenant_view_counts": pg.get("rls_per_tenant_view_counts") or {},
        "rls_negative_no_context": pg.get("rls_negative_no_context"),
        "rls_negative_unknown_tenant": pg.get("rls_negative_unknown_tenant"),
        # 三态而非 bool()：**没跑这项对照**（缺键 = None）与**跑了但不等值**（False）是两回事 ——
        # 前者只能说"未测"，后者必须点名。本轮起判据跑在"四形态 × 真串行/真并行"上 ⇒ 还要
        # 搬出**哪一格**少算、以及生产执行链那一格等不等值，否则措辞只能含糊说"不等值"。
        "parallel_equality_ok": pg.get("parallel_equality_ok"),
        "parallel_undercount_states": pg.get("parallel_undercount_states") or [],
        "parallel_state_ok": pg.get("parallel_state_ok") or {},
    }


def loadtest_pressure(path: str | None = DEFAULT_LOADTEST_RECEIPT) -> dict[str, Any] | None:
    """W7 压测回执（§16.5 / `w7.loadtest.receipt/1`）→ G-6 的输入。没跑就是 `None`。

    ⚠️ 取**各场景 p95 的最大值**：§17.3 的「P95 ≤ 8s」是延迟红线，取平均或只取
    steady 一条会让 burst / 配额场景的劣迹隐身。
    ⚠️ 任一场景带 `g6_caveat` ⇒ 整份回执的 P95 不可判达标（W7 的 6 种不可判情形里最强的
    一种是"该场景 0 条真正完成"）；降成 UNVERIFIED 的活交给 `gates.py`，本函数只负责如实搬运。

    U-106 之后 `latency_ms.p95` 的**population 变了**：只在准入（HTTP 2xx）样本上算，
    429 被剔出分母、单列在 `admission`。⇒ 本函数照旧用 `latency_ms.p95` 打分（那是 schema
    里定义的那一个数），但把 `p95_scope` / `admission` / `latency_ms_all_ms` 一并搬出来，
    由 `gates.py` 负责把"这不是端到端全请求分位数"写进判定格 —— **不做的事**：
    不拿新字段重算 p95（两套口径同时打分只会让人以为门禁换了定义），也不校验未知键
    （W7 刻意不升版本号，升了就静默变 NOT_AVAILABLE；多出来的键必须无害）。
    """
    raw = _load(path)
    if not isinstance(raw, Mapping) or raw.get("schema") != LOADTEST_SCHEMA:
        return None
    scenarios = [s for s in (raw.get("scenarios") or []) if isinstance(s, Mapping)]
    p95s = [float(s["latency_ms"]["p95"]) for s in scenarios
            if (s.get("latency_ms") or {}).get("p95") is not None]
    if not p95s:
        return None
    scopes = sorted({
        str(s["p95_scope"]) for s in scenarios
        if isinstance(s.get("p95_scope"), str) and s.get("p95_scope")
    })
    all_p95s = [float(s["latency_ms_all_ms"]["p95"]) for s in scenarios
                if (s.get("latency_ms_all_ms") or {}).get("p95") is not None]
    return {
        "p95_total_ms": max(p95s),
        "source": (f"{LOADTEST_SCHEMA} @ {_rel(path)}"
                   f"（{len(p95s)}/{len(scenarios)} 个场景有 p95，取最大）"),
        "as_of": raw.get("started_at") or "未记录",
        "caveat": next((str(s.get("g6_caveat")) for s in scenarios if s.get("g6_caveat")), None),
        "p95_scope": " / ".join(scopes) if scopes else None,
        "p95_all_requests_ms": max(all_p95s) if all_p95s else None,
        "admission": [s["admission"] for s in scenarios if isinstance(s.get("admission"), Mapping)],
    }


def pg_statement(facts: Mapping[str, Any] | None) -> str:
    """「PG 侧到底验到哪一步」—— 只在这里措辞一次。

    为什么要有这个函数：上一版同一句话在 `_known_limitations`、缺口表 `follow_up`、
    跨租户注记里各写了一遍，而且写的是「hostname `pg` 解析失败 ⇒ PG 侧全部 UNVERIFIED」。
    实测**这条结论是错的**：集成测试用的是 `localhost:5432` 那条 DSN，真 PG 16 应答正常 ——
    把"我没测"报告成"环境测不了"正是 §17.4 要防的叙述。收口成一个函数后，
    事实变了只需改一处，其余地方自动跟着变（测试也钉在这一处）。
    """
    if facts is None:
        return (
            "**本轮未探测真 PG**（无 `_probe_pg_real.json` 产物）⇒ PG 侧结论一律 UNVERIFIED。"
            "注意：未探测 ≠ 不可达，本报告不替环境下任何结论。"
        )
    if not facts["reachable"]:
        return "**PG 不可达**（实测连接失败）⇒ RLS / GRANT / pgvector / tsvector / 真 EXPLAIN 均 UNVERIFIED。"
    if not facts["pg_fact_rows"]:
        return (
            f"**PG 可达但没有业务数据**：实测 `{str(facts['version']).split(' on ')[0]}`、"
            f"alembic {facts['alembic_version']}、{facts['n_app_tables']} 表 + {facts['n_app_views']} 视图、"
            f"{facts['rls_policies_n']} 条 RLS 策略且 "
            f"{len(facts['rls_forced_relations'])} 张表 `FORCE ROW LEVEL SECURITY`"
            f"（{', '.join(facts['rls_forced_relations'])}），`app_ro` 可读视图；"
            f"但 PG 业务事实表 **0 行** vs SQLite 沙箱 {facts['sqlite_fact_rows']:,} 行 "
            "⇒ 结构/权限面已实测，**RLS 有效性与结果集等价在 PG 侧仍不可测**"
            "（0 行对 0 行必然相等，那种「通过」比不测更糟）。"
            "补齐需 W7 灌入与沙箱同规模数据（见 RELAY）。"
        )
    if bool(facts.get("rls_partition_ok")):
        return (
            f"**PG 可达且有 {facts['pg_fact_rows']:,} 行业务事实数据**（RLS 策略 "
            f"{facts['rls_policies_n']} 条）⇒ 策略**存在性与有效性均已实测**："
            "逐租户可见数求和恰等于属主总数（不重不漏），零上下文与未知租户两条负对照均返 0 行。"
            "⚠️ 但这**不等于**评测走了 PG：本窗口的租户边界仍是 SQLite TEMP VIEW 模拟，"
            "「应用运行时经 PG 执行并设好 `app.tenant_id` + `app.shop_ids`」那一跳仍未测。"
            + " " + gaps_mod.parallel_clause(facts)
        )
    return (
        f"**PG 可达且有 {facts['pg_fact_rows']:,} 行业务事实数据**"
        f"（RLS 策略 {facts['rls_policies_n']} 条）⇒ 可评估把评测主链路切到 PG。"
        "注意：本轮探测**没有**给出逐租户可见数（`rls_partition_ok`），"
        "所以这条只到「数据与策略在位」，不到「RLS 有效性已实测」。"
        + " " + gaps_mod.parallel_clause(facts)
    )


def timeout_snapshot_drift(snapshot_contract: Mapping[str, Any] | None) -> str:
    """批次快照里的超时表 vs **当前树**的超时表 —— 不同就必须点名。

    为什么需要：`meta.run_config.node_timeouts` 是 **runner 落盘当时**的快照，报告器只是搬运。
    本轮实测：09-18 那批的快照里 `contract` 有 15 个节点（`normalize` 2.0s、`link` 4.0s、
    `present` 2.0s…），而 U-104/U-107 之后当前树只剩 9 个非 LLM 节点（`link` 已到 30s）。
    报告 §0 同页写着本次生成时的 commit ⇒ 不点名的话，读者会拿一张已经不存在的表去引用契约。
    """
    if not snapshot_contract:
        return ""
    from harness import NODE_TIMEOUT_S as now  # 延迟导入：报告器只读产物，不在加载期装整张图

    snap = dict(snapshot_contract)
    if snap == now:
        return ""
    moved_out = sorted(set(snap) - set(now))
    moved_in = sorted(set(now) - set(snap))
    changed = sorted(k for k in set(now) & set(snap) if now[k] != snap[k])
    bits = []
    if moved_out:
        bits.append("已移出契约表（硬超时改执行期解析）：" + "、".join(f"`{k}`" for k in moved_out))
    if moved_in:
        bits.append("新增：" + "、".join(f"`{k}`" for k in moved_in))
    if changed:
        bits.append("值变了：" + "、".join(f"`{k}` {snap[k]}s→{now[k]}s" for k in changed))
    return ("⚠️ 那份 `contract` 是**跑批当时**的快照，已与当前树的 `NODE_TIMEOUT_S` 不一致（"
            + "；".join(bits) + "）⇒ 引用超时契约以当前树为准，别把这张表当今天的口径。")


def replay_reproducibility(probe: Mapping[str, Any] | None) -> str:
    """匣带今天还能不能**零成本复算**（§C.6.1 纪律二的成立条件，不是免责句）。

    实测来由（09-21）：W2A `fbae176` 把 `metrics()/aliases()` 枚举器接进语义摘要 ⇒ 出站报文
    多出一段 `## 指标口径`（首条 system 从 6,401 涨到 11,343 字符）⇒ 旧匣带的 48 个报文指纹
    **全部不再命中**（同一批 20 题回放 = 20/20 `cassette_miss`）。
    ⇒ "产物可复算"这句话必须带**日期与命中率**，否则下一轮会以为自己还能重算。
    """
    if not probe:
        return ("⚠️ 本轮**没有**匣带可复算性探针产物（`cassette_replay_probe.json` 缺失）"
                "⇒ §C.6.1 纪律二（产物可复算）**未验证**，不要把回放当成随时可重算。")
    recs = list(probe.get("records") or [])
    n = len(recs)
    miss = sum(1 for r in recs if "cassette_miss" in str(r.get("infra_error") or ""))
    summary = probe.get("summary") or {}
    if n and miss == n:
        return (
            f"🔴 匣带**已失效，报告里的回放读数今天不可零成本复算**：同一批 {n} 题重放 "
            f"`{os.path.basename(str((probe.get('config') or {}).get('cassette') or ''))}` ⇒ "
            f"**{miss}/{n} 全部 miss**（`tokens_total={summary.get('tokens_total', 0)}`）。"
            "miss 的成因实测在上游出站报文变了（语义摘要新增 `## 指标口径` 段，见 W2A `fbae176`），"
            "**不在评测侧** ⇒ 要重新出这批读数必须**重新录制**（真打），不得回退到网络静默补数。"
        )
    if miss:
        return (
            f"⚠️ 匣带部分失效：{n} 题回放 miss **{miss}** 条（{miss / max(n, 1):.0%}）"
            "⇒ 命中率不满即视为该批不可复算，先重录再引用。"
        )
    return f"✅ 匣带可复算：{n} 题回放 0 miss（本报告的回放读数今天可零成本重算）。"


def git_rev() -> dict[str, Any]:
    """本次报告对应的代码版本。拿不到就写「未知」，**不猜** ——
    报告缺版本锚点，好过带着一个错误的 commit 让人去复现错误的树。"""
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", _bootstrap.ROOT, *args],
            capture_output=True, text=True, timeout=15, check=True,
        ).stdout.strip()

    try:
        return {"rev": run("rev-parse", "--short", "HEAD") or None, "dirty": bool(run("status", "--porcelain"))}
    except Exception as exc:
        return {"rev": None, "dirty": None, "error": f"{type(exc).__name__}: {exc}"}


#: 只在日志里"点过名"的集成测试才算跑了 —— 纯 `.` 的输出里全绿的用例不留文件名。
_INTEGRATION_FILE_RE = re.compile(r"tests[\\/]integration[\\/](\S+?\.py)", re.I)
#: ⚠️ FAILED 与 ERROR **分开放**：前者是断言失败（被测系统坏了），后者是夹具起不来
#: （测试环境坏了）—— 归属不同的窗口，混进一个列表里就没法点名（见 `gates._p0_notes`）。
#: 且摘要里是否出现 `ERROR <nodeid>` 取决于 `-r` 的字符：`E` 才有，小写 `e` 不点 error 名。
_FAILED_TEST_RE = re.compile(r"^FAILED\s+(\S+)", re.M)
_ERROR_TEST_RE = re.compile(r"^ERROR\s+(\S+)", re.M)


def parse_pytest_summary(log_path: str | None) -> dict[str, Any] | None:
    """从 pytest 日志取计数（G-1 的输入）。**只取数，不替环境宣布结论。**

    ⚠️ 这里曾经写死 `integration_ran=False`，理由是本机 `ANALYTICS_DB_URL` 的主机名 `pg`
    解析失败。那个理由**站不住**：`tests/integration/**` 的默认 DSN 是 `localhost:5432`
    （W0 的夹具），与 `pg` 是两条路 —— 实测真 PG 16 应答正常、集成层确实跑过了。
    把"我没查这条路"写成"这条路不通"，就是 §17.4 禁止的那类叙述。
    现在改成从日志里**取证**：集成层是否出现，看有没有 `tests/integration/*.py` 被点过名。
    """
    if not log_path or not os.path.exists(log_path):
        return None
    with open(log_path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    tail = text[-4000:]

    def n(pattern: str) -> int:
        m = re.search(pattern, tail)
        return int(m.group(1)) if m else 0

    passed, failed, errors = n(r"(\d+) passed"), n(r"(\d+) failed"), n(r"(\d+) error")
    if not (passed or failed or errors):
        return None
    skipped = n(r"(\d+) skipped")
    integration_files = sorted(set(_INTEGRATION_FILE_RE.findall(text)))
    failed_tests = sorted(set(_FAILED_TEST_RE.findall(text)))
    error_tests = sorted(set(_ERROR_TEST_RE.findall(text)))
    ran_integration = bool(integration_files)
    return {
        "source_log": os.path.basename(log_path),
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "failed_tests": failed_tests,
        "error_tests": error_tests,
        "integration_ran": ran_integration,
        "integration_files_seen": integration_files,
        "integration_note": (
            f"集成层已跑（日志点名 {len(integration_files)} 个 `tests/integration` 文件，"
            f"跳过 {skipped} 条）⇒ 单元 + 契约 + 集成三层都有读数。"
            if ran_integration
            else (
                "日志里没有 `tests/integration` 文件名 ⇒ **无法**据此断定集成层跑过 "
                f"（跳过 {skipped} 条时才会点名，全绿的用例在 `.` 输出里不留文件名）。"
                "G-1 因此最高只能 PARTIAL（单元 + 契约全绿 ≠ 生产能力已验证）；"
                "要拿集成层读数，单独跑 `pytest tests/integration -q` 并把该日志喂给本报告。"
            )
        ),
    }


# ---------------------------------------------------------------------------
# 二、覆盖率面（EX 的「分母为什么是它」）
# ---------------------------------------------------------------------------

def _terminal(rec: Mapping[str, Any]) -> str:
    """图终态（`refuse` / `clarify` / `error` / `complete`）。

    ⚠️ 不用 `outcome`：那是**审计**口径（实测同一记录 `outcome='failed'` 而
    `terminal_event='error'`），拿它当"停在哪一层"会把两个轴混成一张分布表。
    """
    return str(rec.get("terminal_event") or rec.get("outcome") or "?")


def _has_result_set(rec: Mapping[str, Any]) -> bool:
    """预测侧是否**真拿到了带列的结果集**。

    判据只认 runner 落盘的 `predicted.columns`（= 等价判定器实际拿到的预测侧表）。
    ⚠️ 旧实现是从 `diffs` 文案里正则反推"预测 N 列" ⇒ 一条只差"行序/取值"的用例
    会被读成"没拿到结果集"，于是报告里的「执行层未覆盖」是假的（覆盖率被低估）。
    没有 `predicted` 区块 = 判定器压根没拿到两侧的表 ⇒ 一律 False，不猜。
    """
    pred = rec.get("predicted")
    return bool(pred.get("columns")) if isinstance(pred, Mapping) else False


def collect_coverage(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """把「跑了多少」与「跑到了哪一层」分开数 —— EX 低的原因必须一眼看得见。

    ⚠️ 三个容易混淆的计数：
    * `n_execute_cases`      = 题面是 execute 的用例数；
    * `n_execute_with_sql`   = 其中**产出了非空 SQL** 的条数；
    * `n_execute_with_result`= 其中**真拿到结果集**的条数（只有它进得了 §C.4.1 等价判定）。
    前两个非零而第三个为零 ⇒ 失败发生在**执行之前**（拒答/澄清/闸门），
    此时「EX = 0」与「模型不会写 SQL」无关。
    """
    execute = [r for r in records if str(r.get("expected_behavior")) == "execute"]
    return {
        "n_records": len(records),
        "n_scored": sum(1 for r in records if r.get("scored")),
        "n_execute_cases": len(execute),
        "n_execute_with_sql": sum(1 for r in execute if r.get("sql_text")),
        "n_execute_with_result": sum(1 for r in execute if _has_result_set(r)),
        "n_false_clarify": sum(
            1 for r in records
            if str(r.get("expected_behavior")) == "execute" and _terminal(r) == "clarify"
        ),
        "terminal_distribution": _tally(_terminal(r) for r in records),
        "hash_matches_none_n": sum(
            1 for r in records if (r.get("verdict") or {}).get("hash_matches") is None
        ),
    }


def _tally(items) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        out[it] = out.get(it, 0) + 1
    return dict(sorted(out.items()))


def split_attributions(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """失败归因分布 + 三个**必须分开**的补集。

    ⚠️ 为什么重写（20 条真打批次的实测）：旧实现是一行
    `category or "?"`，判据是"verdict 不等价"。而 runner 对**交互层判对**的用例
    （该拒且拒 / 该澄清且澄清）**根本不写 verdict** ⇒ 它们全落进 `?` 桶，
    于是报告里冒出一行 `? | 7`，读起来像"7 条无法归因"。
    那 7 条的实测构成是：3 条正确拒答 + 3 条正确澄清 + 1 条 infra_error（未进判定）。
    §C.7 的"不可归因 ≤10%"正是靠这张表被读对的 —— 把非失败项混进分母，
    要么虚报缺陷，要么给"放宽阈值"留下口实。
    """
    dist: dict[str, int] = {}
    interaction_correct: list[str] = []
    unscored: list[str] = []
    failures_passed: list[str] = []
    missing: list[str] = []
    for r in records:
        cid = str(r.get("case_id"))
        cat = str((r.get("attribution") or {}).get("category") or "")
        if cat:
            dist[cat] = dist.get(cat, 0) + 1
            continue
        verdict = r.get("verdict")
        expected = str(r.get("expected_behavior"))
        if not r.get("scored"):
            unscored.append(cid)
        elif expected in ("refuse", "clarify") and _terminal(r) == expected:
            interaction_correct.append(cid)
        elif isinstance(verdict, Mapping) and verdict.get("equivalent"):
            failures_passed.append(cid)
        else:
            # 真失败却没有归因 ⇒ 计进 unattributed（§C.7 的兜底类），不藏进"其他"。
            dist["unattributed"] = dist.get("unattributed", 0) + 1
            missing.append(cid)
    return {
        "distribution": dict(sorted(dist.items())),
        "interaction_correct": sorted(interaction_correct),
        "unscored": sorted(unscored),
        "equivalent_so_not_failure": sorted(failures_passed),
        "failure_without_attribution": sorted(missing),
        "note": (
            "`interaction_correct` = 题面本就该拒答/澄清且终态一致 ⇒ **不是失败**，不进归因表；"
            "`unscored` = infra_error 等未进判定 ⇒ 不进任何分母；"
            "`failure_without_attribution` 已并入 `distribution.unattributed`。"
        ),
    }


def split_over_refusal(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """误拒（over_refusal）按**是否带 `bind.l4` 降级**拆开。

    为什么必须拆：沙箱没有 embedding（`embedding_unavailable → sparse_only`），
    且 L4 的候选装配 JSON 会被 `max_tokens` 截断到解析失败
    （`llm_unavailable → reduced_candidates`，`detail.stage = bind.l4`）。
    这类「被上游降级逼出来的拒答」若记成模型误拒，就是拿评测器的环境缺陷给模型定罪。
    """
    both = [r for r in records if (r.get("attribution") or {}).get("category") == "over_refusal"]

    def has_l4(rec: Mapping[str, Any]) -> bool:
        for d in rec.get("degradations") or ():
            detail = d.get("detail") or {}
            if isinstance(detail, Mapping) and detail.get("stage") == _L4_STAGE:
                return True
        return False

    return {
        "total": len(both),
        "with_bind_l4_degradation": [str(r.get("case_id")) for r in both if has_l4(r)],
        "without": [str(r.get("case_id")) for r in both if not has_l4(r)],
        "note": "with_bind_l4 那部分**不得**计入模型误拒（沙箱无 embedding + L4 候选装配解析失败）",
    }


# ---------------------------------------------------------------------------
# 三、τ 与环境事实（N-25 / §18.4.1 的「不许隐瞒」）
# ---------------------------------------------------------------------------

def tau_facts() -> dict[str, Any]:
    """τ 的校准状态。两处实测（占位环境 + `deploy/.env`）必须一起给。

    评测跑在占位环境下，`binding_tau_is_calibrated` 自然是 False —— 那并不说明什么。
    真正要回答的是「**生产**会不会以为自己是校准过的」，答案在 W7 的 `deploy/.env` 里：
    三个校准字段**存在但值为空** ⇒ 生产配置同样未校准。
    （W0 的 `#` 开头校验已排掉「行尾注释被读成值 → 恒 True」那条假绿灯路径。）
    """
    from app.core.config import get_settings  # 延迟导入：只有这里需要 settings

    s = get_settings()
    deploy: dict[str, bool] = {}
    env_path = os.path.join(_bootstrap.ROOT, "deploy", ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"\s*(BINDING_TAU[A-Z_]*)\s*=\s*(.*)$", line)
                if m:
                    # 只落「有没有值」，不落值本身（该文件归 W7，且含密钥）。
                    deploy[m.group(1)] = bool(m.group(2).strip().strip('"').strip("'"))
    return {
        "BINDING_TAU": s.BINDING_TAU,
        "calibrated_under_eval_env": bool(s.binding_tau_is_calibrated),
        "deploy_env_declared": deploy,
        "changed_this_window": False,
        "consequence": (
            "τ 未校准 ⇒ 依赖 L4 精排阈值的结论一律带 R-19 caveat（G-2/G-5/G-7/G-8 的输入面），"
            "判 UNVERIFIED 而不是 FAIL/PASS。本轮**未修改 τ** ⇒ N-25 的「τ 变更须附校准报告」未触发。"
        ),
    }


# ---------------------------------------------------------------------------
# 四、装配
# ---------------------------------------------------------------------------

def build_payload(
    *,
    results_path: str = DEFAULT_RESULTS,
    redteam_path: str = DEFAULT_REDPATH,
    consistency_path: str = DEFAULT_CONSPATH,
    pytest_log: str | None = DEFAULT_PYTEST_LOG,
    integration_log: str | None = DEFAULT_INTEGRATION_LOG,
    metric_probe_path: str | None = DEFAULT_METRIC_PROBE,
    metric_values_path: str | None = DEFAULT_METRIC_VALUES,
    pg_probe_path: str | None = DEFAULT_PG_PROBE,
    cassette_probe_path: str | None = DEFAULT_CASSETTE_PROBE,
    loadtest_receipt: str | None = DEFAULT_LOADTEST_RECEIPT,
    pressure_report: str | None = DEFAULT_PRESSURE_REPORT,
) -> dict[str, Any]:
    dataset = _bootstrap.load_json(_bootstrap.DATASET_PATH)
    cases = dataset.get("cases") or []
    results = _load(results_path) or {}
    records = results.get("records") or []
    cfg = results.get("config") or {}
    cfg_live = bool(cfg.get("live"))
    cfg_mode = cfg.get("mode")
    redteam = _load(redteam_path)
    consistency = _load(consistency_path)          # §17.6 三测（**不是** G-7 的输入）
    metric_probe = _load(metric_probe_path)        # 指标覆盖度（解释 EX 分母，不是 G-7 的输入）
    metric_values = _load(metric_values_path)      # §C.4.3 权威值比对 = G-7 的输入
    pg = pg_facts(pg_probe_path)
    pg_txt = pg_statement(pg)
    cassette_probe = _load(cassette_probe_path)   # 匣带可复算性（纪律二的成立条件）
    p0 = parse_pytest_summary(pytest_log)
    # 全量日志是 `.` 输出时看不到集成层是否参与；有定向日志就用它补上取证。
    p0_integration = parse_pytest_summary(integration_log)
    if p0 and p0_integration and not p0["integration_ran"]:
        p0 = {**p0, **{k: v for k, v in p0_integration.items() if k != "source_log"},
              "source_log": f"{p0['source_log']} + {p0_integration['source_log']}"}

    results_map = {
        str(r.get("case_id")): {
            "scored": bool(r.get("scored")),
            "passed": bool((r.get("verdict") or {}).get("equivalent")),
            "category": str((r.get("attribution") or {}).get("category") or ""),
        }
        for r in records
    }
    grid = grid_mod.build_grid(cases, results_map)
    coverage = collect_coverage(records)

    cross_tenant = None
    if redteam:
        xt = [r for r in redteam.get("results") or [] if str(r.get("case_id")).startswith("RT-XT")]
        if xt:
            cross_tenant = {
                "leaked": sum(1 for r in xt if not r.get("blocked")),
                "n_cases": len(xt),
                # 拦下发生在 SQL 层 ⇒ 与 PG 策略是否生效是两件事，只有后者才算 N-07 完整证据。
                "pg_rls_verified": False,
                "notes": [
                    "RT-XT 全部被拦发生在 **SQL 层**（评测侧 TEMP VIEW 边界 + 闸门）"
                    "⇒ 不构成 N-07 的完整证据。" + pg_txt,
                ],
            }
    tau = tau_facts()
    clarification = _clarify_counts(records)
    pressure = loadtest_pressure(loadtest_receipt)
    gate_list = gates_mod.evaluate_gates(
        grid=grid,
        p0_tests=p0,
        red_team=redteam,
        cross_tenant=cross_tenant,
        refusal=_refusal_counts(records),
        pressure=pressure,                  # §16.5 压测 = W7 的回执；没有 ⇒ NOT_AVAILABLE
        pressure_report=(os.path.relpath(pressure_report, _bootstrap.ROOT)
                         if pressure_report and os.path.isfile(pressure_report or "") else None),
        consistency=metric_values,         # G-7 = §C.4.3 核心指标口径一致性（权威值比对）
        clarification=clarification,
        tau_calibrated=tau["calibrated_under_eval_env"],
    )
    gate_summary = gates_mod.summary(gate_list)

    uncovered = ", ".join(str(c.get("case_id")) for c in (redteam or {}).get("not_covered_cases") or [])
    run_summary = results.get("summary") or {}
    provenance = cfg.get("provenance")
    llm_measured = (
        "无 live 记录（本轮全部为夹具/回放或未跑）"
        if not cfg_live
        else f"本轮真打 {len(records)} 条，tokens_total="
             f"{run_summary.get('tokens_total', '未记录')}，cost_cny_total="
             f"{run_summary.get('cost_cny_total', '未记录')}"
    )
    if not cfg_live and provenance:
        # 回放轮的读数同样来自真金白银录制的那一次 —— 漏报这一句 = 把 §17.2 的工作说没。
        llm_measured = f"回放轮（本轮不出网）；匣带来源：{provenance}"
    gap_rows = gaps_mod.build_gap_table(extra_evidence={
        "EXPLAIN": f"本轮红队未覆盖 {uncovered or '（无）'}",
        "LLM 出站": f"mode={cfg_mode}，{llm_measured}",
        "RLS": ("一致性三测已跑，见 §6" if consistency else "一致性三测未跑") + f"；{pg_txt}",
        "执行层驱动": pg_txt,
    }, pg_facts=pg)

    attribution_split = split_attributions(records)
    attribution_dist = attribution_split["distribution"]
    return {
        "meta": {
            "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "window": "W6",
            "git": git_rev(),
            "run_config": results.get("config"),
            "run_frozen_evidence": results.get("frozen_evidence"),
            "frozen_recheck_now": _safe(_bootstrap.verify_frozen_inputs),
            "dataset_version": dataset.get("dataset_version"),
            "n_dataset_cases": len(cases),
            "artifacts_present": {
                "results": bool(records),
                "redteam": bool(redteam),
                "consistency": bool(consistency),
                "pytest_log": bool(p0),
                "metric_probe": bool(metric_probe),
                "metric_values": bool(metric_values),
                "pg_probe": bool(pg),
                "loadtest_receipt": bool(pressure),
            },
        },
        "gates": [dataclasses.asdict(g) for g in gate_list],
        "gate_summary": gate_summary,
        "grid": {
            "matrix": grid.matrix(),
            "scored_total": grid.scored_total,
            "scored_passed": grid.scored_passed,
            "ex": grid.ex,
            "unattributed_share": grid.unattributed_share(),
        },
        "coverage": coverage,
        "over_refusal_split": split_over_refusal(records),
        "attribution_distribution": attribution_dist,
        "attribution_split": attribution_split,
        "attribution_extra_categories": [c for c in W6_EXTRA_CATEGORIES if c in attribution_dist],
        "red_team": _redteam_digest(redteam) if redteam else None,
        "cross_tenant": cross_tenant,
        "consistency_17_6": consistency,
        "metric_consistency_c43": _metric_values_digest(metric_values),
        "metric_coverage": _metric_coverage_digest(metric_probe),
        "pg_probe": pg,
        "gap_table": gap_rows,
        "tau": tau,
        "known_limitations": _known_limitations(
            coverage, redteam, metric_probe, consistency,
            g8_second_round_available=bool(clarification and clarification.get("second_round_loop_available")),
            clarify_expected_n=int((clarification or {}).get("clarify_expected_n") or 0),
            pg_txt=pg_txt, metric_values=metric_values,
            replay_txt=replay_reproducibility(cassette_probe),
        ),
        "reproduce": [
            "PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/consistency.py",
            "PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/redteam_eval.py",
            "PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/probe_gate_rejections.py",
            "PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/probe_rule_identity.py",
            "PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/probe_metric_coverage.py",
            "PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/probe_metric_values.py   # G-7 输入",
            "PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/_probe_pg_real.py        # 只读探测真 PG",
            "cd backend && PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m pytest -q -rfEs   # G-1 读全量：大写 E 才点 error 名（小写 e 不点 ⇒ 红因无从点名）",
            "cd backend && PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m pytest tests/integration -q -rfEs",
            "PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/select_smoke_batch.py   # 确定性取 20 题",
            "PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/probe_gate_allowlist_shape.py   # U-119 判据③：两种形状 × 两道闸门",
            "PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/runner.py --live --yes   # 真打全量需额度：先不带 --yes 看计划",
            "PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/runner.py --mode replay --provenance \"<匣带来源>\" --yes"
            "   # 匣带未失效时才是零成本复算；今天是否可复算看 §8 那条 🔴（探针 = 下一条命令）",
            "PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/probe_cassette_replay.py"
            "   # 匣带可复算性探针（不是批次读数；产物喂 §8 那条 🔴）",
        ],
    }


def _safe(fn) -> Any:
    try:
        return fn()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _refusal_counts(records: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    refuse_cases = [r for r in records if str(r.get("expected_behavior")) == "refuse"]
    answerable = [r for r in records if str(r.get("expected_behavior")) == "execute"]
    if not refuse_cases:
        return None
    return {
        "total": len(refuse_cases),
        "correct_refused": sum(1 for r in refuse_cases if _terminal(r) == "refuse"),
        "answerable_total": len(answerable),
        "over_refused": sum(1 for r in answerable if _terminal(r) == "refuse"),
    }


def _clarify_counts(records: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """G-8 的输入。**没有应澄清题就返回 None**（⇒ `NOT_AVAILABLE`），理由：

    `runner.py` 只跑**单轮** —— 它没有「clarify 之后把用户补答再喂回去」的第二轮回路。
    而 G-8 的后半句正是"澄清后一次成功率"，它在单轮批次上**结构上不可测**。
    拿 5 条单轮记录去判 FAIL，等于把评测器的能力缺口记成被测系统的失败
    （更糟：这条门禁变得不可能通过，于是下一轮有人会来"放宽阈值"）。

    ⚠️ 反过来，题面是 execute 却收口成 clarify 的**误澄清**是真实观测，
    它进 §3 的覆盖率读数与 §C.4.4 的误拒面，**不进** G-8。
    """
    want = [r for r in records if str(r.get("expected_behavior")) == "clarify"]
    if not want:
        return None
    asked = [r for r in records if _terminal(r) == "clarify"]
    # 分母取「本轮跑到的全部用例」，并把「题面本来就要澄清」的条数一并落盘 ——
    # 分母口径不写死，读者就会按自己的理解重算出一个不同的澄清率。
    return {
        "requests": len(records),
        "clarify_expected_n": len(want),
        "clarified": len(asked),
        "clarify_then_correct": sum(1 for r in asked if (r.get("verdict") or {}).get("equivalent")),
        #: `runner.py` 只跑单轮 ⇒ 后半句「澄清后一次成功」在本类批次里**永远拿不到分子**。
        #: 落这个标志不是装饰：少了它，`gates.py` 会把「评测器没有第二轮回路」判成被测系统 FAIL。
        "second_round_loop_available": False,
    }


def _metric_values_digest(mv: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """§C.4.3 权威值比对的摘要（G-7 的读数 + 差异到底差在哪条谓词）。"""
    if not mv:
        return None
    rows = list(mv.get("rows") or [])
    by_metric: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_metric.setdefault(str(row.get("metric")), []).append(row)
    return {
        "total": mv.get("total"),
        "consistent": mv.get("consistent"),
        "consistent_rate": mv.get("consistent_rate"),
        "unattributed": mv.get("unattributed"),
        "threshold_rel_error": mv.get("threshold_rel_error"),
        "metrics_covered": mv.get("metrics_covered"),
        "comparison_basis": mv.get("comparison_basis"),
        "n_excluded": len(mv.get("excluded") or []),
        "per_metric": {
            name: {
                "n": len(rs),
                "consistent": sum(1 for r in rs if r.get("consistent")),
                "max_rel_error": max(
                    (r["rel_error"] for r in rs if r.get("rel_error") is not None),
                    default=None,
                ),
                #: 只统计**真有差异**的行（一致行不做归因）⇒ 空表 ≠ "gold 已含全部默认谓词"。
                "predicates_behind_differences": sorted(
                    {
                        p
                        for r in rs
                        if not r.get("consistent")
                        for p in ((r.get("attribution") or {}).get("missing_predicates") or [])
                    }
                ),
            }
            for name, rs in sorted(by_metric.items())
        },
        "examples": [
            {
                "case_id": r.get("case_id"),
                "metric": r.get("metric"),
                "gold_value": r.get("gold_value"),
                "authority_value": r.get("authority_value"),
                "rel_error": r.get("rel_error"),
                "attributed": (r.get("attribution") or {}).get("explained_by_predicate"),
            }
            for r in rows
            if not r.get("consistent")
        ][:5],
    }


def _metric_coverage_digest(mc: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """指标**覆盖度**摘要（解释 EX 分母为什么小 —— 与 G-7 无关，别混）。"""
    if not mc:
        return None
    return {
        "n_cases": mc.get("n_cases"),
        "n_question_hits_metric_term": mc.get("n_question_hits_metric_term"),
        "n_execute_agg_without_metric_term": mc.get("n_execute_agg_without_metric_term"),
        "execute_miss_share": mc.get("execute_miss_share"),
        "active_metrics": mc.get("active_metrics"),
    }


def _redteam_digest(rt: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "total", "leaked", "expect_block", "checked", "n_cases_clean", "assertion_counts",
        "reject_gates", "gate2_visible_raise", "gate2_chain_raise_n", "not_covered_cases",
        "terminal_shapes", "failures_by_class", "leak_vocabulary_size",
    )
    out = {k: rt.get(k) for k in keys}
    # `layer_ordering` 只留前若干条做示例：全量在 redteam_results.json 里，报告不复制大表。
    out["layer_ordering_sample"] = (rt.get("layer_ordering") or [])[:3]
    return out


def _known_limitations(
    coverage: Mapping[str, Any],
    redteam: Any,
    metric_probe: Any,
    consistency: Any,
    *,
    g8_second_round_available: bool,
    clarify_expected_n: int = 0,
    pg_txt: str,
    metric_values: Any = None,
    replay_txt: str = "",
) -> list[str]:
    """「已知限制」是报告的一部分，不是免责声明 —— 缺一条就可能被读成通过。"""
    out = [
        "**I-3**：v1 的 `medium` 语义档因沙箱物化了 `v_region.region_name` 而存在**高估**（U-32）。"
        "不就地改（改了 `content_hash` 就不再是冻结集），只在此披露；v2 冻结时按判据重标。",
        "**§17.4 全表 `covered_by_eval=False`** ⇒ 本报告的任何一行都不构成「生产能力已验证」。",
        pg_txt,
        "**τ 未校准**（`deploy/.env` 的三个校准字段同样为空）⇒ L4 相关结论带 R-19 caveat；本轮未改 τ。",
    ]
    if replay_txt:
        # 空串不占位：§8 是"已知限制"清单，一条空 bullet 会被读成"这里本来有内容但没渲染"。
        out.append(replay_txt)
    if metric_values:
        rate = float(metric_values.get("consistent_rate") or 0.0)
        out.append(
            f"**§C.4.3 口径比对**：核心指标 {metric_values.get('total')} 条可比对用例中一致 "
            f"{metric_values.get('consistent')} 条（{rate:.1%}），不可归因差异 "
            f"{metric_values.get('unattributed')} 条。一致率低于 95% 是**冻结集 gold 与语义包默认口径"
            "不一致**的实测结论（差在 gold 少了 `default_predicates`），不是环境缺陷；"
            "比对方是语义包而非外部 BI ⇒ 「已确认权威值」按内部口径降级验证，见 `comparison_basis`。"
            if isinstance(rate, (int, float)) and rate < gates_mod.THRESHOLDS["G-7_consistency"]
            else (
                f"**§C.4.3 口径比对**：{metric_values.get('total')} 条可比对用例，一致率 "
                f"{rate:.1%}，不可归因 {metric_values.get('unattributed')} 条。"
                "比对方是语义包而非外部 BI ⇒ 「已确认权威值」按内部口径降级验证。"
            )
        )
    else:
        out.append(
            "G-7（核心指标口径一致性）**未跑**：`probe_metric_values.py` 尚无产物 ⇒ NOT_AVAILABLE。"
            "注意：覆盖率探针 `probe_metric_coverage.json` **不是**它的输入（那份没有 total/consistent）。"
        )
    if metric_probe:
        out.append(
            f"指标覆盖度：{metric_probe.get('n_execute_agg_without_metric_term', '?')} 条期望 execute 的题面"
            f"不含任何运行时可达的指标词形（占全集 {metric_probe.get('execute_miss_share', 0):.1%}）"
            "⇒ EX 分母偏小的**上半截**来自目录覆盖，不是模型能力。（覆盖度 ≠ G-7 的口径比对）"
        )
    if not coverage["n_records"]:
        out.append("**无 live 批次产物**（结果 JSON 缺失或为空）⇒ G-2/G-5/G-8 无输入，判 NOT_AVAILABLE。")
    else:
        if coverage["n_execute_cases"] and not coverage["n_execute_with_result"]:
            out.append(
                f"**执行层端到端未覆盖**：{coverage['n_execute_cases']} 条 execute 用例里真拿到结果集的是 "
                f"**0** 条（终态分布 {json.dumps(coverage['terminal_distribution'], ensure_ascii=False)}）"
                "⇒ 本轮 EX 只度量「闸门之前 + 闸门本身」，**不等于**「执行 + 掩码 + 渲染链路正确」。"
            )
        elif coverage["n_execute_with_result"] < coverage["n_execute_cases"]:
            out.append(
                f"执行层覆盖不完整：execute 用例 {coverage['n_execute_cases']} 条中 "
                f"{coverage['n_execute_with_result']} 条真拿到结果集。"
            )
        out.append(
            f"样本量：本轮只有 {coverage['n_records']} 条记录进入网格 —— "
            "**任何百分比都是覆盖率读数，不是能力读数**。"
        )
    if redteam:
        out.append(
            f"红队：{redteam.get('total')} 条全跑（确定性闸门面），未覆盖 "
            f"{len(redteam.get('not_covered_cases') or [])} 条成本用例（沙箱无 EXPLAIN）。"
        )
    else:
        out.append("红队产物缺失 ⇒ G-3/G-4 无输入。")
    if not consistency:
        out.append("§17.6 一致性三测产物缺失 ⇒ I-1…I-6 在本轮**没有被机器验证过**。")
    if not g8_second_round_available:
        shape = (
            "本轮**没有应澄清题**⇒ 整条门禁无输入，判 **NOT_AVAILABLE**"
            if not clarify_expected_n
            else (
                f"本轮跑了 {clarify_expected_n} 条应澄清题 ⇒ 前半句「澄清率」有读数，"
                "后半句无分子 ⇒ 整条门禁判 **UNVERIFIED**"
            )
        )
        out.append(
            "**G-8 结构性不可测**：`runner.py` 只跑单轮，没有「clarify 之后把用户补答喂回去」的"
            f"第二轮回路 ⇒ 「澄清后一次成功率」无从度量。{shape}。"
            "两者都**不是** FAIL：拿评测器自己的缺口给被测系统定罪，会把这条门禁变成不可能通过，"
            "下一轮就有人来放宽阈值。"
            f"本轮 {coverage['n_false_clarify']} 条**误澄清**（题面 execute 却 clarify）"
            "已计入 §C.4.4 误拒面。该回路缺口属 W6 评测器自身，已上呈（见 RELAY）。"
        )
    return out


# ---------------------------------------------------------------------------
# 五、渲染
# ---------------------------------------------------------------------------

def _md_table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = [
        "| " + " | ".join(str(h) for h in header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(c).replace("\n", "<br>") for c in row) + " |")
    return "\n".join(lines)


def render_markdown(p: Mapping[str, Any]) -> str:
    meta = p["meta"]
    summary = p["gate_summary"]
    cov = p["coverage"]
    cfg = meta.get("run_config") or {}
    g: list[str] = []
    add = g.append

    add("# 评测报告与门禁判定（W6 · 阶段 6）")
    add("")
    add(f"> 本文件由 `eval/reporter.py` 生成于 `{meta['generated_at']}`。")
    add("> 所有数字都是从产物 JSON 复算的；解释性文字也写在代码里。")
    add("> **要改结论就得改代码，改代码就会进 diff。不要手抄本文件的数字去写别的文档。**")
    add("")
    add("## 0. 本次 run 的身份")
    add("")
    add(f"- 代码版本：`{meta['git'].get('rev')}`（工作区有未提交改动：{meta['git'].get('dirty')}）")
    checks = ((meta.get("frozen_recheck_now") or {}).get("checks")) or {}
    add(f"- 数据集：v{meta['dataset_version']}（{meta['n_dataset_cases']} 条）；"
        f"本报告生成时**重新验真** `content_hash`/`sandbox_db_sha256`："
        f"{'通过' if checks.get('all_ok') else checks or '未取到'}")
    add(f"- LLM 后端：mode={cfg.get('mode')}、live={cfg.get('live')}、"
        f"匣带={os.path.basename(str(cfg.get('cassette') or '')) or '—'}")
    add("- 节点超时派生值见产物 JSON 的 `meta.run_config.node_timeouts`（真打轮被放大 ⇒ "
        "**真打轮的 EX 不覆盖 §5.3 的超时契约**，§17.4）"
        + (" " + timeout_snapshot_drift((cfg.get("node_timeouts") or {}).get("contract"))
           if isinstance(cfg.get("node_timeouts"), Mapping) else ""))
    add("- 产物在位：" + "，".join(f"{k}={'有' if v else '无'}" for k, v in meta["artifacts_present"].items()))
    add("")

    add("## 1. 门禁判定（07 §17.3）")
    add("")
    add(f"**总判定：{'全部 PASS' if summary['all_pass'] else '未全部通过'}** —— "
        f"PASS {len(summary['passed'])}/{len(p['gates'])}；"
        f"非 PASS：`{json.dumps(summary['not_pass'], ensure_ascii=False)}`")
    add("")
    add("> 判定词表：`PASS` / `FAIL` / `UNVERIFIED` / `NOT_AVAILABLE` / `PARTIAL`。")
    add("> **`PASS` 之外的一律不得进入「门禁通过」的汇总句**（gates.py 的文档头同一条）。")
    add("")
    add(_md_table(
        ["门禁", "条件", "判定", "本次实测", "依据", "结论成立的前置（caveats）"],
        [[x["gate_id"], x["condition"], x["verdict"], x["measured"], x["basis"],
          "；".join(x.get("caveats") or ()) or "—"] for x in p["gates"]],
    ))
    add("")
    na = sorted(k for k, v in summary["not_pass"].items() if v == "NOT_AVAILABLE")
    add("> `NOT_AVAILABLE` = **输入根本没拿到**，不是「测了但没过」，也不是「没问题」。")
    add("> 本轮 `NOT_AVAILABLE`：" + (
        "、".join(f"`{x}`" for x in na) if na else "（无）"
    ) + "；逐条原因见 §8 已知限制。")
    add("")

    add("## 2. EX 与 4×3 分层网格（I-1 主口径）")
    add("")
    grid = p["grid"]
    ex = grid["ex"]
    add(f"- 进入 EX 分母：`{grid['scored_total']}` 条（§C.4.1：分母不含应拒答题；未跑到的用例不进分母）")
    add(f"- EX = {grid['scored_passed']}/{grid['scored_total']} = "
        + ("**不可计算（分母为 0）**" if ex is None else f"`{ex:.1%}`"))
    add(f"- 不可归因占比：`{grid['unattributed_share']:.2%}`（§C.7 要求 ≤ 10%）")
    add("")
    add(_md_table(
        ["结构 \\ 语义", "低 low", "中 medium", "高 high"],
        [[level] + [
            f"{c['passed']}/{c['total']}" + ("" if c["pass_rate"] is None else f" ({c['pass_rate']:.0%})")
            for c in row
        ] for level, row in zip(grid_mod.LEVELS, grid["matrix"], strict=True)],
    ))
    add("")
    add("> ⚠️ 单元格 `0/0` **不是**「该格 0 分」，是「该格没有样本」。本轮覆盖率见 §3。")
    add("")

    add("## 3. 覆盖率读数（为什么 EX 不能当能力读数）")
    add("")
    add(_md_table(["计数", "值", "含义"], [
        ["记录条数", cov["n_records"], "本轮进入报告的用例数"],
        ["进分母", cov["n_scored"], "`scored=True`"],
        ["题面 execute", cov["n_execute_cases"], "应执行的用例数"],
        ["产出非空 SQL", cov["n_execute_with_sql"], "模型确实写了 SQL"],
        ["真拿到结果集", cov["n_execute_with_result"], "走到执行层并返回行（只有这条进得了等价判定）"],
        ["误澄清", cov["n_false_clarify"],
         "题面 execute 却收口 clarify ⇒ 计入 §C.4.4 误拒面，**不进** G-8（G-8 需第二轮回路）"],
        ["`hash_matches=None`", cov["hash_matches_none_n"], "金标哈希无从比对（终态在结果集之前）"],
        ["终态分布", json.dumps(cov["terminal_distribution"], ensure_ascii=False), "refuse/clarify/error 各多少"],
    ]))
    add("")
    ors = p["over_refusal_split"]
    add(f"- 误拒拆分（§C.4.4 两类错误分开统计）：`over_refusal` 共 {ors['total']} 条，其中 "
        f"{len(ors['with_bind_l4_degradation'])} 条带 `bind.l4` 降级"
        f"（{', '.join(ors['with_bind_l4_degradation']) or '—'}）→ 这部分**不计入模型误拒**："
        "沙箱无 embedding、L4 候选装配 JSON 解析失败是**评测器环境**缺陷。"
        f"剩余 {len(ors['without'])} 条（{', '.join(ors['without']) or '—'}）才是模型侧待查。")
    add("")

    add("## 4. §C.7 归因分布")
    add("")
    if p["attribution_distribution"]:
        add(_md_table(["类别", "条数"], [[k, v] for k, v in p["attribution_distribution"].items()]))
    else:
        add("_本轮没有失败用例进入归因（记录数为 0 或全过）。_")
    add("")
    if p["attribution_extra_categories"]:
        add("> 本窗口新增类别：" + "、".join(f"`{c}`" for c in p["attribution_extra_categories"])
            + "。**它们不进 §C.7 的模型归因分布** —— `sandbox_dialect_gap` 是沙箱与 PG 的方言差距，"
              "`gate_policy_gap` 是闸门自身判据缺陷，`terminal_shape_gap` 是"
              "**该拒答却收口成 clarify（且没出 SQL）** 的终态形状之争，"
              "混进模型类别 = 用别人的错误给模型打分。")
        add("")
    leak_n = int(p["attribution_distribution"].get("security_leak") or 0)
    if leak_n:
        add(f"> 🔴 **`security_leak` = {leak_n} 条**（应拒答题**真出数了**）—— 这是 P0 事故类，"
            "不是普通失败桶。逐条 case_id 见产物 JSON 的 `records[].attribution`。")
        add("")
    sp = p.get("attribution_split") or {}
    add(f"> 上表**只含失败**。另有 {len(sp.get('interaction_correct') or [])} 条"
        "「交互层判对」（该拒且拒 / 该澄清且澄清）与 "
        f"{len(sp.get('unscored') or [])} 条 `unscored`（infra_error 等未进判定）—— "
        "两者都不是失败，不进归因表也不进分母。"
        + ("" if not sp.get("failure_without_attribution") else
           f" ⚠️ {len(sp['failure_without_attribution'])} 条失败没拿到归因类别，"
           "已并入 `unattributed`（§C.7 兜底类），逐条 case_id 见 `attribution_split`。"))
    add("")

    add("## 5. 红队与跨租户（G-3 / G-4）")
    add("")
    rt = p.get("red_team")
    if not rt:
        add("_红队产物缺失 —— G-3/G-4 无输入。_")
        add("")
    else:
        add(_md_table(["项", "值"], [
            ["红队用例总数", rt["total"]],
            ["应拦 / 实覆盖 / **放行**", f"{rt['expect_block']} / {rt['checked']} / **{rt['leaked']}**"],
            ["断言级 PASS/FAIL/NOT_CHECKED", json.dumps(rt["assertion_counts"], ensure_ascii=False)],
            ["无任何失败断言的用例", rt["n_cases_clean"]],
            ["拒绝发生在哪道闸门", json.dumps(rt["reject_gates"], ensure_ascii=False)],
            ["gate2 在「生产可见列形状」下的异常", json.dumps(rt["gate2_visible_raise"], ensure_ascii=False)],
            ["未覆盖用例", "; ".join(f"{c['case_id']}" for c in rt["not_covered_cases"] or []) or "—"],
        ]))
        add("")
        add("### 5.1 失败四桶（逐条到 `redteam_results.json`）")
        add("")
        buckets = rt["failures_by_class"] or {}

        def ids(name: str) -> str:
            return ", ".join(buckets.get(name) or []) or "—"

        add(_md_table(["桶", "用例", "归属与性质"], [
            ["终态形状（refuse vs error）", ids("终态形状（refuse vs error）"),
             "红队集期望 `refuse`，而 gate1 先拦 ⇒ 推导终态是 `error(GATE_AST_REJECTED)`。"
             "**是「用例前提 vs 实现约定」之争**，不是漏拦（W1A + W2C/W4）"],
            ["规则身份归因（rule_id）", ids("规则身份归因（rule_id）"),
             "同一 deny 引用因**是否写表前缀**落 R06/R07（`probe_rule_identity.json` 实测 3:3，"
             "且不存在的列也报「查询包含受保护字段」）⇒ 归因统计失真（W2C）"],
            ["截断可观测性（truncated）", ids("截断可观测性（truncated）"),
             "`effective_limit` 载体缺失（P0 恒 None）⇒ `truncated` 无从置真（N-06 / FR-8.9，W2D/W4）"],
            ["可执行前提（用例假设能跑到 DB）", ids("可执行前提（用例假设能跑到 DB）"),
             "题面要求引用 `tenant_id`，而它是 deny 列 ⇒ 用例前提与语义包不相容（W1A）"],
        ]))
        add("")
        add("> ⚠️ 这四桶里**没有一桶**是「模型不安全」。`leaked=0` 的准确含义是：")
        add("> **三道闸门 + 执行层租户边界在 66 条攻击样本上没有放行**；"
            "它**不等于**「权限链路已在生产环境验证」（§17.4 RLS 行）。")
        add("")
        xt = p.get("cross_tenant")
        if xt:
            add(f"- 跨租户：RT-XT-* 共 {xt['n_cases']} 条，放行 {xt['leaked']} 条；"
                f"PG RLS 验证 = `{xt['pg_rls_verified']}` ⇒ **G-4 = PARTIAL**（沙箱无 RLS，I-6）。")
            add("")

    add("## 6. §17.6 口径不变量一致性三测")
    add("")
    c = p.get("consistency_17_6")
    if not c:
        add("_一致性三测未跑（`consistency_results.json` 缺失）⇒ I-1…I-6 仍是口头约定。_")
        add("")
    else:
        t1, t1b = c["test_1_tenant_boundary"], c["test_1b_boundary_efficacy"]
        t2, t3 = c["test_2_field_whitelist"], c["test_3_anchors"]
        paid = next((r for r in t1b["rows"] if r["asset"] == "v_order_paid"), None)
        add(_md_table(["测试", "判定", "本次实测"], [
            ["① 注入后 vs 手写租户谓词", "OK" if t1["ok"] else "FAIL",
             f"{t1['n_selected']}/{t1['n_required']} 条（租户 {t1['tenants_covered']}）；"
             "三条链路（冻结值 / `tenant_wrap` 手写谓词 / TEMP VIEW 边界）逐字相等"],
            ["① 前置：边界真的在过滤", "OK" if t1b["ok"] else "FAIL",
             f"{len(t1b['rows'])} 个租户域资产全 OK；"
             + (f"`v_order_paid` {paid['unfiltered_rows']} = "
                f"{'+'.join(str(v) for v in paid['per_tenant_rows'].values())}"
                if paid else "（无 v_order_paid 探针行）")],
            ["② 字段白名单（I-1）", "OK" if t2["ok"] else "FAIL",
             f"源码 {t2['source']['n_files_scanned']} 文件、工件 "
             f"{t2['artifacts']['n_files_scanned']} JSON 无读取命中；对照字段仍在冻结集 "
             f"{t2['control_field_still_in_dataset']} 处；正对照命中 "
             f"{t2['self_test']['patterns_hit']}/3"],
            ["③ 锚点回归（§4.7.2）", "OK" if t3["ok"] else "FAIL",
             f"本项目锚点 {sum(1 for x in t3['project'] if x['ok'])}/"
             f"{t3['n_project_anchors']} 命中；官方锚点 {t3['official_mismatch_n']} 条不符"
             "（**只作差异记录，不参与门禁**）；分歧点仍为 "
             f"`{t3['divergence']['actual_adopted']}`"],
        ]))
        add("")
        add(f"- 总判定：**{'四条不变量一致' if c['ok'] else '存在不变量被破坏'}**。")
        add("- ① 选出的用例都是单行聚合，其判别力来自「三条**独立实现** + 边界有效性探针」，"
            "不是来自行数 —— 这两件事分开声明，免得「1 行也敢叫一致性测试」的质疑指向错的地方。")
        add(f"- ⚠️ 07 §4.7.2 写「新立 **4 条**」锚点，`layering.PROJECT_ANCHORS` 实落 "
            f"{t3['n_project_anchors']} 条（hard / extra 各有两个形状）。差异如实登记，"
            "不为对上文档数字而删锚点。")
        add("")

    add("## 6.5 §C.4.3 核心指标口径一致性（G-7 的输入）")
    add("")
    mc = p.get("metric_consistency_c43")
    if not mc:
        add("_未跑：`backend/reports/w6/probe_metric_values.json` 缺失 ⇒ G-7 判 `NOT_AVAILABLE`。_")
        add("")
    else:
        add(
            f"- 可比对 **{mc['total']}** 条（题面命中单个核心指标词形 + gold 无 `GROUP BY` + "
            f"WHERE 只剩时间边界与默认谓词）；一致 **{mc['consistent']}** 条 = "
            f"**{mc['consistent_rate']:.1%}**（门槛 95%）；**不可归因差异 "
            f"{mc['unattributed']}** 条（门槛 0）。"
        )
        add(f"- 判定阈值：相对误差 < {mc['threshold_rel_error']:.1%}（§C.4.3 原文）。")
        add("")
        add(_md_table(
            ["指标", "比对条数", "一致", "最大相对误差", "差异背后的默认谓词"],
            [[name, d["n"], d["consistent"],
              "—" if d["max_rel_error"] is None else f"{d['max_rel_error']:.2%}",
              "；".join(d["predicates_behind_differences"]) or "（无差异行）"]
             for name, d in mc["per_metric"].items()],
        ))
        add("")
        add(f"- **比对口径（必须连着读）**：{mc['comparison_basis']}")
        add("- 覆盖指标：" + "、".join(f"`{m}`" for m in mc["metrics_covered"]) +
            f"；被排除 {mc['n_excluded']} 条（排除理由逐条在 `probe_metric_values.json` 的 `excluded`）。")
        add("")
    add("## 7. 沙箱能力缺口表（§17.4 —— **本表必须出现在评测报告里**）")
    add("")
    add("> 由 `eval/gap_table.py` 每次重新生成；`evidence` 列指向**本次 run 的实测事实**，")
    add("> 所以做不到「顺手把某行删掉让报告好看」。")
    add("")
    add(_md_table(
        ["能力", "PG", "SQLite", "评测侧处置", "进评测?", "本次实测证据", "补齐责任"],
        [[x["capability"], x["pg"], x["sqlite"], x["handling"],
          "是" if x["covered_by_eval"] else "否", x["evidence"], x["follow_up"]]
         for x in p["gap_table"]],
    ))
    add("")
    n_cov = sum(1 for x in p["gap_table"] if x["covered_by_eval"])
    add(f"- 全表 {len(p['gap_table'])} 行，其中 `covered_by_eval=True` 的行数 = **{n_cov}**。"
        "`covered_by_eval=False` 的行**不得**被任何门禁引用为通过依据。")
    add("")

    add("## 8. 已知限制（缺一条就可能被读成通过）")
    add("")
    for line in p["known_limitations"]:
        add(f"- {line}")
    add("")

    add("## 9. τ 与配置事实（N-25 / §18.4.1）")
    add("")
    tau = p["tau"]
    add(f"- `BINDING_TAU = {tau['BINDING_TAU']}`；占位环境下 "
        f"`binding_tau_is_calibrated = {tau['calibrated_under_eval_env']}`")
    add(f"- `deploy/.env` 各键**是否有值**：`{json.dumps(tau['deploy_env_declared'], ensure_ascii=False)}`"
        "（三个校准字段空 ⇒ 生产配置同样未校准；值本身不在本报告里出现）")
    add(f"- {tau['consequence']}")
    add("")

    add("## 10. 复算指令（零 LLM 优先；真打需额度）")
    add("")
    for cmd in p["reproduce"]:
        add(f"    {cmd}")
    add("")
    return "\n".join(g)


# ---------------------------------------------------------------------------
# 六、CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="W6 评测报告装配（只读产物，零 LLM）")
    ap.add_argument("--results", default=DEFAULT_RESULTS)
    ap.add_argument("--redteam", default=DEFAULT_REDPATH)
    ap.add_argument("--consistency", default=DEFAULT_CONSPATH)
    ap.add_argument("--pytest-log", default=DEFAULT_PYTEST_LOG)
    ap.add_argument("--integration-log", default=DEFAULT_INTEGRATION_LOG)
    ap.add_argument("--metric-probe", default=DEFAULT_METRIC_PROBE)
    ap.add_argument("--metric-values", default=DEFAULT_METRIC_VALUES)
    ap.add_argument("--pg-probe", default=DEFAULT_PG_PROBE)
    ap.add_argument("--cassette-probe", default=DEFAULT_CASSETTE_PROBE,
                    help="匣带可复算性探针产物（只影响 §8 的纪律二措辞）")
    ap.add_argument("--loadtest-receipt", default=DEFAULT_LOADTEST_RECEIPT,
                    help="W7 压测回执（w7.loadtest.receipt/1）= G-6 的唯一输入")
    ap.add_argument("--pressure-report", default=DEFAULT_PRESSURE_REPORT,
                    help="W7 压测报告路径，仅用于在报告里注明「谁欠这份数据、去哪查」")
    ap.add_argument("--json-out", default=DEFAULT_JSON_OUT)
    ap.add_argument("--md-out", default=DEFAULT_MD_OUT)
    ap.add_argument("--no-backup", action="store_true", help="默认覆盖前先 mv 备份（§C.6.1 纪律三）")
    args = ap.parse_args(argv)

    payload = build_payload(
        results_path=args.results, redteam_path=args.redteam, consistency_path=args.consistency,
        pytest_log=args.pytest_log, integration_log=args.integration_log,
        metric_probe_path=args.metric_probe, metric_values_path=args.metric_values,
        pg_probe_path=args.pg_probe, cassette_probe_path=args.cassette_probe,
        loadtest_receipt=args.loadtest_receipt, pressure_report=args.pressure_report,
    )
    md = render_markdown(payload)
    for path, text in (
        (args.json_out, json.dumps(payload, ensure_ascii=False, indent=2)),
        (args.md_out, md),
    ):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if os.path.exists(path) and not args.no_backup:
            stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
            os.replace(path, f"{path}.bak-{stamp}")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("written:", path)

    s = payload["gate_summary"]
    print(json.dumps(s, ensure_ascii=False))
    # 退出码只表达「门禁是否全过」，不表达「报告是否写成功」。
    return 0 if s["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
