"""版本化 prompt 资产与加载器（N-19 / 07 §10.3）。

归属窗口：W3A｜职责：`llm/prompts/loader.py` = "YAML→…" 式的最小加载器，
**不解析、只替换**：把 `.txt` 模板里 `$name` 占位符用已登记变量替换成最终文本。

## 为什么用标准库 `string.Template` 而不是 `str.format` 或 jinja2（Q5 裁定）

- **不用 jinja2**：依赖白名单里没有它（实测 `importlib.metadata.version("jinja2")` →
  `PackageNotFoundError`）。要加须走 ADR-20，归 W0，**W3A 不得自己加**。
- **不用 `str.format`**：本项目 prompt 里**必然**大量出现 `{` `}` ——
  输出 JSON Schema（`{"type":"object",...}`）、SQL 片段、few-shot 里的 JSON 样例。
  `str.format` 会把它们当占位符，**一用就炸**，且要靠 `{{` 转义污染整份资产。
- **用 `string.Template`（`$name`）**：`$` 在 SQL / JSON 里是**稀有字符**（唯一要躲的是
  `$schema` 这类 JSON Schema 关键字，本目录的资产刻意不写它，加载器也会校验）。

## 前缀缓存的四条硬规则怎么被**机器化**（07 §10.3）

| # | 规则 | 本模块的强制方式 |
|---|---|---|
| 1 | 稳定内容必须前置 | 资产文件被 `=== SYSTEM ===` / `=== USER ===` 分成两段；`system` 段渲染出的就是前缀 |
| 2 | 前缀里禁请求级变量（`user_id` 之外） | `STABLE_PREFIX_VARS` 白名单 + **加载期**校验：SYSTEM 段出现白名单外的变量 → 加载失败 |
| 3 | 前缀里禁会话历史 | `history_block` **不在** `STABLE_PREFIX_VARS` 里 → 规则 2 自动覆盖它 |
| 4 | 命中率必须埋点 | 不在本模块：实测上游 `usage.prompt_cache_hit_tokens` 直供（见 `client.py` 与 `budget.py`） |

规则 2 的实现细节值得点出：校验发生在**加载期**而不是渲染期，因为"某天有人在 system 段
顺手加了个 `$trace_id`"是一类**只让缓存命中率掉、不产生任何错误**的变更 ——
命中率是滞后指标，等它掉下来（成本已经涨了）才发现的代价太大。
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from string import Template
from typing import Any, Final

from app.llm.egress_guard import EgressPayload
from app.llm.errors import LlmPromptError

__all__ = [
    "PromptAsset",
    "load_prompt",
    "available_versions",
    "render_messages",
    "STABLE_PREFIX_VARS",
    "FORBIDDEN_PREFIX_VARS",
    "SYSTEM_MARKER",
    "USER_MARKER",
    "PROMPTS_DIR",
]

PROMPTS_DIR: Final[Path] = Path(__file__).resolve().parent

SYSTEM_MARKER: Final[str] = "=== SYSTEM ==="
USER_MARKER: Final[str] = "=== USER ==="

#: 允许出现在**稳定前缀**里的变量（07 §10.3 规则 2 的白名单）。
#: 全是"随 `bundle_version` / `prompt_version` 变化"的量，**没有任何请求级变量**。
STABLE_PREFIX_VARS: Final[frozenset[str]] = frozenset(
    {
        "semantic_summary",   # 语义包摘要（表/列注释、指标定义、同义词）
        "bundle_version",     # 语义包版本 —— 它变了前缀就该变（这是**特性**不是缺陷）
        "dialect_note",       # 方言说明
        "output_schema",      # 输出 JSON Schema
        "task_name",          # task 标识（常量，随 prompt 版本冻结）
    }
)

#: 明确**禁止**出现在前缀的变量 —— 单独列出来只为让报错信息可读
#: （它们全部已在 `STABLE_PREFIX_VARS` 之外，属于"规则 1+3 的显式表达"）。
FORBIDDEN_PREFIX_VARS: Final[frozenset[str]] = frozenset(
    {
        "question", "raw_question", "normalized_question", "few_shots", "constraints",
        "history_block", "history_questions", "error_digest", "trace_id", "task_id",
        "session_id", "tenant_id", "user_id", "user_scope", "now", "timestamp", "request_id",
    }
)

_SECTION_RE: Final[re.Pattern[str]] = re.compile(
    rf"^{re.escape(SYSTEM_MARKER)}\s*$|{re.escape(USER_MARKER)}\s*$", re.MULTILINE
)

#: `$name` / `${name}` —— 同时用于提取变量与校验"孤独的 `$`"。
_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")

#: 文件名规范：`{task}_v{n}.txt`（07 §10.3）。
_ASSET_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<task>[a-z0-9_]+)_v(?P<num>\d+)\.txt$")


@dataclass(frozen=True, slots=True)
class PromptAsset:
    """一份已解析的 prompt 资产。**不可变** —— 它是版本化产物，不是运行时状态。"""

    task: str
    #: 版本标识，**就是文件词干**（`normalize_v1`）—— 直接进 `LLMResponse.prompt_version`（N-19）。
    version: str
    system_template: Template
    user_template: Template
    #: SYSTEM 段实际用到的变量（加载期已校验 ⊆ `STABLE_PREFIX_VARS`）。
    prefix_vars: frozenset[str]
    #: 原始文件内容的 sha256（前 16 位）—— 07 §10.3："版本号与文件内容哈希一并记录"。
    #: 它在**前缀缓存失效定位**时的作用：版本号没变但哈希变了 ⇒ 有人改了文件没升版本号。
    content_hash: str
    path: str


def _split_sections(raw: str, *, where: str) -> tuple[str, str]:
    """按标记切成 system / user 两段。缺段或顺序错 → `LlmPromptError`（fail-fast）。"""
    parts = _SECTION_RE.split(raw)
    markers = _SECTION_RE.findall(raw)
    if markers[:2] != [SYSTEM_MARKER, USER_MARKER] or len(parts) < 3:
        raise LlmPromptError(
            "prompt 资产必须依次包含 `=== SYSTEM ===` 与 `=== USER ===` 两段",
            detail={"asset": where},
        )
    return parts[1], parts[2]


def _extract_vars(text: str, *, where: str) -> frozenset[str]:
    """提取 `$name` 占位符，并拦下"孤独的 `$`"（Template 会当成不完整占位符炸）。"""
    for m in re.finditer(r"\$(?![A-Za-z_{$])", text):
        raise LlmPromptError(
            "prompt 资产里出现了裸 `$`（会被 string.Template 当成不完整占位符）",
            detail={"asset": where, "position": m.start()},
        )
    return frozenset(_PLACEHOLDER_RE.findall(text))


def available_versions(task: str) -> list[int]:
    """该 task 在磁盘上存在的版本号（升序）。没有 → 空列表（**不抛错**，交由调用方决策）。"""
    nums: list[int] = []
    for p in PROMPTS_DIR.glob(f"{task}_v*.txt"):
        m = _ASSET_NAME_RE.match(p.name)
        if m and m.group("task") == task:
            nums.append(int(m.group("num")))
    return sorted(nums)


@cache
def load_prompt(task: str, version: int | None = None) -> PromptAsset:
    """加载并**校验**一份资产。`version=None` → 取该 task 的**最高**版本号。

    校验项（任一失败 → `LlmPromptError`，不给"半可用的资产"）：

    1. 文件名合规范、文件存在；
    2. 两段标记齐备；
    3. SYSTEM 段变量 ⊆ `STABLE_PREFIX_VARS`（07 §10.3 规则 1/2/3）；
    4. 两个模板都没有裸 `$`。

    ⚠️ `@cache` 是有意的：资产在进程生命周期内**不该**变化（它由发版控制），
    缓存它同时让"同一进程内前缀稳定"这件事成为**结构保证**而不是纪律要求。
    测试要换版本时用 `load_prompt.cache_clear()`（`functools.cache` 自带）。
    """
    if version is None:
        nums = available_versions(task)
        if not nums:
            raise LlmPromptError(
                "找不到该 task 的 prompt 资产（07 §10.3 的 `{name}_v{n}.txt`）",
                detail={"task": task, "dir": str(PROMPTS_DIR)},
            )
        version = nums[-1]

    path = PROMPTS_DIR / f"{task}_v{version}.txt"
    if not path.is_file():
        raise LlmPromptError(
            "指定的 prompt 版本不存在", detail={"task": task, "version": version}
        )

    raw = path.read_text(encoding="utf-8")
    sys_raw, user_raw = _split_sections(raw, where=path.name)

    prefix_vars = _extract_vars(sys_raw, where=f"{path.name}::SYSTEM")
    illegal = sorted(prefix_vars - STABLE_PREFIX_VARS)
    if illegal:
        raise LlmPromptError(
            "SYSTEM（稳定前缀）段出现了非稳定变量 —— 07 §10.3 规则 1/2/3 被破坏，"
            "前缀缓存命中率会归零",
            detail={
                "asset": path.name,
                "illegal_vars": illegal,
                "forbidden_hint": sorted(set(illegal) & FORBIDDEN_PREFIX_VARS),
                "allowed": sorted(STABLE_PREFIX_VARS),
            },
        )
    _extract_vars(user_raw, where=f"{path.name}::USER")

    return PromptAsset(
        task=task,
        version=f"{task}_v{version}",
        system_template=Template(sys_raw),
        user_template=Template(user_raw),
        prefix_vars=prefix_vars,
        content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16],
        path=str(path),
    )


def _render_block_few_shots(few_shots: tuple[tuple[str, str], ...]) -> str:
    """few-shot 渲染成**变化后缀**里的一段（§10.3 布局）。SQL 侧由内容流水线脱敏。"""
    if not few_shots:
        return "（无示例）"
    lines = []
    for idx, (question, sql) in enumerate(few_shots, start=1):
        lines.append(f"[示例 {idx}]\n问：{question}\nSQL：{sql}")
    return "\n\n".join(lines)


def _render_block_history(history: tuple[str, ...]) -> str:
    """多轮上下文 —— **只放问题**，不含 SQL 与结果（§10.5 ⑥），且只进后缀（规则 3）。"""
    if not history:
        return "（无历史轮次）"
    return "\n".join(f"- {q}" for q in history[-5:])


def _render_block_candidates(candidates: tuple[str, ...]) -> str:
    """候选资产名（表/列/指标/别名的**名字**，§10.5 ① 的"同义词"子集）。只进后缀。"""
    if not candidates:
        return "（无候选）"
    return "\n".join(f"{idx}. {name}" for idx, name in enumerate(candidates, start=1))


def _render_template(tmpl: Template, values: Mapping[str, Any], *, where: str) -> str:
    try:
        return tmpl.substitute(dict(values))
    except KeyError as exc:
        raise LlmPromptError(
            "prompt 模板需要的变量未被提供（调用方与资产版本不匹配）",
            detail={"asset": where, "missing_var": str(exc).strip("'")},
        ) from None
    except ValueError as exc:  # 裸 `$` 等（加载期已拦，此处兜底）
        raise LlmPromptError(
            "prompt 模板替换失败", detail={"asset": where, "reason": type(exc).__name__}
        ) from None


def render_messages(asset: PromptAsset, payload: EgressPayload) -> tuple[list[dict[str, str]], str]:
    """渲染成 OpenAI 兼容的 `messages`，并返回 `prompt_version`（N-19 必录字段）。

    返回的第一个元素**就是**要出站的东西 —— 中间不再经过任何拼接，
    因此"出站内容 = 已登记字段的渲染结果"是**可验证**的（见 `egress_guard`）。
    """
    sys_values = {
        "semantic_summary": payload.semantic_summary or "（语义包摘要未提供）",
        "bundle_version": payload.bundle_version or "(unset)",
        "dialect_note": payload.dialect_note or "目标方言：PostgreSQL 16 + pgvector。",
        "output_schema": payload.output_schema or "（未提供输出 Schema；仍必须输出 JSON 对象）",
        "task_name": asset.task,
    }
    user_values = {
        "question": payload.raw_question,
        "normalized_question": payload.raw_question,
        "raw_question": payload.raw_question,
        "few_shots": _render_block_few_shots(payload.few_shots),
        "constraints": payload.constraints or "（无附加约束）",
        "history_block": _render_block_history(payload.history_questions),
        "candidates_block": _render_block_candidates(payload.candidates),
        "error_digest": payload.error_digest or "（无错误摘要）",
    }

    system_text = _render_template(asset.system_template, sys_values, where=f"{asset.version}::SYSTEM")
    user_text = _render_template(asset.user_template, user_values, where=f"{asset.version}::USER")

    return (
        [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        asset.version,
    )


def prefix_hash(asset: PromptAsset, payload: EgressPayload) -> str:
    """前缀文本的哈希 —— **前缀缓存稳定性的观测手段**。

    `tests/unit/test_llm_prompts.py` 用它做核心断言：
    "同一 payload（除问题/后缀外全部相同）两次渲染 → 前缀哈希必须相同"。
    这比"读代码觉得没问题"强，因为它会随资产改动自动失效。
    """
    messages, _ = render_messages(asset, payload)
    return hashlib.sha256(messages[0]["content"].encode("utf-8")).hexdigest()[:16]
