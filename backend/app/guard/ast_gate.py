"""闸门一：AST 静态审计 + LIMIT 注入 + 默认谓词注入（07 §7.2–§7.3）。

归属窗口：W2C（docs/08 §4.1）。**纯函数，禁依赖 LLM**（N-01 / N-03 / R-DEP-2）。

**节点内执行顺序（不可变，07 §7.1 + §5.3 节点 8）**：

    剥注释(R15) → 多语句检查(R02) → 语句类型(R01/R16)
    → 默认谓词注入（AST 层，必须在审计前 —— 注入的谓词必须被审计，否则成绕过后门）
    → LIMIT 归一化(R04) → 逐规则审计（审计对象 = 注入后的**最终 SQL**）

R14 字面量白名单的三类来源（07 §7.2 原文）：
    ① LIMIT 注入值（本模块注入，自动进白名单）
    ② 注入的默认谓词常量（从谓词 AST 提取）
    ③ 语义包声明的白名单常量（``allowlist["allowed_constants"]``）

allowlist 输入形状（与 W2A ``asset_allowlist(ctx)`` 的对齐点，见 reports/w2c/RELAY.md）：

    {
      "bundle_version": str,
      "assets": { <物理名>: {"logical_name": str, "domain": str,
                              "tenant_scoped": bool, "columns": {<列名>: <类型>}} },
      "joins": [ {"left": <逻辑名>, "right": <逻辑名>, "on_columns": [str, ...]} ],
      "deny_columns": ["<逻辑名>.<列名>", ...],
      "default_predicates": {<域>: ["<谓词 SQL 片段>", ...]},
      "allowed_constants": [str],
      "max_rows": int,          # 可选；R04 注入上限
    }
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.core.contracts import GateResult
from app.core.enums import AstRule, GateDecision, GateNo
from app.guard.rules import FUNCTION_DENYLIST, FUNCTION_DENYLIST_PREFIXES, RULES

__all__ = [
    "Gate1Warning",
    "Gate1Report",
    "run_gate1",
    "strip_comments",
    "MAX_ROWS_HARD_LIMIT",
    "DEFAULT_MAX_ROWS",
]

#: 硬上限（07 §7.3：``L = min(options.max_rows, MAX_ROWS_HARD_LIMIT=10000)``）。
MAX_ROWS_HARD_LIMIT: Final[int] = 10000
DEFAULT_MAX_ROWS: Final[int] = MAX_ROWS_HARD_LIMIT

#: R19 告警阈值：嵌套深度 > 5 记录（07 §7.2）。
MAX_SUBQUERY_DEPTH: Final[int] = 5
#: R20 告警阈值：顶层输出列 > 50 记录。
MAX_OUTPUT_COLUMNS: Final[int] = 50

_SELECT_LIKE: Final[tuple[type, ...]] = (exp.Select, exp.Union, exp.Intersect, exp.Except)

# sqlglot 30.x 把 ``from``/``with`` 两个 arg key 改名为 ``from_``/``with_``；
# 用 arg_types 探测，不硬编码版本。
_FROM_KEY: Final[str] = "from_" if "from_" in exp.Select.arg_types else "from"
_WITH_KEY: Final[str] = "with_" if "with_" in exp.Select.arg_types else "with"

_COMPARISONS: Final[tuple[type[exp.Expr], ...]] = (
    exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE,
)

_TEXT_TYPES: Final[frozenset[str]] = frozenset(
    {"text", "varchar", "character varying", "char", "bpchar", "uuid"}
)
_NUMERIC_TYPES: Final[frozenset[str]] = frozenset(
    {"numeric", "decimal", "int", "integer", "bigint", "smallint", "double precision",
     "real", "float", "money"}
)

_SYSTEM_SCHEMA_PREFIXES: Final[tuple[str, ...]] = (
    "information_schema", "pg_catalog", "pg_temp", "pg_toast",
)

_LINE_COMMENT: Final[re.Pattern[str]] = re.compile(r"--[^\n]*")
_BLOCK_COMMENT: Final[re.Pattern[str]] = re.compile(r"/\*.*?\*/", re.DOTALL)
_LIMIT_ALL: Final[re.Pattern[str]] = re.compile(r"\bLIMIT\s+ALL\b", re.IGNORECASE)


def _nearest_select(node: exp.Expr | None) -> exp.Select | None:
    """向上找最近的 SELECT scope（不穿越 Select 边界）。"""

    p = node.parent if node is not None else None
    while p is not None and not isinstance(p, exp.Select):
        p = p.parent
    return p


def _root_select_scopes(root: exp.Expr) -> list[exp.Select]:
    """根级输出 scope：Select 本身；集合查询（UNION/INTERSECT/EXCEPT）的每个分支。"""

    if isinstance(root, exp.Select):
        return [root]
    if isinstance(root, (exp.Union, exp.Intersect, exp.Except)):
        return [s for s in (root.this, root.expression) if isinstance(s, exp.Select)]
    inner = root.find(exp.Select)
    return [inner] if inner is not None else []


def _leaf_selects(root: exp.Expr) -> list[exp.Select]:
    """集合查询树的全部叶子 SELECT（分支可嵌套集合操作）。"""

    if isinstance(root, (exp.Union, exp.Intersect, exp.Except)):
        return _leaf_selects(root.this) + _leaf_selects(root.expression)
    if isinstance(root, exp.Select):
        return [root]
    inner = root.find(exp.Select)
    return [inner] if inner is not None else []


def _projection_names(select: exp.Select | None) -> frozenset[str] | None:
    """SELECT 输出列名集：``Alias``→别名、``Column``→列名、其余→规范化 SQL 文本。"""

    if select is None:
        return None
    names: set[str] = set()
    for proj in select.expressions:
        if isinstance(proj, exp.Alias):
            names.add(proj.alias)
        elif isinstance(proj, exp.Column):
            names.add(proj.name)
        else:
            names.add(proj.sql(dialect="postgres").lower())
    return frozenset(names)


# ---------------------------------------------------------------------------
# 注释剥离（R15）—— 字符串感知，防止 `/*'*/` 这类注入态注释破坏后续解析
# ---------------------------------------------------------------------------

def strip_comments(sql: str) -> str:
    """剥离全部注释（R15），**字符串/美元引用字面量内部不动**。

    为什么不用正则一把梭：红队用例 ``WHERE 1=1 /*'*/ OR /*'*/ 1=1`` 的注释里含引号，
    无状态正则会把字符串边界搞乱，反而制造出原本不存在的解析错误。
    """

    out: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        # 单引号字符串（含 '' 转义与 E'...' 反斜杠转义——按逐个引号翻状态即可）
        if ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i : min(j + 1, n)])
            i = j + 1
            continue
        # 双引号标识符
        if ch == '"':
            j = i + 1
            while j < n:
                if sql[j] == '"':
                    if j + 1 < n and sql[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i : min(j + 1, n)])
            i = j + 1
            continue
        # 美元引用（$$...$$ 或 $tag$...$tag$）
        if ch == "$":
            m = re.match(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$", sql[i:])
            if m:
                tag = m.group(0)
                end = sql.find(tag, i + len(tag))
                if end == -1:
                    out.append(sql[i:])
                    i = n
                    continue
                out.append(sql[i : end + len(tag)])
                i = end + len(tag)
                continue
        # 块注释
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            out.append(" ")
            i = n if end == -1 else end + 2
            continue
        # 行注释
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end == -1 else end
            continue
        out.append(ch)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# 结果对象
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Gate1Warning:
    """告警级规则的记录（R17–R20）。**告警不拒绝**（U-16）——记录后查询继续。"""

    rule: AstRule
    #: 内部归因信息（进 gate_detail / 日志；不下发用户）。
    detail: str


@dataclass(frozen=True, slots=True)
class Gate1Report:
    """gate1 完整出参。``gate_result`` 是端口契约（C-02：rule_id 必进 gate_detail）。"""

    gate_result: GateResult
    #: 注入谓词与 LIMIT 之后的**最终 SQL**（W4 写回 state ``sql_text`` / 交给 gate3、execute）。
    rewritten_sql: str
    warnings: tuple[Gate1Warning, ...]
    #: §7.3 的 ``limit_injected``（``{"injected": bool, "original_limit": int}`` 或 None）。
    limit_injected: Mapping[str, Any] | None
    #: 注入的默认谓词（审计可追溯，07 §5.2 ``applied_predicates``）。
    applied_predicates: tuple[str, ...]
    #: R15 是否发生了注释剥离（改写级记录）。
    comments_stripped: bool

    @property
    def passed(self) -> bool:
        return self.gate_result.passed


def _build_reject(rule: AstRule) -> Gate1Report:
    rd = RULES[rule]
    return Gate1Report(
        gate_result=GateResult(
            gate_no=GateNo.AST,
            passed=False,
            decision=GateDecision.REJECT,
            rule_id=rd.rule.value,
            reason=rd.user_message,
        ),
        rewritten_sql="",
        warnings=(),
        limit_injected=None,
        applied_predicates=(),
        comments_stripped=False,
    )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def run_gate1(sql: str, allowlist: Mapping[str, Any]) -> Gate1Report:
    """执行 gate1（完整流程，见模块 docstring 的顺序）。"""

    if not isinstance(sql, str) or not sql.strip():
        return _build_reject(AstRule.R01_STATEMENT_TYPE)

    # --- R15：先剥离全部注释再解析（07 §7.2 原文）---
    stripped = strip_comments(sql)
    comments_stripped = stripped != sql

    # --- R02：多语句（先于单语句解析）---
    try:
        statements = sqlglot.parse(stripped, dialect="postgres")
    except ParseError:
        # 解析失败 = 形态不支持（语法错误应在上游 gen_sql/repair 被截获）。
        return _build_reject(AstRule.R01_STATEMENT_TYPE)
    if len(statements) != 1 or statements[0] is None:
        return _build_reject(AstRule.R02_MULTI_STATEMENT)
    root = statements[0]

    # --- R16 / R01：语句级 SET / Command ---
    # 归因消歧（依冻结红队集）：`SET LOCAL search_path` → R16（事务级篡改）；
    # 其余 SET/RESET/其他非 SELECT 命令 → R01（语句形态不支持）。
    if isinstance(root, (exp.Set, exp.Command)):
        if (
            isinstance(root, exp.Set)
            and re.search(r"search_path", stripped, re.IGNORECASE)
            and re.search(r"\bSET\s+LOCAL\b", stripped, re.IGNORECASE)
        ):
            return _build_reject(AstRule.R16_SEARCH_PATH)
        return _build_reject(AstRule.R01_STATEMENT_TYPE)

    # --- R01：只允许 SELECT / 带 WITH 的 SELECT（含集合查询分支）---
    if not isinstance(root, (*_SELECT_LIKE, exp.Subquery, exp.Paren)):
        return _build_reject(AstRule.R01_STATEMENT_TYPE)

    # LIMIT ALL 被 sqlglot 归一化为"无 LIMIT"→ 文本层剥除后按无 LIMIT 注入
    # （红队 RT-R04-003 冻结口径 = rewrite；与 07 §7.3 "拒绝"行的分歧已登记 RELAY）。
    if _LIMIT_ALL.search(stripped):
        stripped = _LIMIT_ALL.sub(" ", stripped)
        comments_stripped = True

    # R18 的判据在注入前取（"无界" = 原始 SQL 顶层无 LIMIT）。
    had_top_level_limit = _top_level_limit(root) is not None

    # --- 默认谓词注入（AST 层，必须先于审计）---
    applied = _inject_predicates(root, allowlist)

    # R14 白名单 = ① LIMIT 注入值 ② 谓词常量 ③ 语义包声明常量（07 §7.2 三类）。
    effective_limit = _effective_limit(allowlist)
    literal_allow = set(allowlist.get("allowed_constants") or ())
    literal_allow.add(str(effective_limit))
    for pred_sql in applied:
        node = _parse_predicate(pred_sql)
        if node is not None:
            literal_allow |= _predicate_constants(node)

    # --- R04：LIMIT 归一化（§7.3 六情形）---
    limit_report = _normalize_limit(root, effective_limit)
    if isinstance(limit_report, Gate1Report):
        return limit_report  # LIMIT ALL/NULL/0 → 拒绝
    limit_injected = limit_report

    # R14 白名单第①类 = 全部 LIMIT/OFFSET 字面量（注入值、保留的合法 LIMIT、
    # 既有 OFFSET —— 分页/行界参数，不是数据值；§7.3 明确支持 OFFSET 情形）。
    for lim in root.find_all(exp.Limit):
        if isinstance(lim.expression, exp.Literal):
            literal_allow.add(_literal_key(lim.expression))
    for off in root.find_all(exp.Offset):
        if isinstance(off.expression, exp.Literal):
            literal_allow.add(_literal_key(off.expression))

    # --- 逐规则审计（对象 = 注入后的最终 AST）---
    audit = _Auditor(allowlist, frozenset(literal_allow))
    blocked = audit.run(root)
    if blocked is not None:
        return blocked

    warnings = list(audit.warnings)
    _warn_unbounded_sort(warnings, root, had_top_level_limit)

    return Gate1Report(
        gate_result=GateResult(
            gate_no=GateNo.AST,
            passed=True,
            decision=GateDecision.PASS,
        ),
        rewritten_sql=root.sql(dialect="postgres"),
        warnings=tuple(warnings),
        limit_injected=limit_injected,
        applied_predicates=tuple(applied),
        comments_stripped=comments_stripped,
    )


# ---------------------------------------------------------------------------
# LIMIT 归一化（§7.3）
# ---------------------------------------------------------------------------

def _top_level_limit(root: exp.Expr) -> exp.Limit | None:
    return root.args.get("limit") if hasattr(root, "args") else None


def _effective_limit(allowlist: Mapping[str, Any]) -> int:
    """``L = min(options.max_rows, MAX_ROWS_HARD_LIMIT=10000)``（07 §7.3）。"""

    max_rows = allowlist.get("max_rows", DEFAULT_MAX_ROWS)
    try:
        return min(int(max_rows), MAX_ROWS_HARD_LIMIT)
    except (TypeError, ValueError):
        return MAX_ROWS_HARD_LIMIT


def _normalize_limit(
    root: exp.Expr, effective: int
) -> Gate1Report | Mapping[str, Any] | None:
    """返回 ``None``（保留原 LIMIT）/ 注入说明 mapping / 拒绝 Gate1Report。"""

    query = root
    limit = _top_level_limit(query)

    if limit is None:
        # 子查询有 LIMIT 顶层无 → 仍注入顶层（§7.3：子查询 LIMIT 不限制最终行数）。
        query.set("limit", exp.Limit(expression=exp.Literal.number(effective)))
        return {"injected": True}

    expr = limit.expression
    # LIMIT NULL → 与 LIMIT ALL 同判：无效上界 → 注入 L（红队集 RT-R04-003 冻结口径；
    # 与 07 §7.3 "拒绝"行的分歧在 reports/w2c/RELAY.md 登记，提请架构裁定）。
    if isinstance(expr, exp.Null):
        query.set("limit", exp.Limit(expression=exp.Literal.number(effective)))
        return {"injected": True, "original_limit": "NULL"}
    if isinstance(expr, exp.Literal) and not expr.is_string:
        try:
            n = int(expr.this)
        except (TypeError, ValueError):
            return _build_reject(AstRule.R04_FORCE_LIMIT)
        if n == 0:
            return _build_reject(AstRule.R04_FORCE_LIMIT)  # §7.3：LIMIT 0 属无效查询
        if n > effective:
            query.set(
                "limit",
                exp.Limit(expression=exp.Literal.number(effective)),
            )
            return {"injected": True, "original_limit": n}
        return None  # n ≤ L：保留
    # LIMIT 表达式非字面量（子查询/函数）→ 无法静态证明有界 → 拒绝。
    return _build_reject(AstRule.R04_FORCE_LIMIT)


# ---------------------------------------------------------------------------
# 默认谓词注入（AST 层）
# ---------------------------------------------------------------------------

def _parse_predicate(predicate_sql: str) -> exp.Expr | None:
    try:
        node = sqlglot.parse_one(predicate_sql, dialect="postgres")
    except ParseError:
        return None
    if isinstance(node, exp.Select):
        where = node.args.get("where")  # 谓词误写成完整查询时兜底取 where
        if where is None:
            return None
        predicate = where.this
        return predicate if isinstance(predicate, exp.Expr) else None
    return node


def _predicate_constants(node: exp.Expr) -> frozenset[str]:
    """从谓词 AST 提取字面量常量（R14 白名单第②类来源）。"""

    vals: set[str] = set()
    for lit in node.find_all(exp.Literal):
        vals.add(_literal_key(lit))
    return frozenset(vals)


def _inject_predicates(root: exp.Expr, allowlist: Mapping[str, Any]) -> list[str]:
    """对查询内每个**物理表实例**注入其域的默认谓词，返回已注入谓词（审计可追溯）。"""

    pred_by_domain: Mapping[str, Sequence[str]] = allowlist.get("default_predicates") or {}
    if not pred_by_domain:
        return []
    assets: Mapping[str, Any] = allowlist.get("assets") or {}
    cte_names = {c.alias for c in root.find_all(exp.CTE)}
    applied: list[str] = []

    for table in list(root.find_all(exp.Table)):
        name = table.name
        if not name or name in cte_names:
            continue
        asset = assets.get(name)
        if asset is None:
            continue  # 未声明资产 → R05 会拒绝；注入不为其背书
        predicates = pred_by_domain.get(asset.get("domain", ""), [])
        if not predicates:
            continue
        qualifier = table.alias_or_name
        # 谓词必须挂到**包含该表实例的 SELECT** 的 WHERE 上。
        parent_select: exp.Select | None = None
        p = table.parent
        while p is not None:
            if isinstance(p, exp.Select):
                parent_select = p
                break
            p = p.parent
        if parent_select is None:
            continue
        for pred_sql in predicates:
            node = _parse_predicate(pred_sql)
            if node is None:
                continue  # 非法谓词由 W2A 校验器负责；此处不放大
            for col in node.find_all(exp.Column):
                if not col.table:
                    col.set("table", exp.to_identifier(qualifier))
            where = parent_select.args.get("where")
            cond = node
            if where is not None:
                cond = exp.And(this=where.this, expression=node)
            parent_select.set("where", exp.Where(this=cond))
            applied.append(pred_sql)
    return applied


# ---------------------------------------------------------------------------
# 审计器（R01–R14、R16 阻断 + R17/R19/R20 告警；R18 在 run_gate1 内补）
# ---------------------------------------------------------------------------

class _Auditor:
    """逐规则审计。首个阻断命中即停（规则顺序 = 07 §7.2 表序）。"""

    def __init__(
        self,
        allowlist: Mapping[str, Any],
        literal_allowlist: frozenset[str] = frozenset(),
    ) -> None:
        self.assets: Mapping[str, Any] = allowlist.get("assets") or {}
        self.joins: Sequence[Mapping[str, Any]] = allowlist.get("joins") or []
        self.deny_columns: frozenset[str] = frozenset(allowlist.get("deny_columns") or ())
        self.allowed_constants: frozenset[str] = literal_allowlist
        self.warnings: list[Gate1Warning] = []

    # -- 主流程 --

    def run(self, root: exp.Expr) -> Gate1Report | None:
        cte_names = {c.alias for c in root.find_all(exp.CTE)}

        # R12：递归 CTE（P0 直接拒绝）
        for w in root.find_all(exp.With):
            if w.args.get("recursive"):
                return _build_reject(AstRule.R12_RECURSIVE_CTE)

        # R09：函数黑名单（**先于表检查** —— 表函数形态 ``FROM dblink(...) AS t(...)``
        # 的函数名藏在 Table.this 里，若先查表会被 R05 抢归因；红队 RT-R09-006 tag = R09）
        for fname in self._called_functions(root):
            if fname in FUNCTION_DENYLIST or fname.startswith(FUNCTION_DENYLIST_PREFIXES):
                return _build_reject(AstRule.R09_FUNCTION_DENYLIST)

        # R13：UNION/INTERSECT/EXCEPT 每个分支独立过 R05/R06/R07（07 §7.2 原文）。
        # 全树遍历天然覆盖分支内的列/表，但**归因**必须落 R13（红队 RT-R13-* 冻结口径）：
        # 集合查询的分支违规 → rule_id=R13，即使违规形态是 R05/R06/R07。
        if isinstance(root, (exp.Union, exp.Intersect, exp.Except)):
            for leaf in _leaf_selects(root):
                verdict = self._branch_violation(leaf, cte_names)
                if verdict is not None:
                    return verdict

        # R05/R08/R16(前缀)：物理表白名单 + 系统 schema（先于 R03，保证 rule_id 归因）
        for table in root.find_all(exp.Table):
            name = table.name
            if not name or name in cte_names:
                continue
            full = ".".join(p for p in (table.catalog, table.db, name) if p)
            if full.startswith(_SYSTEM_SCHEMA_PREFIXES) or name.startswith(
                _SYSTEM_SCHEMA_PREFIXES
            ):
                return _build_reject(AstRule.R08_SYSTEM_SCHEMA)
            if table.db or table.catalog:
                # 带 schema 前缀 = 绕白名单形态（07 §7.8 R16 用例：public.v_orders）
                return _build_reject(AstRule.R16_SEARCH_PATH)
            if name not in self.assets:
                return _build_reject(AstRule.R05_TABLE_ALLOWLIST)

        # R03：SELECT *（**根 scope** 的投影项；COUNT(*) 不受影响 —— 它不是投影项）。
        # 只查根 scope 的依据：内层 SELECT * 不直接暴露列（外层投影才是数据出口），
        # 且冻结红队 RT-R19-001 的嵌套 SELECT * 必须 warn 放行（否则 R19 永远测不到）。
        for top_select in _root_select_scopes(root):
            for proj in top_select.expressions:
                if isinstance(proj, exp.Star) or (
                    isinstance(proj, exp.Column) and isinstance(proj.this, exp.Star)
                ):
                    return _build_reject(AstRule.R03_SELECT_STAR)

        # R10/R11：JOIN 路径与笛卡尔积。
        # 归因口径（依冻结红队集；与 07 §7.2 文字的映射有出入，已在 RELAY 登记）：
        #   R10 = 无 ON/USING（含 CROSS JOIN / 逗号连接）、ON 无任何列（`ON 1=1`）、
        #         或 (左,右) 表对不在认证 join_path 内；
        #   R11 = 表对已认证但 ON 条件列 ⊄ 认证列（条件列错配 → 笛卡尔风险）。
        joins = list(root.find_all(exp.Join))
        for j in joins:
            verdict = self._join_verdict(j)
            if verdict is not None:
                return verdict

        # R06/R07：列白名单 + 敏感列
        col_verdict = self._check_columns(root, cte_names)
        if col_verdict is not None:
            return col_verdict

        # R14：字面量策略
        verdict = self._check_literals(root)
        if verdict is not None:
            return verdict

        # --- 告警级（不拒绝）---
        self._warn_implicit_cast(root)
        depth = self._max_select_depth(root)
        # 07 §7.2：「嵌套深度 > 5 → 记录」—— 深度 = Select 总层数（含顶层）。
        # 红队 RT-R19-001（顶层+5 层派生表 = 6 层）预期告警，与本口径一致。
        if depth > MAX_SUBQUERY_DEPTH:
            self.warnings.append(
                Gate1Warning(AstRule.R19_SUBQUERY_DEPTH, f"select_depth={depth}")
            )
        top = root if isinstance(root, exp.Select) else root.find(exp.Select)
        if top is not None and len(top.expressions) > MAX_OUTPUT_COLUMNS:
            self.warnings.append(
                Gate1Warning(
                    AstRule.R20_OUTPUT_COLUMNS,
                    f"output_columns={len(top.expressions)}",
                )
            )
        return None

    # -- R10/R11 --

    def _join_verdict(self, join: exp.Join) -> Gate1Report | None:
        """单条 JOIN 的路径判定。``None`` = 通过；否则返回拒绝报告（R10 或 R11）。"""

        right = join.this
        if not isinstance(right, exp.Table) or not right.name:
            return None  # 派生表 / 表函数：内部已被全树审计（表函数见 R09）
        parent = join.parent
        if not isinstance(parent, exp.Select):
            return None

        # 左侧候选 = 同一 FROM 子句中先于本 join 引入的表
        lefts: list[str] = []
        frm = parent.args.get(_FROM_KEY)
        if frm is not None:
            for t in frm.find_all(exp.Table):
                lefts.append(t.name)
        for prev in parent.args.get("joins", []):
            if prev is join:
                break
            for t in prev.find_all(exp.Table):
                lefts.append(t.name)

        on_expr = join.args.get("on")
        using = join.args.get("using")
        cond_src = on_expr if on_expr is not None else using
        cond_cols = (
            {c.name for c in cond_src.find_all(exp.Column)} if cond_src is not None else set()
        )

        # ① 无 ON/USING（含 CROSS JOIN / 逗号连接）→ R10
        if on_expr is None and using is None:
            return _build_reject(AstRule.R10_JOIN_PATH)
        # ② ON 无任何列（`ON 1 = 1`）→ 无条件连接 → R10
        if not cond_cols:
            return _build_reject(AstRule.R10_JOIN_PATH)

        right_asset = self.assets.get(right.name, {})
        right_logical = right_asset.get("logical_name", right.name)
        for left in dict.fromkeys(lefts):
            left_asset = self.assets.get(left, {})
            left_logical = left_asset.get("logical_name", left)
            for entry in self.joins:
                pair = {entry.get("left"), entry.get("right")}
                if {left_logical, right_logical} != pair:
                    continue
                # ③ 认证边存在：条件列必须 ⊆ 认证列，否则笛卡尔风险 → R11
                if not cond_cols <= set(entry.get("on_columns") or []):
                    return _build_reject(AstRule.R11_CARTESIAN)
                return None
        # ④ 无认证边 → R10
        return _build_reject(AstRule.R10_JOIN_PATH)

    # -- R06/R07 --

    def _check_columns(self, root: exp.Expr, cte_names: set[str]) -> Gate1Report | None:
        """全树列引用解析（07 §7.2：含 GROUP/ORDER/HAVING/窗口，全树遍历天然覆盖）。"""

        for col in root.find_all(exp.Column):
            resolved = self._resolve_column(col, cte_names)
            if resolved is None:
                # 无法归属到任何已声明资产/CTE 输出的列（含多义）→ 拒绝。
                return _build_reject(AstRule.R06_COLUMN_ALLOWLIST)
            owner, colname = resolved
            kind = owner[0]
            logical = owner[1]
            columns = owner[2] or frozenset()
            if kind == "asset":
                if f"{logical}.{colname}" in self.deny_columns:
                    return _build_reject(AstRule.R07_DENY_COLUMNS)
                if colname not in columns:
                    return _build_reject(AstRule.R06_COLUMN_ALLOWLIST)
            else:  # cte / derived：底层列已在其定义 scope 被审计
                if colname not in columns:
                    return _build_reject(AstRule.R06_COLUMN_ALLOWLIST)
        return None

    def _branch_violation(
        self, leaf: exp.Select, cte_names: set[str]
    ) -> Gate1Report | None:
        """R13 分支检查：叶子 SELECT 内的 R05/R06/R07 违规统一归因 R13。"""

        for table in leaf.find_all(exp.Table):
            name = table.name
            if not name or name in cte_names:
                continue
            if name not in self.assets:
                return _build_reject(AstRule.R13_UNION_SCOPE)
        for col in leaf.find_all(exp.Column):
            resolved = self._resolve_column(col, cte_names)
            if resolved is None:
                return _build_reject(AstRule.R13_UNION_SCOPE)
            (kind, logical, cols), colname = resolved
            if kind != "asset":
                continue
            if f"{logical}.{colname}" in self.deny_columns:
                return _build_reject(AstRule.R13_UNION_SCOPE)
            if colname not in (cols or frozenset()):
                return _build_reject(AstRule.R13_UNION_SCOPE)
        return None

    def _resolve_column(
        self, col: exp.Column, cte_names: set[str]
    ) -> tuple[tuple[str, str, frozenset[str] | None], str] | None:
        """解析一列的归属。

        返回 ``(owner, colname)``；``owner = (kind, logical_or_name, columns|None)``，
        ``kind ∈ {"asset", "cte", "derived"}``。无法解析（含多义归属）→ ``None``。
        """

        colname = col.name
        alias = col.table
        scope = _nearest_select(col)
        while scope is not None:
            mapping = self._scope_tables(scope, cte_names)
            if alias:
                owner = mapping.get(alias)
                if owner is not None:
                    return owner, colname
            else:
                owners = [
                    (kind, name, cols)
                    for kind, name, cols in mapping.values()
                    if cols is not None and colname in cols
                ]
                if len(owners) == 1:
                    return owners[0], colname
                if len(owners) > 1:
                    return None  # 多义归属
            scope = _nearest_select(scope.parent)
        return None

    def _scope_tables(
        self, scope: exp.Select, cte_names: set[str]
    ) -> dict[str, tuple[str, str, frozenset[str] | None]]:
        """本 scope 的 ``alias -> (kind, logical_or_name, 输出列集)``。"""

        out: dict[str, tuple[str, str, frozenset[str] | None]] = {}

        def put(alias: str, kind: str, name: str, cols: frozenset[str] | None) -> None:
            out.setdefault(alias, (kind, name, cols))

        frm = scope.args.get(_FROM_KEY)
        tables: list[exp.Table] = list(frm.find_all(exp.Table)) if frm is not None else []
        for j in scope.args.get("joins", []):
            tables.extend(t for t in j.find_all(exp.Table))
        for t in tables:
            name = t.name
            if not name:
                continue
            asset = self.assets.get(name)
            if asset is not None:
                put(t.alias_or_name, "asset", asset.get("logical_name", name),
                    frozenset((asset.get("columns") or {}).keys()))
            elif name in cte_names:
                cols = self._cte_output_columns(scope, name)
                put(t.alias_or_name, "cte", name, cols)
        # 派生表（子查询别名）
        for sub in scope.find_all(exp.Subquery):
            if sub.alias:
                inner = sub.find(exp.Select)
                put(sub.alias, "derived", sub.alias, _projection_names(inner))
        return out

    def _cte_output_columns(self, scope: exp.Select, cte_name: str) -> frozenset[str] | None:
        for cte in scope.ctes:
            if cte.alias == cte_name:
                return _projection_names(cte.this)
        return None

    # -- R09 --

    def _called_functions(self, root: exp.Expr) -> set[str]:
        names: set[str] = set()
        for fn in root.find_all(exp.Func):
            rendered = fn.sql(dialect="postgres")
            head = rendered.split("(", 1)[0]
            m = re.search(r"([A-Za-z_][A-Za-z0-9_.]*)$", head)
            if m:
                names.add(m.group(1).split(".")[-1].lower())
        return names

    # -- R14 --

    #: 字面量可以合法出现的"值位"父节点：与列比较（列-常量）、集合成员、LIKE 模式、
    #: BETWEEN 边界、IS NULL 结构。行界（LIMIT/OFFSET）单独放行。
    _VALUE_PARENTS: Final[tuple[type, ...]] = (
        exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE,
        exp.Like, exp.ILike, exp.Is, exp.In, exp.Between,
    )

    def _check_literals(self, root: exp.Expr) -> Gate1Report | None:
        """R14 字面量策略 —— 按冻结红队集（RT-R14-* / RT-R17-*）可执行的口径：

        **拒绝**：① 字面量-字面量比较（``1 = 1`` / ``'x' = 'x'`` 恒真注入通道）；
        ② 不在任何列比较上下文、也不在白名单内的自由字面量（投影/函数实参等）。
        **放行**：① 列-常量比较 / LIKE 模式 / BETWEEN 边界 / IN 成员 / IS NULL
        （类型失配交 R17 告警，不在此拒）；② LIMIT/OFFSET 行界字面量；
        ③ 谓词常量与语义包声明常量（``literal_allowlist``）。

        ⚠️ 本口径与 07 §7.2 "除三类外不得出现字面量"的字面读法有出入（红队集
        RT-R17-* 明确要求 ``region_code = 440000`` 放行 + 告警）—— 分歧已登记
        reports/w2c/RELAY.md 提请架构裁定；红队集是 DoD① 的判定基准。
        """

        for lit in root.find_all(exp.Literal):
            if _literal_key(lit) in self.allowed_constants:
                continue
            if not self._literal_in_value_position(lit):
                return _build_reject(AstRule.R14_LITERAL_POLICY)
        return None

    def _literal_in_value_position(self, lit: exp.Literal) -> bool:
        parent = lit.parent
        if isinstance(parent, (exp.Limit, exp.Offset)):
            return True
        if isinstance(parent, self._VALUE_PARENTS):
            return self._sibling_has_column(lit)
        return False

    def _sibling_has_column(self, lit: exp.Expr) -> bool:
        """比较/集合节点的**其他操作数**是否含列引用（含列侧嵌套表达式）。"""

        parent = lit.parent
        if parent is None:
            return False
        operands: list[exp.Expr | None] = []
        if isinstance(parent, exp.Between):
            operands = [parent.this, parent.args.get("low"), parent.args.get("high")]
        elif isinstance(parent, exp.In):
            operands = [parent.this, *parent.args.get("expressions", [])]
        elif isinstance(parent, exp.Binary):
            operands = [parent.this, parent.expression]
        else:  # Is 等
            operands = [parent.this, parent.expression]
        for op in operands:
            if op is None or op is lit:
                continue
            if op.find_ancestor(exp.Column) is not None or list(op.find_all(exp.Column)):
                return True
        return False

    # -- R17 --

    def _warn_implicit_cast(self, root: exp.Expr) -> None:
        for cmp_ in root.find_all(*_COMPARISONS):
            left, right = cmp_.this, cmp_.expression
            col, lit = None, None
            if isinstance(left, exp.Column) and isinstance(right, exp.Literal):
                col, lit = left, right
            elif isinstance(right, exp.Column) and isinstance(left, exp.Literal):
                col, lit = right, left
            if col is None or lit is None:
                continue
            if lit.is_string:
                if self._column_type(col) in _NUMERIC_TYPES:
                    self.warnings.append(
                        Gate1Warning(
                            AstRule.R17_IMPLICIT_CAST,
                            f"numeric column vs string literal: {col.name}",
                        )
                    )
            else:
                if self._column_type(col) in _TEXT_TYPES:
                    self.warnings.append(
                        Gate1Warning(
                            AstRule.R17_IMPLICIT_CAST,
                            f"text column vs numeric literal: {col.name}",
                        )
                    )

    def _column_type(self, col: exp.Column) -> str | None:
        cte_names: set[str] = set()
        resolved = self._resolve_column(col, cte_names)
        if resolved is None:
            return None
        (kind, logical, _cols), colname = resolved
        if kind != "asset":
            return None
        for a in self.assets.values():
            if a.get("logical_name") == logical:
                return (a.get("columns") or {}).get(colname)
        return None

    # -- R19 --

    def _max_select_depth(self, node: exp.Expr) -> int:
        def walk(n: exp.Expr, depth: int) -> int:
            best = depth
            for child in n.iter_expressions():
                nd = depth + (1 if isinstance(child, exp.Select) else 0)
                best = max(best, walk(child, nd))
            return best

        base = 1 if isinstance(node, exp.Select) else 0
        return walk(node, base)


def _warn_unbounded_sort(
    warnings: list[Gate1Warning], root: exp.Expr, had_top_level_limit: bool
) -> None:
    """R18：原始 SQL 顶层有 ORDER BY 且无 LIMIT → 告警（成本交 gate3 判）。"""

    if had_top_level_limit:
        return
    query = root
    order = query.args.get("order") if hasattr(query, "args") else None
    if order is not None:
        warnings.append(Gate1Warning(AstRule.R18_UNBOUNDED_SORT, "top-level ORDER BY without LIMIT"))


def _literal_key(lit: exp.Literal) -> str:
    """字面量规范键：字符串取原文；数字取 ``str(int|float)`` 规范形。"""

    if lit.is_string:
        return str(lit.this)
    try:
        num = float(lit.this)
        if num.is_integer():
            return str(int(num))
        return repr(num)
    except (TypeError, ValueError):
        return str(lit.this)
