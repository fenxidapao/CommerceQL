"""L4 打分器的**分数值对象**与解析（N-27 检查方式①、PRD §12.9）。

归属窗口：W3C｜依据：07 §6.8.2（含 5 条硬约束）、PRD §12.9 方案 C。

🔴 **为什么必须是 `RerankScore` 而不是裸 `float`**
    PRD §12.9 已把红线从"产品类别"改写成**三项可验证属性**（联合打分 / 归一化 / 可校准）；
    "叫不叫 reranker"是形式要求，**实质要禁的是双塔余弦** —— 它衡量"名字像不像"，
    而不是"这个字段是不是用户要的那个"。类型系统能钉住的只有一件事：
    **分数必须携带着它出自哪个打分器**。于是 `(model_id, prompt_version)` 成为
    `RerankScore` 的**必填字段** —— 裸 float 无法伪装成它，而"分数跨打分器不可比 /
    换打分器后 τ 必须重新校准"这两条纪律也就有了物理载体，而不只是评审时的一句提醒。

四个刻意的设计选择（每一条都对应一条上游硬约束）：
  1. **越界即失败，不是截断**（PRD §12.9 约束①）：落在 `[0,1]` 外的分数说明打分器没按契约
     输出，截断会让它"看起来正常"，而它其实已经不可信了。
  2. **不给默认值**：`model_id` / `prompt_version` 无默认 → 构造分数就必须显式声明打分器身份。
  3. **解析失败返回 `ScoreOutcome(failed=True)`，不抛异常**：解析失败的**正确响应**是
     fail-safe 判 `ambiguous`（N-27 约束④），那是**产品结论**；抛异常会把"一次偏安全的澄清"
     变成"一次 500"，方向刚好相反。
  4. **`adopt_l4_candidates` 是唯一的适配缝**：端口签名 `resolve(concept, ctx, candidates)`
     装不下打分类对象（`CandidateRef` 只有 `asset_id/score/layer`），所以在"裸 float 候选"
     与"类型化分数"之间**只留一个**被单测钉死的转换点，而不是让各处自行转换。
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.binding.errors import BindingScoreMisuse
from app.core.contracts import CandidateRef
from app.core.enums import BindingLayer

__all__ = [
    "L4_SCORE_ITEM_KEYS",
    "RerankScore",
    "ScoreOutcome",
    "ScoreParseError",
    "adopt_l4_candidates",
    "parse_scores_json",
    "require_rerank_scores",
]


class ScoreParseError(ValueError):
    """`RerankScore` 构造期的契约违背（越界 / 非法 / 缺打分器标识）。

    ⚠️ 这是**内部**信号：`parse_scores_json` 会把它转换成 `ScoreOutcome(failed=True)`，
    不让它穿出本模块 —— 因为对上层而言"这次打分不可用"是数据问题，不是异常。
    """


@dataclass(frozen=True, slots=True)
class RerankScore:
    """L4 精排分数 —— **类型化**，携带打分器身份（N-27 检查方式①）。

    | 字段 | 为什么必须有 |
    |---|---|
    | `candidate_id` | 分差判定要能对上候选；`Δscore` 只在同一候选集合内可比 |
    | `value` | 归一化到 `[0,1]`（PRD §12.9 属性②：有界、可比较） |
    | `model_id` | τ 绑定三元组之一（PRD §6.3.1"不得跨打分器复用"） |
    | `prompt_version` | **仅改 prompt 亦须重新校准 τ** —— 分数量纲随 prompt 漂移 |
    """

    candidate_id: str
    value: float
    model_id: str
    prompt_version: str

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ScoreParseError("RerankScore.candidate_id 不得为空")
        if not self.model_id or not self.prompt_version:
            raise ScoreParseError(
                "RerankScore 必须携带 (model_id, prompt_version) —— "
                "缺了它 τ 就无法绑定打分器（N-27 约束②），分数也就不可比"
            )
        value = self.value
        # bool 是 int 的子类：`True` 混进来当 1.0 是典型的"看起来对"
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ScoreParseError(f"RerankScore.value 必须是数值，收到 {type(value).__name__}")
        as_float = float(value)
        if not math.isfinite(as_float):
            raise ScoreParseError(f"RerankScore.value 必须是有限数，收到 {as_float!r}")
        if not (0.0 <= as_float <= 1.0):
            # ⚠️ 越界 = **解析失败**，不得截断（PRD §12.9 约束①）
            raise ScoreParseError(
                f"RerankScore.value 越出 [0,1]：{as_float!r} —— 按 PRD §12.9 约束① "
                "视为**解析失败**（不是截断）：打分器没按契约输出，分数已不可信"
            )


@dataclass(frozen=True, slots=True)
class ScoreOutcome:
    """一次 L4 打分的**结果对象**（含失败态）。

    `failed=True` 是**正常返回值**：它的下游动作是 N-27 约束④ 的 fail-safe（判 `ambiguous`），
    所以它必须能被传递，而不是以异常形式中断链路。
    """

    scores: tuple[RerankScore, ...] = ()
    failed: bool = False
    reason: str | None = None

    @property
    def ok(self) -> bool:
        """是否拿到**可用于分差判定**的分数（失败态恒为 `False`）。"""
        return not self.failed


def _fail(reason: str) -> ScoreOutcome:
    return ScoreOutcome(scores=(), failed=True, reason=reason)


def _is_candidate_ref(value: object) -> bool:
    """运行时类型守卫。

    ⚠️ 写成**辅助函数**而不是内联 `isinstance` 是有意的：内联会让 mypy 依据形参类型把
    "它不是 `CandidateRef`" 这个分支判成 unreachable（`warn_unreachable = true`），
    从而**删掉真正要保留的防线**。这里的检查是给运行时用的（夹具、装配处乱传），
    不是给类型系统看的。
    """
    return isinstance(value, CandidateRef)


def require_rerank_scores(values: Sequence[object]) -> tuple[RerankScore, ...]:
    """四层判定的**运行时类型闸门**（N-27 检查方式①）。

    ⚠️ 为什么不能只靠类型标注：mypy 只在静态分析时生效，而"夹具/装配处塞了个 float 进来"
    是**运行时**发生的事。这里的 `isinstance` 硬校验是把"禁余弦"从纪律变成断路器的唯一手段。
    """
    checked: list[RerankScore] = []
    for item in values:
        if not isinstance(item, RerankScore):
            raise BindingScoreMisuse(
                "L4 只接受 RerankScore，不接受裸 float 或其它类型 —— "
                f"收到 {type(item).__name__}（N-27 检查方式①：类型错误优于评审遗漏）"
            )
        checked.append(item)
    return tuple(checked)


def adopt_l4_candidates(
    candidates: Sequence[CandidateRef],
    *,
    model_id: str,
    prompt_version: str,
) -> ScoreOutcome:
    """把**已声明为 L4 产出**的候选转成类型化分数 —— **唯一**适配缝。

    这是端口签名（`resolve(concept, ctx, candidates)`）与类型化分数之间的桥。它必须窄，
    因为它是"裸 float 混进 L4 判定"的唯一可能入口。三条准入条件：

    1. 候选必须**显式声明** `layer is BindingLayer.L4` ——
       检索侧（W2B）的相似度分、dense 分**都没有这个标记**，因此不可能被误当精排分；
    2. 分数必须落在 `[0,1]`，否则按"解析失败"处理（不截断）；
    3. 候选集合非空。

    任何一条不满足 → `ScoreOutcome(failed=True)` → 下游 fail-safe 判 `ambiguous`。
    这不是"宽容"，是 N-27 约束④ 要求的**偏安全**。
    """
    if not candidates:
        return _fail("no_candidates")
    scores: list[RerankScore] = []
    for ref in candidates:
        if not _is_candidate_ref(ref):
            return _fail(f"not_a_candidate_ref:{type(ref).__name__}")
        if ref.layer is not BindingLayer.L4:
            # 最容易被误用的形态：检索分被当成精排分（这正是"禁双塔余弦"要防的那件事）
            return _fail(f"candidate_not_l4:{ref.asset_id}")
        try:
            scores.append(
                RerankScore(
                    candidate_id=ref.asset_id,
                    value=ref.score,
                    model_id=model_id,
                    prompt_version=prompt_version,
                )
            )
        except ScoreParseError as exc:
            return _fail(f"score_invalid:{ref.asset_id}:{exc}")
    return ScoreOutcome(scores=tuple(scores))


#: L4 打分器的**输出契约**（写进 prompt 的 `output_schema`，与解析器单点对应）。
#: 允许且仅允许：`candidate_id` / `score` / 可选 `reason`（PRD §12.9 方案 C 的"可解释"）。
#:
#: ⚠️ **公开**（非 `_` 前缀）是因为 `l4.py` 要用它**派生**出站 `output_schema` 文本 ——
#: 若在 prompt 里手写一份键名清单，改契约时必然有一处漏改，而失败方式正是本项目最怕的
#: "静默不生效"（模型按旧键名输出 → 解析器判 `item_keys_invalid` → 全部落 `ambiguous`）。
L4_SCORE_ITEM_KEYS: Final[frozenset[str]] = frozenset({"candidate_id", "score", "reason"})


def parse_scores_json(
    text: str,
    *,
    expected_ids: Sequence[str],
    model_id: str,
    prompt_version: str,
) -> ScoreOutcome:
    """解析 L4 打分器返回的 JSON 文本（`{"scores": [{"candidate_id":…, "score":…}]}`）。

    🔴 **严格**：任何一处不符即整体判为解析失败，**不做部分采纳**。理由 —— 分差判定吃的是
    「最高分 − 次高分」，缺一个候选的分就可能把"两个候选几乎并列"误读成"一个明显占优"，
    而后者会直接产出 `resolved_unique`。宁可澄清，不可猜（N-27 约束④）。

    判失败的七种情形：非字符串/空串、非合法 JSON、顶层不是对象、缺 `scores`、
    `scores` 不是列表、条目缺字段/含未知键/重复 id、id 集合与期望不符、分数越界或非数值。
    """

    def sniff(payload: Any) -> ScoreOutcome:
        if not isinstance(payload, Mapping):
            return _fail("top_level_not_object")
        if "scores" not in payload:
            return _fail("missing_scores_key")
        raw_items = payload["scores"]
        if not isinstance(raw_items, list):
            return _fail("scores_not_list")

        expected = list(dict.fromkeys(expected_ids))
        seen: dict[str, RerankScore] = {}
        for item in raw_items:
            if not isinstance(item, Mapping):
                return _fail("item_not_object")
            keys = set(item.keys())
            if not keys <= L4_SCORE_ITEM_KEYS or "candidate_id" not in keys or "score" not in keys:
                return _fail(f"item_keys_invalid:{sorted(keys)}")
            candidate_id = item["candidate_id"]
            if not isinstance(candidate_id, str) or not candidate_id:
                return _fail("candidate_id_invalid")
            if candidate_id in seen:
                return _fail(f"duplicate_candidate:{candidate_id}")
            if candidate_id not in expected:
                return _fail(f"unknown_candidate:{candidate_id}")
            try:
                seen[candidate_id] = RerankScore(
                    candidate_id=candidate_id,
                    value=item["score"],
                    model_id=model_id,
                    prompt_version=prompt_version,
                )
            except ScoreParseError as exc:
                return _fail(f"score_invalid:{candidate_id}:{exc}")

        missing = [cid for cid in expected if cid not in seen]
        if missing:
            return _fail(f"missing_candidates:{sorted(missing)}")
        # 保持**期望顺序**，让分差判定与调用方看到的候选顺序一致（可复现）
        return ScoreOutcome(scores=tuple(seen[cid] for cid in expected))

    if not text or not text.strip():
        return _fail("empty_text")
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        return _fail(f"invalid_json:{exc}")
    return sniff(payload)
