"""出站脱敏与请求体构造 —— **白名单而非黑名单**（N-12 的实现，07 §10.5）。

归属窗口：W3A｜位置由 07 §10.5 指定：`llm/egress_guard.py`，且在 **payload 构造时**生效
（不是"发送前过滤"）。这两者的差别是本质的：

    构造时白名单 = 只有我登记过的字段**存在**，未登记的字段**无法被表示**；
    发送前过滤   = 字段都能进来，靠一个过滤器拦 —— 过滤器漏一个键就漏一次数据。

07 原话："**白名单优于黑名单：黑名单会漏，白名单不会**。"

## 三道防线（强度递减，但都要有 —— 纵深防御，不是三选一）

| # | 防线 | 拦什么 | 机制 |
|---|---|---|---|
| 1 | **键白名单**（主） | 任何未登记字段 | `EgressPayload.from_mapping` 严格模式：未知键 → **抛错**，不静默丢弃 |
| 2 | **键名扫描** | 就算有人绕过数据类、直接拼 dict | `assert_no_forbidden_keys` 递归扫键名（`rows`/`result_set`/`deny_*`/`tenant_*`…） |
| 3 | **值级形态扫描** | 字段名合法但**值**被塞了明细 | 类型断言 + 长度上限 + SQL 特征扫描（**只对"外部来源"字段**，见下） |

## 🔴 为什么值级扫描**不**覆盖语义包摘要与方言说明

`dialect_note` / `output_schema` / `constraints` 是**我们自己的稳定文本**，
它们**合法地含有 SQL 关键词**（方言说明当然要写 "使用 SELECT 而非 SELECT ALL"）。
对它们做 SQL 特征扫描 = 每天误杀自己。这就是 07 说的"白名单/黑名单"之分在**值级**的对应物：
**只对"外部来源"字段做形态扫描**，对"自产稳定文本"只做类型断言。

外部来源字段（`EXTERNALLY_SOURCED_FIELDS`）：

- `raw_question` —— 用户输入。**允许含 SQL**：§10.5 ① 明确允许"归一化后的用户问题"出站，
  用户自己贴一句 SQL 提问是合法用法，拦它 = 拦正常业务。所以对它只做**长度上限**
  与**"结果集形态"检测**（明细数据的到达方式必然是"一大坨带分隔符的行"）。
- `history_questions` —— 会话历史。§10.5 ⑥ 禁止"会话历史中的 **SQL 与结果**"，
  所以对**它**禁 SQL 特征（且字段名就是 `_questions`，多轮上下文只能带问题）。
- `error_digest` —— 库/执行错误摘要。§10.5 ⑤ 禁止"库原始错误"，
  §8.9 允许的是**脱敏后的摘要** → 同样禁 SQL 特征（原始报错里最常见的泄漏物就是语句片段）。

## 🔴 N-17：`sql_text` **永不回灌 prompt**

`generated_sql` / `sql_text` / `sql` 这一组键名被**永久**列在禁用键里，不是"记得别传"，
而是"传了就炸"。N-17 是硬约束（见 `core/contracts.py` 的 `PlannerPort` docstring）。
连带后果：**有界纠错（`repair`）拿不到失败的那条 SQL**，它只能吃 `error_digest`。
这是设计如此，不是本模块的缺陷 —— 见 `reports/w3a/RELAY.md §给 W3B/W3C`。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from typing import Any, Final

from app.llm.errors import LlmEgressViolation

__all__ = [
    "EgressPayload",
    "ALLOWED_WIRE_KEYS",
    "FORBIDDEN_KEY_EXACT",
    "FORBIDDEN_KEY_SUBSTR",
    "EXTERNALLY_SOURCED_FIELDS",
    "MAX_RAW_QUESTION_CHARS",
    "MAX_ERROR_DIGEST_CHARS",
    "MAX_SEMANTIC_SUMMARY_CHARS",
    "MAX_FEW_SHOT_TURNS",
    "MAX_CANDIDATES",
    "MAX_CANDIDATE_CHARS",
    "build_wire_request",
    "assert_no_forbidden_keys",
    "normalize_key",
    "wire_keys_of",
]


# ============================================================================
# 一、白名单：登记的**出站字段**（改这里 = 改契约，必须同步 07 §10.5）
# ============================================================================

#: HTTP 请求体里允许出现的**顶层键**。07 §10.5 的"允许出站"五行只能表达为这些：
ALLOWED_WIRE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "model",            # 模型 ID（路由表产物）
        "messages",         # 只有 system（稳定前缀）+ user（变化后缀）两条
        "max_tokens",
        "temperature",
        "response_format",  # {"type": "json_object"}
        "thinking",         # ★ 实测：关闭思考的唯一有效写法是 {"type": "disabled"}
        "user",             # ★ 只放 user_scope 的**哈希**，见 §10.3 规则 2 与 N-12 的冲突处理
    }
)

def _payload_keys() -> frozenset[str]:
    """`EgressPayload` 的字段集 —— 由数据类自身推导，**不手写第二份**（手写一定会漂）。

    ⚠️ 抽成函数而不是模块级常量：`fields()` 必须在类定义完成**之后**才能调用，
    而模块级常量会在类之前求值并**静默拿到空集** —— 那会让白名单变成"什么都不许"，
    或者更糟（若写反了判断）变成"什么都许"。
    """
    return frozenset(f.name for f in fields(EgressPayload))


# ============================================================================
# 二、禁用键名（键级扫描，防线 2）
# ============================================================================

#: **精确**匹配的禁用键名（归一化后比较：小写 + 去掉 `_`/`-`/空格）。
FORBIDDEN_KEY_EXACT: Final[frozenset[str]] = frozenset(
    {
        # ①结果集任何行 / ②明细数据
        "rows", "row", "rowdata", "result", "results", "resultset", "data", "items",
        "records", "record", "tuples", "columns_data", "cell", "cells",
        # ③真实值样本
        "sample", "samples", "samplejson", "samplevalue", "distinctvalues", "values", "value",
        # ⑤库原始错误
        "rawerror", "dberror", "errorraw", "traceback", "stacktrace", "sqlstate",
        # ⑥会话历史中的 SQL 与结果（N-17 同源）
        "sql", "sqltext", "generatedsql", "history", "sessionhistory", "previoussql",
        # ⑦其他租户任何信息
        "tenant", "tenantid", "othertenant", "shopids", "userid",
        # 内部结构（不是内容，但混进来即说明构造路径错了）
        "fingerprint", "maskoutcome", "gate_detail", "gate_detail_json",
    }
)

#: **子串**匹配的禁用键名（比精确匹配更能拦住 `deny_columns_list` / `raw_result_rows` 这类变体）。
#: ⚠️ 短词（如 `data`）**不进**这里 —— 子串匹配 `data` 会连 `metadata` 一起杀掉。
FORBIDDEN_KEY_SUBSTR: Final[frozenset[str]] = frozenset(
    {
        "resultset", "samplejson", "denycolumn", "rawerror", "dberror",
        "generatedsql", "sqltext", "othertenant", "tenantid", "rowcount",
    }
)


def normalize_key(key: str) -> str:
    """键名归一化：小写并去掉 `_` / `-` / 空格 —— 让 `result_set` 与 `resultSet` 同罪。"""
    return re.sub(r"[\s_-]+", "", key).lower()


def assert_no_forbidden_keys(obj: Any, *, _path: str = "$") -> None:
    """递归扫描任意结构的**键名**，命中禁用键 → `LlmEgressViolation`。

    ⚠️ 报错信息**只给键名与路径，绝不回显值** —— 否则错误信息本身成了泄露通道
    （07 §10.5 的取向：脱敏模块的报错也必须脱敏）。
    """
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise LlmEgressViolation(
                    "出站请求体存在非字符串键名", detail={"path": _path, "key_type": type(key).__name__}
                )
            norm = normalize_key(key)
            if norm in FORBIDDEN_KEY_EXACT or any(s in norm for s in FORBIDDEN_KEY_SUBSTR):
                raise LlmEgressViolation(
                    "出站请求体命中禁用键名（N-12：结果集/明细/值样本/原始错误/他租户信息禁止出站）",
                    detail={"path": f"{_path}.{key}"},
                )
            assert_no_forbidden_keys(value, _path=f"{_path}.{key}")
    elif isinstance(obj, (list, tuple)):
        for idx, item in enumerate(obj):
            assert_no_forbidden_keys(item, _path=f"{_path}[{idx}]")


# ============================================================================
# 三、值级扫描（防线 3）
# ============================================================================

#: 做**形态扫描**的字段（外部来源）。自产稳定文本（方言说明/JSON Schema/约束提示）不在其中。
EXTERNALLY_SOURCED_FIELDS: Final[frozenset[str]] = frozenset(
    {"raw_question", "history_questions", "error_digest"}
)

#: 用户问题长度上限。超长不是"用户话多"，而是"有人把数据集粘进来了"。
MAX_RAW_QUESTION_CHARS: Final[int] = 2000
MAX_ERROR_DIGEST_CHARS: Final[int] = 1000
MAX_SEMANTIC_SUMMARY_CHARS: Final[int] = 40_000
MAX_FEW_SHOT_TURNS: Final[int] = 8
#: 候选名条数上限（精筛/L4 的 Top-N 量级；07 §6.7 融合截断后不会有几百条）。
MAX_CANDIDATES: Final[int] = 200
#: 单条候选名长度上限（表名/列名/指标名不可能更长；更长 = 有人在塞行内容）。
MAX_CANDIDATE_CHARS: Final[int] = 120

#: SQL **语句**特征（不是"出现 SELECT 这个词"）。
#: 必须有 `SELECT…FROM` / `INSERT INTO` / `UPDATE…SET` / `DELETE FROM` 这类**子句组合**，
#: 否则会把"select 前十个 SKU"这种正常中文问句误杀。
_SQL_STATEMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"\bselect\b[\s\S]{0,4000}?\bfrom\b"
    r"|\binsert\b[\s\S]{0,500}?\binto\b"
    r"|\bupdate\b[\s\S]{0,500}?\bset\b"
    r"|\bdelete\b[\s\S]{0,500}?\bfrom\b"
    r"|\b(drop|alter|truncate|create)\b\s+\b(table|index|view|schema|database)\b",
    re.IGNORECASE,
)

#: "结果集形态"：一行里出现 ≥3 个被逗号/制表符分隔的短字段，且**多行重复**。
#: 明细数据只有这一种到达方式；正常自然语言不会连续两行都长这样。
_TABULAR_ROW_RE: Final[re.Pattern[str]] = re.compile(r"^\s*[\w\u4e00-\u9fff .\-]{1,40}\s*[,\t|]\s*(?=[^\n]*[,\t|])")


def _check_shape(name: str, value: Any) -> None:
    """类型断言：出站字段只允许 `str`（容器形态是"明细数据"的必然外观）。"""
    if isinstance(value, str):
        return
    raise LlmEgressViolation(
        "出站字段只接受字符串；容器形态疑似明细数据（N-12）",
        detail={"field": name, "value_type": type(value).__name__},
    )


def _check_no_sql_statement(name: str, text: str) -> None:
    """对**禁止含 SQL** 的字段做语句特征扫描（N-17 / §10.5 ⑥⑤）。"""
    if text and _SQL_STATEMENT_RE.search(text):
        raise LlmEgressViolation(
            "该字段禁止携带 SQL 语句（N-17：sql_text 永不回灌 prompt；§10.5 ⑥ 禁会话历史中的 SQL）",
            detail={"field": name},
        )


def _check_no_tabular_rows(text: str) -> None:
    """检测"结果集形态"（多行分隔字段）——只对用户问题生效。"""
    rows = [ln for ln in text.splitlines() if _TABULAR_ROW_RE.match(ln)]
    if len(rows) >= 3:
        raise LlmEgressViolation(
            "字段值呈现结果集形态（多行分隔字段）——疑似粘贴明细数据（N-12 ②）",
            detail={"matched_rows": len(rows)},
        )


# ============================================================================
# 四、受控数据类（防线 1：唯一构造入口）
# ============================================================================

@dataclass(frozen=True, slots=True)
class EgressPayload:
    """唯一允许出站的载荷。

    🔴 **新增字段 = 改契约**：必须同时改①本类②07 §10.5 的"允许出站"表③
    `tests/unit/test_llm_egress_guard.py` 的字段集快照断言。三处漏一处，CI 会红。

    与 07 §10.5 "允许出站"五行的对应关系：

    | 07 §10.5 允许 | 本类字段 |
    |---|---|
    | ① 语义包摘要（表/列注释、指标定义、同义词） | `semantic_summary` |
    | ② 方言与输出格式说明 | `dialect_note` / `output_schema` |
    | ③ 归一化后的用户问题 | `raw_question` |
    | ④ 已脱敏的 few-shot | `few_shots` |
    | ⑤ 脱敏后的错误摘要（§8.9） | `error_digest` |
    """

    #: ③ 用户问题。**唯一**允许出站的用户输入（07 §10.3 构造层）。允许含 SQL —— 那是用户自己的话。
    raw_question: str

    #: ① 语义包摘要。**由调用方经 `SemanticBundlePort` 取后传进来**。
    #:
    #: ⚠️ 为什么不由本模块自己 import `app.semantics` 取：`.importlinter` 的 `layers` 里
    #: `app.semantics` 排在 `app.llm` **之前**（= 更高层），而 R-DEP-1 规定
    #: "只能依赖严格更低层" ⇒ **低层不能 import 高层**。所以本模块拿不到语义包，
    #: 只能接收已取好的摘要文本。这不是绕路，是分层约束的正确形状。
    semantic_summary: str = ""

    #: ② 方言说明（自产稳定文本）。
    dialect_note: str = ""

    #: ② 输出 JSON Schema（自产稳定文本）。★ 实测约束：用了 `response_format=json_object`
    #: 就必须让**整体消息里出现 "json" 字样**，否则上游直接 400。本字段与系统角色说明
    #: 共同保证该条件成立（见 `client.build_wire_request` 的断言）。
    output_schema: str = ""

    #: ④ 已脱敏的 few-shot。**只收 (问题, SQL) 二元组**；SQL 侧由内容流水线负责脱敏。
    few_shots: tuple[tuple[str, str], ...] = ()

    #: 约束提示（自产稳定文本）。
    constraints: str = ""

    #: ⑤ 脱敏后的错误摘要（§8.9）。禁含 SQL 语句（N-17）。
    error_digest: str = ""

    #: ① **候选资产名列表**（精筛 / L4 打分器需要）。
    #:
    #: 🔴 这是本窗口**唯一新增**的登记字段，依据 = §10.5 ① "语义包摘要（表/列注释、
    #: 指标定义、**同义词**）" —— 候选名就是语义包资产的**名字**（表名/列名/指标名/别名），
    #: 是 §10.5 ① 的子集，**不是**结果集内容。它必须显式登记才合法（白名单语义）。
    #: 登记去向：`DELIVERY.md §登记` 与 `RELAY.md §给架构`。
    #:
    #: ⚠️ 三处约束：① 不属于 `STABLE_PREFIX_VARS` → 只能出现在**变化后缀**（每次请求都不同）；
    #: ② 有条数与单条长度上限（防有人把明细塞成"候选"）；
    #: ③ 与 `raw_question` 同受"结果集形态"扫描。
    candidates: tuple[str, ...] = ()

    #: 会话历史 —— **只允许"问题"**，不含 SQL 与结果（§10.5 ⑥）。
    #: 且按 §10.3 规则 3，它**必须**落在变化后缀里。
    history_questions: tuple[str, ...] = ()

    #: 语义包版本。前缀按它冻结（§10.3 前缀缓存布局）。
    bundle_version: str = ""

    #: 用户级缓存隔离用的**哈希**（16 hex，与 `cache/keys.user_scope_hash` 同源）。
    #: 🔴 N-12 明列 `user_id` 为 PII 禁出站，而 §10.3 规则 2 又要求"开 user_id 隔离" ——
    #: 二者字面冲突。裁定：**出站的是哈希，不是 `user_id`**，且只进 HTTP `user` 参数、
    #: **不进任何 prompt 文本**（进文本就会被模型复述）。见 `reports/w3a/DELIVERY.md` Q-冲突A。
    user_scope: str | None = None

    def __post_init__(self) -> None:
        _check_shape("raw_question", self.raw_question)
        _check_shape("semantic_summary", self.semantic_summary)
        _check_shape("dialect_note", self.dialect_note)
        _check_shape("output_schema", self.output_schema)
        _check_shape("constraints", self.constraints)
        _check_shape("error_digest", self.error_digest)
        _check_shape("bundle_version", self.bundle_version)
        _check_shape("history_questions", "@".join(self.history_questions))
        _check_shape("few_shots", repr(self.few_shots))

        if not self.raw_question.strip():
            raise LlmEgressViolation("`raw_question` 不得为空 —— 没有问题的调用一定是构造错误")
        if len(self.raw_question) > MAX_RAW_QUESTION_CHARS:
            raise LlmEgressViolation(
                "`raw_question` 超长（疑似粘贴数据集）",
                detail={"field": "raw_question", "limit": MAX_RAW_QUESTION_CHARS},
            )
        if len(self.error_digest) > MAX_ERROR_DIGEST_CHARS:
            raise LlmEgressViolation(
                "`error_digest` 超长（§8.9 要求的是**摘要**，不是原始报错）",
                detail={"field": "error_digest", "limit": MAX_ERROR_DIGEST_CHARS},
            )
        if len(self.semantic_summary) > MAX_SEMANTIC_SUMMARY_CHARS:
            raise LlmEgressViolation(
                "`semantic_summary` 超长",
                detail={"field": "semantic_summary", "limit": MAX_SEMANTIC_SUMMARY_CHARS},
            )
        if len(self.few_shots) > MAX_FEW_SHOT_TURNS:
            raise LlmEgressViolation(
                "few-shot 轮数超上限（前缀体积失控 = 成本失控）",
                detail={"field": "few_shots", "limit": MAX_FEW_SHOT_TURNS},
            )

        # 外部来源字段的形态扫描
        _check_no_tabular_rows(self.raw_question)
        _check_no_sql_statement("history_questions", "\n".join(self.history_questions))
        _check_no_sql_statement("error_digest", self.error_digest)

        # 候选名：条数/长度/形态三重上限（防止"候选"成为明细数据的后门）
        if len(self.candidates) > MAX_CANDIDATES:
            raise LlmEgressViolation(
                "候选名条数超上限", detail={"field": "candidates", "limit": MAX_CANDIDATES}
            )
        for cand in self.candidates:
            _check_shape("candidates", cand)
            if len(cand) > MAX_CANDIDATE_CHARS:
                raise LlmEgressViolation(
                    "单条候选名超长（候选是**名字**，不是行内容）",
                    detail={"field": "candidates", "limit": MAX_CANDIDATE_CHARS},
                )
            _check_no_tabular_rows(cand)

        if self.user_scope is not None and not re.fullmatch(r"[0-9a-f]{16}", self.user_scope):
            raise LlmEgressViolation(
                "`user_scope` 必须是 16 位十六进制哈希（不得是明文 user_id —— N-12 把 user_id 列为 PII）",
                detail={"field": "user_scope"},
            )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> EgressPayload:
        """唯一构造入口：**严格模式**（未知键 → 抛错，不静默丢弃）。

        🔴 为什么是"抛错"而不是"丢弃"：丢弃会让调用方以为参数生效了（静默失败），
        而白名单的**全部价值**就在于"字段要么被登记、要么当场暴露"。
        这与本项目既有取向一致（`config.py` 的"宁可起不来，也不要带错配置跑起来"）。
        """
        if not isinstance(payload, Mapping):
            raise LlmEgressViolation(
                "payload 必须是 Mapping", detail={"got": type(payload).__name__}
            )
        known = _payload_keys()
        unknown = sorted(set(payload) - known)
        if unknown:
            raise LlmEgressViolation(
                "payload 含未登记的出站字段（N-12 白名单：新增字段必须显式登记）",
                detail={"unknown_keys": unknown, "registered_keys": sorted(known)},
            )
        assert_no_forbidden_keys(dict(payload))
        # `few_shots` 允许以 list 形式传入（JSON 友好），规范化成 tuple 再交给类型断言
        norm: dict[str, Any] = dict(payload)
        if "few_shots" in norm:
            norm["few_shots"] = tuple((str(a), str(b)) for a, b in norm["few_shots"])
        if "history_questions" in norm:
            norm["history_questions"] = tuple(str(q) for q in norm["history_questions"])
        if "candidates" in norm:
            norm["candidates"] = tuple(str(c) for c in norm["candidates"])
        return cls(**norm)

    def as_dict(self) -> dict[str, Any]:
        """白名单投影（**不做任何序列化**）—— 测试用它做字段集快照。"""
        return {f.name: getattr(self, f.name) for f in fields(self)}


# ============================================================================
# 五、请求体构造（唯一出站点）
# ============================================================================

def build_wire_request(
    payload: EgressPayload,
    *,
    model: str,
    system_text: str,
    user_text: str,
    max_tokens: int,
    temperature: float,
    thinking: bool,
    json_output: bool = True,
    deny_columns: Sequence[str] = (),
) -> dict[str, Any]:
    """构造**唯一**合法的 HTTP 请求体。除本函数外，任何地方都不得拼这个 dict。

    参数里没有"会话历史""结果集""SQL"这类口子 —— 它们只能经 `EgressPayload` 的
    已登记字段进来，而那已经过三道防线。
    """
    if not model:
        raise LlmEgressViolation("model 不得为空（路由表必须给出模型）")

    messages = [
        # ⚠️ system 是**稳定前缀**：07 §10.3 硬规则 1/3 —— 前缀里不得出现
        #    trace_id / 时间戳 / 随机数 / 会话历史，否则上游前缀缓存命中率归零。
        {"role": "system", "content": system_text},
        # 变化后缀：few-shot → 归一化问题 → 约束（§10.3 的前缀缓存布局）
        {"role": "user", "content": user_text},
    ]

    # ★ 实测约束（2026-09-17）：`response_format={"type":"json_object"}` 要求
    #   **消息里出现 "json" 字样**，否则上游返回 400
    #   `Prompt must contain the word 'json' in some form ...`。
    #   在**构造期**断言，而不是等一次 400 浪费一个往返（并且 400 会记进上游错误率）。
    if json_output and "json" not in (system_text + user_text).lower():
        raise LlmEgressViolation(
            "json_output=True 但消息里没有 'json' 字样 —— 上游会直接 400（实测）",
            detail={"hint": "prompt 资产的 system/user 模板必须显式出现 JSON"},
        )

    # ④ `deny_columns` 列名绝不出现（§10.5 ④）。摘要由调用方经语义层取，
    #    这里做**独立复核**：语义层过滤失效时，网关是最后一道。
    if deny_columns:
        hay = f"{payload.semantic_summary}\n{system_text}\n{user_text}"
        hit = [c for c in deny_columns if c and c in hay]
        if hit:
            raise LlmEgressViolation(
                "语义包摘要/前缀中出现了 `deny_columns` 列名（§10.5 ④）",
                detail={"deny_columns_hit": hit},
            )

    wire: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format": {"type": "json_object"} if json_output else {"type": "text"},
    }
    # ★ 实测（2026-09-17）：两模型**默认开思考**；关闭的**唯一**有效写法是
    #   `{"type": "disabled"}`。`thinking: false` → 400；`enable_thinking: false`
    #   与 `chat_template_kwargs` → **被静默忽略**（仍产 reasoning_tokens）。
    wire["thinking"] = {"type": "enabled"} if thinking else {"type": "disabled"}

    # 🔴 N-12 与 §10.3 规则 2 的字面冲突在此处收口：出站的是**哈希**，且只走 API 的
    #    `user` 参数（OpenAI 兼容字段），**不进 messages**。
    if payload.user_scope:
        wire["user"] = payload.user_scope

    # 最后一道：出站前再扫一次键名。前两道之后这里的键必然全合法 ——
    # 保留它是因为"必然"这个判断本身会随代码演进失效，而扫描的成本接近零。
    assert_no_forbidden_keys(wire)
    return wire


def wire_keys_of(wire: Mapping[str, Any]) -> frozenset[str]:
    """辅助：暴露顶层键集，供测试断言"只出现已登记键"。"""
    return frozenset(wire.keys())
