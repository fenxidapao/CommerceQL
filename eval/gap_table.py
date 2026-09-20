"""沙箱能力缺口表（07 §17.4；08 §3.8 产出⑤）—— **必须出现在评测报告里**。

归属窗口：W6。

为什么这张表要由代码产出、而不是写在报告正文里
--------------------------------------------------------------------------
§17.4 的原文要求是"诚实声明"。手抄的声明会在下一轮评测里悄悄变成"上次已经补上了"，
而代码产出的表每跑一次就重新生成一次：`evidence` 列指向**本次 run 的实测事实**
（gate3 的 `decision` 值、RLS 在 SQLite 上的存在性、评测是否覆盖检索），
做不到"顺手把某行删掉让报告好看"。

红线对应：本表的任何一行都不允许出现"已覆盖"以外的乐观措辞；
`covered_by_eval=False` 的行**不得**被门禁引用为通过依据。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Final

__all__ = ["GapRow", "build_gap_table", "parallel_clause", "rls_follow_up"]


@dataclass(frozen=True, slots=True)
class GapRow:
    capability: str
    pg: str
    sqlite: str
    handling: str
    covered_by_eval: bool
    #: 本次 run 的实测证据（实现位置或观测值），不是"文档说会这样"。
    evidence: str
    #: 补齐责任（谁在什么条件下能把它变成已覆盖）。
    follow_up: str


_ROWS: Final[tuple[GapRow, ...]] = (
    GapRow(
        capability="EXPLAIN (FORMAT JSON) / gate3 成本闸门",
        pg="可用",
        sqlite="无该语法",
        handling="gate3 判 SKIPPED 并标注，**不得报告为通过**（07 §14.2 D6）",
        covered_by_eval=False,
        evidence="`app/guard/cost_gate.py` 无 `explain_plan` → `GateDecision.SKIPPED`"
                 "（评测执行器的 `explain()` 恒回 None，走的就是这条分支）",
        follow_up="真 EXPLAIN 的**语法/解析面**现在可测（本机 PG 有 `app` schema 与 8 个视图，"
                  "`tests/integration` 已证可达）；但成本**阈值**面仍不可校准 —— 事实表 0 行时 "
                  "planner 的行数/代价估计不带信息，`EXPLAIN` 出来的 `total_cost` 与真实数据下的量级无关。"
                  "⇒ 需 W7 灌入沙箱规模数据后，由 W2C 的 `drill_*` 与 W7 压测把本行变成已覆盖",
    ),
    GapRow(
        capability="RLS（行级权限）",
        pg="`ENABLE ROW LEVEL SECURITY` + `p_<table>_tenant` 策略 + `SET app.tenant_id`",
        sqlite="物理不存在 RLS",
        handling="评测用**执行层租户边界**模拟（I-6）：只读连接上对 `tenant_scoped` 资产建 "
                 "`CREATE TEMP VIEW`（SQLite 的 TEMP 优先解析 ⇒ 被测 SQL 非限定名自动命中视图），"
                 "被测 SQL 内**不出现** `tenant_id`，与生产一样「数据库层面看不到」；"
                 "**没有**按租户物化沙箱库副本（440 MB，零复制）；**这不等于**验证了 PG 策略本身。"
                 "⚠️ I-4「SQL 层改写」与 I-5「改写后仍过闸门」在本语义包下**不能同时成立**"
                 "（`tenant_id` 是 deny 列 ⇒ 任何手写租户谓词都被 gate1 R06/R07 拒，含 W1A 的 "
                 "`tenant_wrap` 派生表形态）⇒ 评测取与生产同构的那一半（谓词在被测 SQL 之外），"
                 "冲突上呈架构（见 RELAY），不由评测器私自改口径",
        covered_by_eval=False,
        evidence="07 §17.6 I-6；`backend/reports/w6/consistency_results.json` 本次实测："
                 "① 三条哈希链路（冻结值 / `tenant_wrap` 手写谓词 / TEMP VIEW 边界）在 "
                 "T_A·T_B·T_C 各 1 条用例上逐字相等；边界有效性探针 6 个租户域资产全 OK"
                 "（例：`v_order_paid` 494249 = 200000+175000+119249，逐租户均为严格子集且并集覆盖全量）",
        follow_up="PG 侧 RLS 专项（08 §3.2 v1.2 拆归 W6）。本轮实测订正：上一版写「hostname `pg` "
                  "解析失败 ⇒ 策略/GRANT 一律 UNVERIFIED」，那是**只查了一条 DSN** 的结论 —— "
                  "`tests/integration/**` 默认走 `localhost:5432`，真 PG 16 应答正常。实测现状："
                  "6 条 `p_<table>_tenant` 策略在位、6 张表 `FORCE ROW LEVEL SECURITY`、"
                  "`app_ro` 能读 `v_*` 视图；但 PG 的业务事实表**全空**（0 行 vs 沙箱 2,023,933 行）"
                  "⇒ 策略**存在性**已实测，**有效性**仍不可测（0 行对 0 行必然相等 = 假通过）。"
                  "补齐条件 = W7 往 PG 灌入与 `data/ecom_sandbox.db` 同规模的数据。"
                  "在此之前本行**不得**被任何门禁引用为通过依据",
    ),
    GapRow(
        capability="CLS / deny 列 / PII 掩码在 DB 侧的强制",
        pg="GRANT + 列级策略",
        sqlite="无 GRANT 概念，整库可读",
        handling="只验证**应用层**闸门（gate1 R07 / gate2 G2-DENY）与掩码前一跳，"
                 "不声明 DB 侧列权限生效",
        covered_by_eval=False,
        evidence="`app/guard/policy_gate.py` 的 G2-DENY 为应用侧判定",
        follow_up="集成测试 + `app_rw`/`app_ro` 授权断言（W1B `startup_assertions`）",
    ),
    GapRow(
        capability="pgvector（稠密检索）",
        pg="可用",
        sqlite="无",
        handling="评测**只测 SQL 生成质量**，不测向量检索；检索面为确定性夹具",
        covered_by_eval=False,
        evidence="07 §17.4 表第 3 行；评测执行器不接 `PgVectorStore`",
        follow_up="环境已就绪（实测 `app.embed_doc` 197 行 + hnsw 索引在位，`tests/integration` 的检索用例真连 PG）；"
                  "但**不进评测分母**是设计决定而非待办 —— 评测打的是 SQL 生成质量，"
                  "召回率归 W2B 的检索黄金集报告（阶段 2B DoD②）",
    ),
    GapRow(
        capability="tsvector / ts_rank_cd（稀疏检索）",
        pg="可用",
        sqlite="无",
        handling="同上：不进评测分母",
        covered_by_eval=False,
        evidence="`app/retrieval/sparse.py` 的 SQL 模板是 PG 方言",
        follow_up="同上（W2B）",
    ),
    GapRow(
        capability="PG 方言表达式（`date_trunc` / `::numeric` / `FILTER (WHERE)` / 窗口函数 / CTE）",
        pg="全部可用",
        sqlite="部分（窗口函数与 CTE 自 3.25 起可用；日期函数与类型转换语法缺失）",
        handling="失败用例归 `sandbox_dialect_gap`（**不进 §C.7 模型归因分布**），"
                 "单独成表，避免把沙箱差距记成模型能力",
        covered_by_eval=False,
        evidence="`planner.engine.SqlOutcome.state_payload()` 硬编码 `sql_dialect=\"postgres\"`",
        follow_up="评测与生产同方言执行需 PG 侧同快照（见 RELAY 给 W2D 的方言适配需求）",
    ),
    GapRow(
        capability="执行层驱动（`PgSqlExecutor` 的连接治理）",
        pg="psycopg + `set_config` GUC + 服务端命名游标 + `pg_cancel_backend` + `statement_timeout`",
        sqlite="不适用",
        handling="评测复用 `app.exec` 的**纯逻辑面**（`normalize_row`/`result_fingerprint`/"
                 "错误分类）与 `app.guard` 全量；驱动层为 eval 侧 SQLite 适配器"
                 "（实现同一个 `SqlExecutorPort` 签名），**已登记为方言适配需求交 W2D**",
        covered_by_eval=False,
        evidence="`app/exec/executor.py` 无方言抽象（W6 探针实测）",
        follow_up="W2D 落 `SqlExecutorPort` 的方言分层后，评测改注入 PG 适配器（消除本行）",
    ),
    GapRow(
        capability="LLM 出站（在线模型）",
        pg="n/a",
        sqlite="n/a",
        handling="评测层夹具：录制回放（07 §17.2）；无网络/无额度时相关门禁判 UNVERIFIED",
        covered_by_eval=False,
        evidence="产物 `eval/results_v1.json` 的 `config`（`live` / `mode` / `cassette`）"
                 "+ 逐条 `tokens` / `cost_cny`（本次 run 的实测值经 reporter 补进本行）",
        follow_up="有网环境全量真跑（见 RELAY 的成本外推与跑批指令）",
    ),
)


def _rls_head() -> str:
    return ("PG 侧 RLS 专项（08 §3.2 v1.2 拆归 W6）。本轮实测订正：上一版写「hostname `pg` "
            "解析失败 ⇒ 策略/GRANT 一律 UNVERIFIED」，那是**只查了一条 DSN** 的结论 —— "
            "`tests/integration/**` 默认走 `localhost:5432`，真 PG 16 应答正常。")


def parallel_clause(pg_facts: Mapping[str, Any]) -> str:
    """并行/串行等值对照的措辞（三态）。为什么评测侧要自带这项判据：
    W7 报过一次"并行把 `count(*)` 吃掉一截**且不报错**"—— 这类错 N-07 抓不到
    （租户策略照样生效，只是数变小），门禁顺路逮不到，只能由引用读数的人自己对照。

    ⚠️ **不自带句首标点**：前一句有没有句号由调用方知道，这里再写一个就会在报告里
    生成"。。"（实测踩过）。调用方按自己那一句的收尾选分隔符。
    """
    state = pg_facts.get("parallel_equality_ok")
    if state is None:
        return ("⚠️ 本轮**未做**并行/串行等值对照 ⇒ 上面这些 PG 读数的"
                "「并行路径下是否同一数」未测")
    if not state:
        return ("🔴 并行开/关**不等值** ⇒ 本行 PG 读数一律不得引用，先定位并行路径"
                "（数变小且不报错，N-07 抓不到）")
    return ("且并行开/关等值对照**通过**（逐关系 `count(*)` 相同、`EXPLAIN` 确有并行节点 ⇒ "
            "并行路径真被走到）")


def rls_follow_up(pg_facts: Mapping[str, Any] | None) -> str:
    """缺口表 RLS 行"下一步"的**唯一**措辞来源（跟着探测结果走，不写死当前事实）。

    为什么要派生：这一栏原先把"业务事实表全空（0 行）+ 补齐条件 = W7 灌数据"写死在散文里。
    W7 真把数据灌进来之后，报告里就同时存在"有 200 万行"和"全空"两句话 ——
    缺口表比判定更容易说谎，因为它读起来像背景。
    """
    head = _rls_head()
    if pg_facts is None:
        return head + "**本轮未探测真 PG** ⇒ 本行一切结论 UNVERIFIED（未探测 ≠ 不可达），不得引用为通过依据"
    n_pol = int(pg_facts.get("rls_policies_n", 0))
    n_forced = len(pg_facts.get("rls_forced_relations") or [])
    shape = (f"实测现状：{n_pol} 条 `p_<table>_tenant` 策略在位、{n_forced} 张表 "
             f"`FORCE ROW LEVEL SECURITY`、`app_ro` 可读 `v_*` 视图；")
    if not int(pg_facts.get("pg_fact_rows", 0)):
        return head + shape + (
            f"但 PG 的业务事实表 **0 行**（沙箱 {int(pg_facts.get('sqlite_fact_rows', 0)):,} 行）"
            "⇒ 策略**存在性**已实测、**有效性**仍不可测（0 行对 0 行必然相等 = 假通过）。"
            "补齐条件 = 往 PG 灌入与 `data/ecom_sandbox.db` 同规模的数据。"
            "在此之前本行**不得**被任何门禁引用为通过依据")
    if not pg_facts.get("rls_partition_ok"):
        return head + (f"PG 业务事实表已有 {int(pg_facts['pg_fact_rows']):,} 行"
                       "（沙箱同规模）⇒ 数据面已具备，但本窗口的探针**没有**给出"
                       "`rls_partition_ok`（逐租户可见数求和 == 属主总数 + 两条负对照）"
                       "⇒ 有效性**仍未实测**，本行保持不覆盖") + "。" + parallel_clause(pg_facts)
    return head + shape + (
        f"PG 业务事实表已有 {int(pg_facts['pg_fact_rows']):,} 行（沙箱 "
        f"{int(pg_facts.get('sqlite_fact_rows', 0)):,}）⇒ 策略**存在性与有效性均已实测**："
        "逐租户可见数求和恰等于属主总数（不重不漏），零上下文与未知租户两条负对照均返 0 行。"
        "⚠️ **但本行仍不构成 G-4 的完整证据**：评测主链路走的是 SQLite TEMP VIEW，"
        "「应用运行时经 PG 执行并设好 `app.tenant_id` + `app.shop_ids`」这一半未接（见 W6 交付 §8）"
    ) + "。" + parallel_clause(pg_facts)


def build_gap_table(
    *,
    extra_evidence: dict[str, str] | None = None,
    pg_facts: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """产出缺口表（可被报告器直接渲染）。

    `extra_evidence` 用本次 run 的实测值补强指定行；`pg_facts` 存在时 RLS 行的
    `follow_up` 改由 :func:`rls_follow_up` 派生（缺探测 ⇒ 只说"未探测"，绝不复述旧事实）。
    """
    rows = [asdict(r) for r in _ROWS]
    for row in rows:
        cap = row["capability"]
        for key, value in (extra_evidence or {}).items():
            if key in cap:
                row["evidence"] = f"{row['evidence']}；本次实测：{value}"
        if cap.startswith("RLS"):
            row["follow_up"] = rls_follow_up(pg_facts)
    return rows
