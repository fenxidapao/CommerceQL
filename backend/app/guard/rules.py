"""闸门一规则表 —— **规则唯一来源**（07 §7.2；docs/08 §4.1 归属 W2C）。

单一事实来源（single source of truth）：

- **判据**（每条规则怎么查）在 ``ast_gate.py``，但**每条规则必须在这里注册**才能生效；
- **处置级别**以 ``app.core.enums.AST_RULE_SEVERITY`` 为准（本文件不复制一份 —— 那是第二真相）；
- **错误码映射**与**用户可见文案**（07 §7.6）在这里 —— 文案**零 schema 细节**（不泄露表名/列名，
  DoD②；负向断言由 ``tests/redteam`` 逐条执行）。

注册纪律：
1. 新增规则 = ①``enums.AstRule``（W0）→ ②本文件注册 → ③红队集补用例（W1A）→ ④``ast_gate`` 落判据。
   跳过任何一步 = 规则"存在但永不触发"，比没有规则更危险（绿灯假象）。
2. ``RULES`` 必须覆盖 ``AstRule`` 全集（模块导入期断言，缺一条直接 ``ImportError``）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from app.core.enums import AST_RULE_SEVERITY, AstRule, AstRuleSeverity, ErrorCode

__all__ = [
    "RuleDef",
    "RULES",
    "RULE_BY_ID",
    "FUNCTION_DENYLIST",
    "USER_MESSAGE_FOR_COST",
]


@dataclass(frozen=True, slots=True)
class RuleDef:
    """单条规则的定义（判据在 ``ast_gate``，这里只放身份与出口）。

    ⚠️ ``user_message`` 是**用户可见文案**（07 §7.6）：
    - 不得含任何物理表名 / 列名 / schema 名（DoD②，红队逐条断言）；
    - ``R14`` 文案**不应到达用户**（到达 = 渲染层 bug，须告警）。
    """

    rule: AstRule
    severity: AstRuleSeverity
    #: 阻断级规则的错误码；REWRITE/WARN 级为 ``None``（不产生错误出口）。
    error_code: ErrorCode | None
    user_message: str
    #: ``True`` = 该文案只允许进内部日志/告警，**不得**下发用户（目前仅 R14）。
    internal_only: bool = False


#: ``AST-R09`` 函数黑名单（07 §7.2 原文逐项；``dblink*`` / ``postgres_fdw`` 按前缀匹配）。
#: ``current_setting`` 默认全拒（†：实际业务 SQL 不需要它；放开须语义包显式声明，P0 未放开）。
FUNCTION_DENYLIST: Final[frozenset[str]] = frozenset(
    {
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "pg_sleep",
        "pg_sleep_for",
        "pg_sleep_until",
        "pg_cancel_backend",
        "pg_terminate_backend",
        "pg_reload_conf",
        "pg_rotate_logfile",
        "lo_import",
        "lo_export",
        "lo_create",
        "lo_get",
        "lo_put",
        "current_setting",
        "set_config",
        "pg_notify",
        "pg_advisory_lock",
        "pg_advisory_lock_shared",
        "pg_advisory_xact_lock",
        "pg_advisory_xact_lock_shared",
        "pg_try_advisory_lock",
        "pg_try_advisory_lock_shared",
    }
)

#: ``dblink*`` / ``postgres_fdw`` 系列按**前缀**匹配（07 §7.2 表内写法）。
FUNCTION_DENYLIST_PREFIXES: Final[tuple[str, ...]] = ("dblink", "postgres_fdw")


def _msg_form() -> str:
    return "这个查询的形态系统不支持，请换一种问法"


def _msg_scope() -> str:
    return "查询涉及的数据范围超出你的权限"


def _msg_protected() -> str:
    return "查询包含受保护字段"


def _msg_too_many_columns() -> str:
    return "查询字段过多，请指明你需要的字段"


_RULE_LIST: Final[tuple[RuleDef, ...]] = (
    RuleDef(
        AstRule.R01_STATEMENT_TYPE,
        AstRuleSeverity.BLOCK,
        ErrorCode.GATE_AST_REJECTED,
        _msg_form(),
    ),
    RuleDef(
        AstRule.R02_MULTI_STATEMENT,
        AstRuleSeverity.BLOCK,
        ErrorCode.GATE_AST_REJECTED,
        _msg_form(),
    ),
    RuleDef(
        AstRule.R03_SELECT_STAR,
        AstRuleSeverity.BLOCK,
        ErrorCode.GATE_AST_REJECTED,
        _msg_too_many_columns(),
    ),
    # R04 改写级：注入/改写 LIMIT（§7.3），无错误出口。
    RuleDef(
        AstRule.R04_FORCE_LIMIT,
        AstRuleSeverity.REWRITE,
        None,
        _msg_form(),
    ),
    RuleDef(
        AstRule.R05_TABLE_ALLOWLIST,
        AstRuleSeverity.BLOCK,
        ErrorCode.FORBIDDEN_SCOPE,
        _msg_scope(),
    ),
    RuleDef(
        AstRule.R06_COLUMN_ALLOWLIST,
        AstRuleSeverity.BLOCK,
        ErrorCode.FORBIDDEN_SCOPE,
        _msg_protected(),
    ),
    # R07 列级屏蔽优先于一切（07 §7.2）→ PII_BLOCKED。
    RuleDef(
        AstRule.R07_DENY_COLUMNS,
        AstRuleSeverity.BLOCK,
        ErrorCode.PII_BLOCKED,
        _msg_protected(),
    ),
    RuleDef(
        AstRule.R08_SYSTEM_SCHEMA,
        AstRuleSeverity.BLOCK,
        ErrorCode.GATE_AST_REJECTED,
        _msg_form(),
    ),
    RuleDef(
        AstRule.R09_FUNCTION_DENYLIST,
        AstRuleSeverity.BLOCK,
        ErrorCode.GATE_AST_REJECTED,
        "查询使用了不允许的函数",
    ),
    RuleDef(
        AstRule.R10_JOIN_PATH,
        AstRuleSeverity.BLOCK,
        ErrorCode.GATE_AST_REJECTED,
        _msg_scope(),
    ),
    RuleDef(
        AstRule.R11_CARTESIAN,
        AstRuleSeverity.BLOCK,
        ErrorCode.GATE_AST_REJECTED,
        _msg_scope(),
    ),
    RuleDef(
        AstRule.R12_RECURSIVE_CTE,
        AstRuleSeverity.BLOCK,
        ErrorCode.GATE_AST_REJECTED,
        _msg_form(),
    ),
    RuleDef(
        AstRule.R13_UNION_SCOPE,
        AstRuleSeverity.BLOCK,
        ErrorCode.GATE_AST_REJECTED,
        _msg_scope(),
    ),
    # R14：**不应到达用户** —— 到达即说明渲染层有 bug（07 §7.6 原文：到达即告警）。
    RuleDef(
        AstRule.R14_LITERAL_POLICY,
        AstRuleSeverity.BLOCK,
        ErrorCode.GATE_AST_REJECTED,
        "这个查询的形态系统不支持，请换一种问法",
        internal_only=True,
    ),
    # R15 改写级：剥注释后重新解析（§7.8 断言语义一致），无错误出口。
    RuleDef(
        AstRule.R15_COMMENT_STRIP,
        AstRuleSeverity.REWRITE,
        None,
        _msg_form(),
    ),
    RuleDef(
        AstRule.R16_SEARCH_PATH,
        AstRuleSeverity.BLOCK,
        ErrorCode.GATE_AST_REJECTED,
        _msg_form(),
    ),
    # --- R17–R20 告警级：命中**不得拒绝**（U-16；写成拒绝 = 误杀正常查询 = 实现缺陷）---
    RuleDef(
        AstRule.R17_IMPLICIT_CAST,
        AstRuleSeverity.WARN,
        None,
        _msg_form(),
    ),
    RuleDef(
        AstRule.R18_UNBOUNDED_SORT,
        AstRuleSeverity.WARN,
        None,
        _msg_form(),
    ),
    RuleDef(
        AstRule.R19_SUBQUERY_DEPTH,
        AstRuleSeverity.WARN,
        None,
        _msg_form(),
    ),
    RuleDef(
        AstRule.R20_OUTPUT_COLUMNS,
        AstRuleSeverity.WARN,
        None,
        _msg_too_many_columns(),
    ),
)

#: 规则注册表（**唯一来源**）。key = ``AstRule``。
RULES: Final[Mapping[AstRule, RuleDef]] = {rd.rule: rd for rd in _RULE_LIST}

#: 规则编号 → 定义（红队断言按 ``rule_id`` 字符串取）。
RULE_BY_ID: Final[Mapping[str, RuleDef]] = {rd.rule.value: rd for rd in _RULE_LIST}

# --- 导入期自检（缺一条 = 部署即假绿灯，宁可在导入时炸）---
_missing = set(AstRule) - set(RULES)
_extra = set(RULES) - set(AstRule)
if _missing or _extra:  # pragma: no cover - 防御性导入断言
    raise ImportError(
        f"guard/rules.py 与 enums.AstRule 不同步：missing={sorted(_missing)} extra={sorted(_extra)}"
    )

_sev_mismatch = {
    rd.rule.value: (rd.severity, AST_RULE_SEVERITY[rd.rule])
    for rd in _RULE_LIST
    if rd.severity != AST_RULE_SEVERITY[rd.rule]
}
if _sev_mismatch:  # pragma: no cover - 防御性导入断言
    raise ImportError(f"guard/rules.py 的 severity 与 enums.AST_RULE_SEVERITY 不一致：{_sev_mismatch}")


#: gate3 拒绝时的用户文案（07 §7.6 末行）；具体收窄建议由
#: ``app.core.enums.DEFAULT_SUGGESTIONS[COST_TOO_HIGH]`` 下发（同一事实一处定义）。
USER_MESSAGE_FOR_COST: Final[str] = (
    "这次查询范围太大，建议把时间范围收窄，或加上过滤条件"
)

del _missing, _extra, _sev_mismatch
