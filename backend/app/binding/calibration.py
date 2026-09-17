"""τ / ε 校准脚手架 —— 把附录 C §C.4.6 的六步流程做成**可复算的纯函数**。

归属窗口：W3C｜依据：附录 C §C.4.6（六步 + 5 条硬约束）、PRD §12.9 约束③（E-5）、NFR-7.1（澄清率 ≤15%）。

## 本模块**不做**什么（很重要，别指望它做）

| 不做 | 为什么 |
|---|---|
| 不联网、不连库、不打分 | 本模块只**消费**已打好的分。打分靠 `l4.score_l4`（在线）或评测夹具（离线） |
| 不读文件、不写报告 | 报告落盘 / 进评测报告是 W6（`eval/**` 执行器）的活；本模块只产出**结构化报告对象** |
| 不自己实现区间判据 | 复用 `four_layer.classify_gap` —— 否则校准描述的是**可能已漂移的**规则（最难发现的一类问题） |
| 不替调用方定"绑定准确率目标" | §C.4.6 步骤 3 只说"满足绑定准确率目标"，**没给数值** → `accuracy_target` 是**必填参数**，不给默认值（编一个数字 = 逼人相信它） |
| 不自动改 τ 的值 | 本模块只**建议**一个点。改配置是人/CI 的动作，且必须附本报告（N-25：τ 每次变更须附校准报告） |

## 与 N-25 的关系（为什么这里没有"自动调到指标好看"的开关）

§C.4.6 步骤 4 明写：候选点不满足 `澄清率 ≤ 15%` 时，动作是**回看语义包**（补别名 → L1 /
定 `default_binding` → L3），**不是换 τ**。故本模块**只报告** `nfr71_satisfied` 与
`suggested_semantic_actions`，**不**在扫描里偷偷换一个"澄清率更低"的 τ 出来 ——
那种开关的存在本身就是风险 R-19 的成因（"调参刷分无法被发现"）。

## 关于"重复打分取平均"（§C.4.6 约束 5 明令禁止）

扫描用**第 1 次重复**的分数，不取平均。理由不只是"省事"：约束 5 的原话是
"**不得用'多打几次取平均'绕过**（那只是把方差藏起来，不是消除它）"。
稳定性门槛已经保证重复之间一致，因此取任意一次都是等价的 —— 取第 1 次只为了**可复现**。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.binding.four_layer import TauConfig, classify_gap
from app.core.enums import BindingState

__all__ = [
    "CLARIFY_RATE_LIMIT",
    "MIN_REPEATS",
    "TAU_SWEEP_STEP",
    "CalibrationReport",
    "ScoreSample",
    "SampleStability",
    "StabilityReport",
    "StabilityVerdict",
    "TauPoint",
    "assess_stability",
    "calibrate",
    "kendall_tau_b",
    "sweep",
]

#: τ 扫描步长（§C.4.6 步骤 1 原文："令 τ 从 0 扫到 1（步长 0.05）"）。
#: ⚠️ 它**同时**是约束 5 里的"τ 的分辨率"—— 一个常量两处用，避免两个 0.05 各自漂移。
TAU_SWEEP_STEP: Final[float] = 0.05

#: 稳定性检查要求的**最少重复次数**（§C.4.6 约束 5 / E-5：`n ≥ 3`）。
MIN_REPEATS: Final[int] = 3

#: NFR-7.1 / 门禁 G-8：`outcome=clarify` 占比上限。
#: ⚠️ 这是**需求常量**，不是可调参数 —— 本模块只用它做"是否达标"的判定，绝不用它反推 τ。
CLARIFY_RATE_LIMIT: Final[float] = 0.15


# ============================================================================
# 输入：一批已打好的分
# ============================================================================


@dataclass(frozen=True, slots=True)
class ScoreSample:
    """一条校准样本：候选 + **重复打分** + 金标准。

    | 字段 | 说明 |
    |---|---|
    | `candidate_ids` | 候选标识，长度 ≥ 2（单候选不构成分差问题） |
    | `repeats` | 每次重复的分数向量，**与 `candidate_ids` 等长**；次数须 ≥ `MIN_REPEATS` |
    | `gold_candidate_id` | 正确答案的候选；**`None` = 本条本该澄清**（无唯一正确答案） |

    `gold_candidate_id is None` 就是 §C.4.6 步骤 2 说的"**该澄清未澄清率**"的**安全侧**样本：
    把不该唯一的问题判成唯一，是本系统最不希望发生的一类错误。
    """

    sample_id: str
    candidate_ids: tuple[str, ...]
    repeats: tuple[tuple[float, ...], ...]
    gold_candidate_id: str | None = None

    def __post_init__(self) -> None:
        if len(self.candidate_ids) < 2:
            raise ValueError(
                f"样本 {self.sample_id!r} 的候选少于 2 个 —— 分差判定无从谈起"
                "（单候选的形态归 four_layer 的读法 4 处理，不是校准的输入）"
            )
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError(f"样本 {self.sample_id!r} 的候选有重复 id")
        if len(self.repeats) < MIN_REPEATS:
            raise ValueError(
                f"样本 {self.sample_id!r} 只有 {len(self.repeats)} 次重复 —— "
                f"§C.4.6 约束 5 要求 n ≥ {MIN_REPEATS} 才允许定稿 τ"
            )
        for idx, row in enumerate(self.repeats):
            if len(row) != len(self.candidate_ids):
                raise ValueError(
                    f"样本 {self.sample_id!r} 第 {idx + 1} 次重复的分数个数"
                    f"({len(row)}) 与候选数({len(self.candidate_ids)}) 不一致"
                )
            for value in row:
                if not math.isfinite(value) or not (0.0 <= value <= 1.0):
                    raise ValueError(
                        f"样本 {self.sample_id!r} 第 {idx + 1} 次重复含非法分数 {value!r}："
                        "必须在 [0,1] 且有限（PRD §12.9 约束①的归一化要求；越界 = 解析失败，不截断）"
                    )
        if self.gold_candidate_id is not None and self.gold_candidate_id not in self.candidate_ids:
            raise ValueError(
                f"样本 {self.sample_id!r} 的金标准 {self.gold_candidate_id!r} 不在候选里 —— "
                "夹具错了，不是模型错了"
            )

    @property
    def gold_should_clarify(self) -> bool:
        """金标准是否表示"本条本该澄清"。"""
        return self.gold_candidate_id is None

    def ranking(self, repeat_index: int) -> tuple[str, ...]:
        """某次重复的**排名**（分数降序；同分按 `candidate_ids` 原序稳定排序）。"""
        row = self.repeats[repeat_index]
        order = sorted(range(len(row)), key=lambda i: (-row[i], i))
        return tuple(self.candidate_ids[i] for i in order)

    def gap(self, repeat_index: int) -> float:
        """某次重复的分差 `最高 − 次高`（同分则 `0.0`）。"""
        row = self.repeats[repeat_index]
        top = sorted(row, reverse=True)
        return top[0] - top[1]


# ============================================================================
# 排名一致性：Kendall τ-b（自己实现 —— 不新增依赖，ADR-20）
# ============================================================================


def kendall_tau_b(a: Sequence[float], b: Sequence[float]) -> float:
    """Kendall τ-b 相关系数（**处理并列**，故用 b 变体而非 a）。

    §C.4.6 约束 5 要求报告"排名一致性（如 Kendall τ）"。本项目不引 `scipy`（ADR-20 的依赖纪律），
    故自实现 —— 公式是闭式的，没有数值稳定性陷阱：

    `τ_b = (C − D) / sqrt((n₀ − n₁)(n₀ − n₂))`，其中 `n₀ = n(n−1)/2`，
    `n₁` / `n₂` 分别是两侧的并列修正（`Σ t(t−1)/2`）。

    ⚠️ 分母为 0（某一侧**全体并列**）时返回 `1.0`：全员并列意味着两边都没给出任何排序信息，
    说"不一致"是错的。此时分差恒为 0，稳定性门槛本来就会以另一种方式看到问题。
    """
    if len(a) != len(b):
        raise ValueError(f"两个分数向量长度必须一致：{len(a)} != {len(b)}")
    n = len(a)
    if n < 2:
        return 1.0

    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            lhs = (a[i] - a[j]) * (b[i] - b[j])
            if lhs > 0:
                concordant += 1
            elif lhs < 0:
                discordant += 1

    def tie_correction(values: Sequence[float]) -> int:
        counts: dict[float, int] = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        return sum(count * (count - 1) // 2 for count in counts.values())

    n0 = n * (n - 1) // 2
    denominator = math.sqrt((n0 - tie_correction(a)) * (n0 - tie_correction(b)))
    if denominator == 0:
        return 1.0
    return (concordant - discordant) / denominator


# ============================================================================
# 约束 5：打分器稳定性门槛（**必须先过**，否则禁止定稿）
# ============================================================================


class StabilityVerdict(StrEnum):
    """稳定性结论（§C.4.6 约束 5）。"""

    STABLE = "stable"
    #: 分差方差与 τ 分辨率同量级 → **校准不可信 → 禁止定稿** → 按 PRD §12.9 升级方案 A。
    UNSTABLE = "unstable"


@dataclass(frozen=True, slots=True)
class SampleStability:
    """单条样本的稳定性明细（报告里逐条给出，不只看汇总 —— 否则一条噪声样本会被平均掉）。"""

    sample_id: str
    gaps: tuple[float, ...]
    gap_std: float
    #: 每次重复相对**第 1 次**的 Kendall τ-b（第 1 项恒为 1.0）。
    kendalls: tuple[float, ...]

    @property
    def min_kendall(self) -> float:
        return min(self.kendalls)

    @property
    def is_stable(self) -> bool:
        """单条是否通过：判据**只有分差 std**（见 `assess_stability` 的说明）。"""
        return self.gap_std < TAU_SWEEP_STEP


@dataclass(frozen=True, slots=True)
class StabilityReport:
    """稳定性检查汇总（§C.4.6 约束 5 / E-5）。"""

    samples: tuple[SampleStability, ...]
    verdict: StabilityVerdict
    #: 最大的**样本内**分差 std（判据用 max 而非 mean —— 见 `assess_stability`）。
    max_gap_std: float
    #: 全体重复里最低的 Kendall τ-b（**只报告，不参与判据**）。
    min_kendall: float
    repeats: int

    @property
    def is_calibratable(self) -> bool:
        return self.verdict is StabilityVerdict.STABLE


def _sample_stdev(values: Sequence[float]) -> float:
    """样本标准差（分母 `n−1`）。

    ⚠️ 用样本口径而非总体口径：重复次数 `n` 是**抽样**（3~5 次），不是全部可能取值；
    用总体口径会把方差系统性低估 —— 而这里判的正是"方差够不够小"，低估方向恰好是危险侧。
    """
    n = len(values)
    if n < 2:
        return 0.0
    mean = math.fsum(values) / n
    variance = math.fsum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(variance)


def assess_stability(samples: Sequence[ScoreSample]) -> StabilityReport:
    """约束 5 的机器判定：`n ≥ 3` 重复打分 → 排名一致性 + 分差 std → STABLE / UNSTABLE。

    **判据（严格按 §C.4.6 约束 5 原文）**：`分差方差与 τ 的分辨率（扫描步长 0.05）同量级`
    → 不可信。落地为 `max(gap_std) >= TAU_SWEEP_STEP` 即 **UNSTABLE**。

    三处刻意的选择，逐条给理由：

    1. **用 max 而不是 mean** —— 判据问的是"校准结果能不能信"，一条极噪声样本就足以让某个样本的
       结论不可复现；取 mean 会把它平均掉。偏保守，与"失败侧偏安全"同向。
    2. **只看分差 std，不用 Kendall τ 判定** —— 约束 5 原文把 Kendall 列在"**报告**"侧，
       把方差列在"**判据**"侧（"若分差方差与 τ 的分辨率同量级 → …"）。故 Kendall 只进报告。
       把它也做成门槛 = **加了一条文档没有的规则**，那和漏掉一条一样不可接受。
    3. **用样本标准差** —— 见 `_sample_stdev`：低估方差的方向恰好是危险侧。

    UNSTABLE 的后果由 `calibrate` 执行：**不给 τ 候选**，并给出升级方案 A 的动作项。
    """
    if not samples:
        raise ValueError("稳定性检查需要至少一条样本")

    details: list[SampleStability] = []
    for sample in samples:
        gaps = tuple(sample.gap(i) for i in range(len(sample.repeats)))
        first = sample.repeats[0]
        kendalls = tuple(kendall_tau_b(list(first), list(row)) for row in sample.repeats)
        details.append(
            SampleStability(
                sample_id=sample.sample_id,
                gaps=gaps,
                gap_std=_sample_stdev(gaps),
                kendalls=kendalls,
            )
        )

    max_gap_std = max(item.gap_std for item in details)
    min_kendall = min(item.min_kendall for item in details)
    verdict = (
        StabilityVerdict.STABLE
        if max_gap_std < TAU_SWEEP_STEP
        else StabilityVerdict.UNSTABLE
    )
    return StabilityReport(
        samples=tuple(details),
        verdict=verdict,
        max_gap_std=max_gap_std,
        min_kendall=min_kendall,
        repeats=min(len(sample.repeats) for sample in samples),
    )


# ============================================================================
# 步骤 1–3：扫描 τ、三列指标、选点
# ============================================================================


@dataclass(frozen=True, slots=True)
class TauPoint:
    """扫描曲线上的一点（§C.4.6 步骤 2 的三列指标）。

    ⚠️ 三个比率都是 `float | None`：**子集为空时给 `None`，不给 `0.0`**。
    `0.0` 会被读成"完全达标"，而真相是"这批样本里没有这种情形，无从判定" —— 两者必须可区分
    （本项目在零分母上的既有做法：不发明数字）。
    """

    tau: float
    #: 判为 `resolved_*` **且判对**的比例（分母 = 判为 `resolved_*` 的条数）。
    binding_accuracy: float | None
    #: 本该澄清却被判唯一的比例（分母 = 金标准为"该澄清"的条数）。**安全侧错误**。
    should_clarify_but_did_not: float | None
    #: 判为 `ambiguous` 的比例（分母 = 样本总数）。
    clarify_rate: float
    #: 判为 `resolved_*` 的条数。
    decided: int
    #: 金标准为"该澄清"的条数（**不随 τ 变**，是样本集的性质）。
    should_clarify_total: int


def sweep(
    samples: Sequence[ScoreSample],
    *,
    epsilon: float,
) -> tuple[TauPoint, ...]:
    """步骤 1–2：τ 从 0 扫到 1（步长 `TAU_SWEEP_STEP`），每个点算三列指标。

    ⚠️ **τ 从 0 起扫**是刻意的（§C.4.6 步骤 1 原文），尽管运行时 `assert_usable_tau` 会拒绝
    `τ ≤ 0`：扫描点是**诊断量**，不是待部署的配置值。曲线左端点的存在让"澄清率随 τ 上升"
    这个形状能被看见。

    ⚠️ 用**第 1 次重复**的分数（不取平均）：理由见模块 docstring —— 取平均是约束 5 明令禁止的
    "把方差藏起来"。稳定性门槛未过的样本**不该**走到这里（`calibrate` 会拦住）。

    判定走 `four_layer.classify_gap` —— 与运行时**同一套区间判据**。

    ⚠️ 不接 `accuracy_target`：**选点**是步骤 3 的事（`calibrate`），扫描只负责把曲线画出来。
    把阈值塞进扫描会让"同一条曲线"随目标值变形，报告就不再是同一份事实。
    """
    if epsilon <= 0:
        raise ValueError("epsilon 必须 > 0（ε=0 时邻域退化成单点，N-27 约束④的缓冲消失）")

    should_clarify_total = sum(1 for sample in samples if sample.gold_should_clarify)
    steps = round(1.0 / TAU_SWEEP_STEP)
    points: list[TauPoint] = []
    for index in range(steps + 1):
        tau_value = index * TAU_SWEEP_STEP
        tau = TauConfig(value=tau_value, epsilon=epsilon)
        decided = 0
        correct = 0
        clarify = 0
        leaked = 0
        for sample in samples:
            verdict = classify_gap(sample.gap(0), tau)
            if verdict.state is not BindingState.RESOLVED_UNIQUE:
                clarify += 1
                continue
            decided += 1
            if sample.gold_should_clarify:
                # 安全侧错误：本该澄清却被判唯一
                leaked += 1
            elif sample.ranking(0)[0] == sample.gold_candidate_id:
                correct += 1
        points.append(
            TauPoint(
                tau=tau_value,
                binding_accuracy=(correct / decided) if decided else None,
                should_clarify_but_did_not=(
                    leaked / should_clarify_total if should_clarify_total else None
                ),
                clarify_rate=clarify / len(samples),
                decided=decided,
                should_clarify_total=should_clarify_total,
            )
        )
    return tuple(points)


# ============================================================================
# 步骤 3–6：选点 + 与 NFR-7.1 联立 + 组装可审计报告
# ============================================================================


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    """校准报告（§C.4.6 步骤 5 要求的**可审计记录**，此处是它的结构化形式）。"""

    stability: StabilityReport
    epsilon: float
    accuracy_target: float
    points: tuple[TauPoint, ...]
    #: 定稿 τ。`None` = **没有可定稿的点**（稳定性未过，或没有点满足准确率目标）。
    selected_tau: float | None
    selected_point: TauPoint | None
    #: 定稿点是否满足 NFR-7.1（澄清率 ≤ 15%）。
    nfr71_satisfied: bool
    #: 因稳定性未过而必须升级方案 A（PRD §12.9）。
    escalation_required: bool
    #: 未定稿时的**具体**动作项（回看语义包 / 升级打分器 —— 都不是"换个 τ"）。
    blocking_actions: tuple[str, ...]
    #: `binding_layer` 分布（§C.4.6 步骤 6）。
    #:
    #: ⚠️ **必须由调用方从运行时观测带进来**（W4 的 `BindingObserver` / 审计日志）。
    #: 本模块离线且只吃分数，**无法自行得出**它 —— 留 `None` 而不是编一份。
    layer_distribution: Mapping[str, int] | None = None
    #: 打分器标识（§C.4.6 步骤 5 要求写进报告；`prompt_version` 改了就等于换打分器）。
    model_id: str = ""
    prompt_version: str = ""
    #: 校准日期（ISO8601）。空 = 未填写 —— 报告因此**不可作为定稿证据**。
    calibrated_at: str = ""
    #: 校准集 / 验收集是否分离（§C.4.6 约束 2）。`False` = 报告不可作为定稿证据。
    holdout_separated: bool = False

    @property
    def is_finalizable(self) -> bool:
        """这份报告能否作为**定稿 τ 的依据** —— 八个条件缺一不可（逐条都能追溯到原文）。

        | # | 条件 | 来源 |
        |---|---|---|
        | 1 | 稳定性门槛通过 | §C.4.6 约束 5："**禁止定稿**" |
        | 2 | 选出了 τ 点 | §C.4.6 步骤 3 |
        | 3 | 该点满足 NFR-7.1（澄清率 ≤ 15%） | §C.4.6 步骤 4："**不满足 → 回看语义包**"（定稿只在满足的分支） |
        | 4 | 声明了 `model_id` | 步骤 5："可审计记录" |
        | 5 | 声明了 `prompt_version` | 步骤 5（P0 = LLM 精排，**改 prompt 即等于换打分器**） |
        | 6 | 有校准日期 | 步骤 5 |
        | 7 | 校准集与验收集分离 | §C.4.6 约束 2 |
        | 8 | 已记录 `binding_layer` 分布（**空映射也算缺**） | 步骤 6（报告产出；L4 占比是"要不要回到步骤 4"的判据） |

        🔴 **与 `blocking_actions` 必须一致**：本属性为真 ⟺ `blocking_actions` 为空。
        两者不一致时报告会"一边说可以定稿、一边列出必须先做的事"，而使用者只会看前者 ——
        单测里有一条不变量专门钉住这一致性（四种形态全过一遍）。

        ⚠️ 条件 3 / 8 是**补上的**：初版只看稳定性 + 选点 + 打分器标识 + 日期 + 分离，
        于是"澄清率 20%（超上限）"或"没记录层分布"的报告也会自称可定稿 ——
        而它自己的 `blocking_actions` 同时写着必须先做那两件事。自相矛盾比漏判更危险。
        """
        return (
            self.stability.is_calibratable
            and self.selected_tau is not None
            and self.nfr71_satisfied
            and bool(self.model_id)
            and bool(self.prompt_version)
            and bool(self.calibrated_at)
            and self.holdout_separated
            and bool(self.layer_distribution)
        )

    def config_lines(self) -> tuple[str, ...]:
        """可直接贴进 `.env` 的配置行（步骤 5 的"写入评测报告"落地形态）。

        只输出**六个**键 —— 与 `core/config.py` 的 `BINDING_TAU*` 一一对应，不另起名字。

        ⚠️ **没有定稿点（`selected_tau is None`）时抛 `ValueError`**，不产出配置行：
        旧实现给的是空值 `BINDING_TAU=`，贴进 `.env` 就是一个解析错误，
        但它看上去像"待填" —— 等于把一个**不存在的** τ 伪装成可部署配置。
        要看缺什么，读 `blocking_actions`。

        ⚠️ `BINDING_TAU_REPORT_REF` **恒为空**：本模块不落盘（见模块 docstring），
        报告存到哪儿只有调用方知道 —— 这一行由落盘方填，不由本模块编一个路径出来。
        """
        if self.selected_tau is None:
            raise ValueError(
                "本报告没有定稿 τ（`selected_tau is None`）→ 不产出配置行。"
                f"原因见 `blocking_actions`：{list(self.blocking_actions)}"
            )
        return (
            f"BINDING_TAU={self.selected_tau}",
            f"BINDING_TAU_EPSILON={self.epsilon}",
            f"BINDING_TAU_MODEL_ID={self.model_id}",
            f"BINDING_TAU_PROMPT_VERSION={self.prompt_version}",
            f"BINDING_TAU_CALIBRATED_AT={self.calibrated_at}",
            "BINDING_TAU_REPORT_REF=",
        )


def calibrate(
    samples: Sequence[ScoreSample],
    *,
    epsilon: float,
    accuracy_target: float,
    model_id: str = "",
    prompt_version: str = "",
    calibrated_at: str = "",
    holdout_separated: bool = False,
    layer_distribution: Mapping[str, int] | None = None,
) -> CalibrationReport:
    """跑完 §C.4.6 的六步：稳定性门槛 → 扫描 → 选点 → 与 NFR-7.1 联立 → 组装报告。

    **选点规则（步骤 3）**：在 `binding_accuracy ≥ accuracy_target` 的点里取**澄清率最小**的；
    并列时依次以 `(准确率更大, τ 更大)` 决出 —— 两个并列打破方向都取保守侧
    （要求更强证据 / 更高的实际准确率），不存在"为降低澄清率而向弱侧滑"的路径。
    这条 tie-break 是**本窗口定的**（原文只说"最小澄清率"），已登记 RELAY §D8。

    **顺序不可交换**：稳定性必须先过。`UNSTABLE` 时**不给 τ 候选**（"禁止定稿"），
    但仍返回曲线供诊断 —— 曲线本身是"该升级打分器"的证据。
    """
    if not 0.0 < accuracy_target <= 1.0:
        raise ValueError(
            f"accuracy_target 必须在 (0, 1] 内，收到 {accuracy_target!r} —— "
            "它由调用方按业务口径给定（§C.4.6 步骤 3 未给数值，本模块不代猜）"
        )
    stability = assess_stability(samples)
    points = sweep(samples, epsilon=epsilon)

    if not stability.is_calibratable:
        return CalibrationReport(
            stability=stability,
            epsilon=epsilon,
            accuracy_target=accuracy_target,
            points=points,
            selected_tau=None,
            selected_point=None,
            nfr71_satisfied=False,
            escalation_required=True,
            blocking_actions=(
                f"打分器稳定性未过（max 分差 std={stability.max_gap_std:.4f} ≥ "
                f"τ 分辨率 {TAU_SWEEP_STEP}）→ §C.4.6 约束 5 **禁止定稿 τ**",
                "按 PRD §12.9 升级为方案 A（本地 cross-encoder）后**重新校准**"
                "（换打分器 = 换量纲，是重跑校准，不是改一个数）",
                "**不得**用'多打几次取平均'绕过（那只是把方差藏起来）",
            ),
            layer_distribution=layer_distribution,
            model_id=model_id,
            prompt_version=prompt_version,
            calibrated_at=calibrated_at,
            holdout_separated=holdout_separated,
        )

    eligible = [
        point
        for point in points
        if point.binding_accuracy is not None and point.binding_accuracy >= accuracy_target
    ]
    selected = (
        min(
            eligible,
            key=lambda p: (p.clarify_rate, -(p.binding_accuracy or 0.0), -p.tau),
        )
        if eligible
        else None
    )

    nfr71 = selected is not None and selected.clarify_rate <= CLARIFY_RATE_LIMIT
    actions: list[str] = []
    if selected is None:
        actions.append(
            f"扫描全程没有任何 τ 满足绑定准确率目标 {accuracy_target} —— "
            "回看语义包（补别名 → L1 / 定 default_binding → L3），**不是**换 τ（§C.4.6 步骤 4）"
        )
    elif not nfr71:
        actions.append(
            f"定稿点澄清率 {selected.clarify_rate:.4f} 超 NFR-7.1 上限 {CLARIFY_RATE_LIMIT} —— "
            "第一补救是**回看语义层**（补别名 → L1 / 定 default_binding → L3，§C.4.6 步骤 4），"
            "**不是放宽 τ**（N-25 / R-19）"
        )
    if not layer_distribution:
        actions.append(
            "缺 `binding_layer` 分布（§C.4.6 步骤 6；**空映射也算缺**）—— "
            "由调用方从运行时观测带入；L4 占比过高说明语义层薄弱，此时**先补语义层**，不是换打分器"
        )
    if not (model_id and prompt_version):
        actions.append("缺打分器标识 `(model_id, prompt_version)` —— 报告不构成可审计记录（步骤 5）")
    if not calibrated_at:
        actions.append("缺校准日期 —— 报告不构成可审计记录（步骤 5）")
    if not holdout_separated:
        actions.append(
            "校准集与验收集未声明分离（§C.4.6 约束 2）—— 定稿 τ 前必须分离，"
            "否则无法排除'在校准集上迭代到过拟合'"
        )

    return CalibrationReport(
        stability=stability,
        epsilon=epsilon,
        accuracy_target=accuracy_target,
        points=points,
        selected_tau=selected.tau if selected is not None else None,
        selected_point=selected,
        nfr71_satisfied=nfr71,
        escalation_required=False,
        blocking_actions=tuple(actions),
        layer_distribution=layer_distribution,
        model_id=model_id,
        prompt_version=prompt_version,
        calibrated_at=calibrated_at,
        holdout_separated=holdout_separated,
    )
