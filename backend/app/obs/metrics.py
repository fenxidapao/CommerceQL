"""指标 —— 骨架（07 §15.3、§15.4、§15.5）。

归属窗口：W0 立骨架 → **W7 实现**（docs/08 §4.1）。

⚠️ **阶段 0 刻意不定义任何指标名**，理由是"指标名一旦写错就是把猜测变成契约"：
07 §15.3 的完整清单（含**标签基数上限**）阶段 0 尚未逐条核实，
凭空起名会被 W7 沿用，然后出现"看板与告警读的不是同一个指标"这种最难查的问题。

已核实并写进文档、W7 必须遵守的三条**口径**（07 §14.5 / §15.3）：

1. **语义指标优先于系统指标**（PRD §14.2）。延迟、QPS 再漂亮，
   也不能替代"闸门拒绝率 / 拒答率 / 澄清率"这类业务侧口径。
2. **标签维度必须按 07 §14.5 指定的键**，不得自创：
   闸门拒绝率 → `gate_no` + **`rule_id`**；拒答率 → `refuse.reason` 四值；
   降级率 → `degraded.reason` + `action_taken`；限流 → `bucket`（**不含**会话串行冲突，那是 409）。
3. **标签基数上限**：`rule_id`（20 个 AST 规则）、`degraded.reason`（8）、`action_taken`（7）
   都是**有界**的，可以安全做标签；而 `task_id` / `session_id` / `user_id` **绝不可**做标签 ——
   它们无界，会把时序库直接打爆。这条是本文件存在的最大价值。

W7 待办清单（与 `app/obs/schema.py` 的 `PENDING_FIELD_GROUPS_OWNER_W7` 配套）：
- §15.3 指标清单全集 + 每个指标的标签集与**基数上限**；
- §15.4 告警规则（6 条）；
- §15.5 最小看板（自用，不追求美观）；
- §16.5 四场景压测的采集口径。
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "BINDING_TAU_CALIBRATED",
    "BOUNDED_ALLOWED_LABELS",
    "UNBOUNDED_FORBIDDEN_LABELS",
    "get_binding_tau_calibrated",
    "render_prometheus_text",
    "set_binding_tau_calibrated",
]


# ============================================================================
# ★ 阶段 0 **唯一**被允许提前命名的指标（U-19 §18.4.1 硬要求 ②）
# ============================================================================
# 上面刚说了"阶段 0 刻意不定义任何指标名"。这里是一个**有意的例外**，且只有一个：
#
#   07 §18.4.1 要求 —— 非 prod 下 τ 未校准虽放行，但**不得隐瞒**，
#   载体是 ① 启动日志 WARN（必打）② 指标 gauge `binding_tau_calibrated` 0/1，
#   使"有多少实例端着未校准的 τ 在跑"是**可查询的**。
#
# 为什么这个例外是安全的（与"凭空起名"的区别）：
#   ① 名字**由 07 明文给定**（不是我起的）；
#   ② 它是 **gauge 无标签**——没有基数风险，也不会与 W7 的看板口径冲突；
#   ③ 不引入新依赖：手写 Prometheus 文本格式（Prometheus text format 只有几行语法），
#      无需 `prometheus_client` —— 加依赖要同时改 pyproject 与 §4.2 白名单测试（ADR-20 双录账），
#      为一行 gauge 不值当。W7 接真实指标库时，本常量是唯一需要保留的遗留物。
BINDING_TAU_CALIBRATED: Final[str] = "binding_tau_calibrated"

#: HELp 文案：把"0 意味着什么"写进指标本身 —— 看板作者不必回来读代码。
_BINDING_TAU_HELP: Final[str] = (
    "1 = BINDING_TAU 已绑定 model_id+prompt_version 且经冻结集校准；"
    "0 = 未校准（仅允许 APP_ENV!=prod，此时 L4 精排结果不具备生产判定效力）"
)

_binding_tau_value: int = 0


def set_binding_tau_calibrated(calibrated: bool) -> None:
    """启动期写入。由 `app.main.lifespan` 在启动时调用（U-19 硬要求 ②）。"""
    global _binding_tau_value
    _binding_tau_value = 1 if calibrated else 0


def get_binding_tau_calibrated() -> int:
    """读回当前值（契约测试用；也可供后续窗口做启动自检）。"""
    return _binding_tau_value


def render_prometheus_text() -> str:
    """Prometheus 文本格式快照。

    ⚠️ 阶段 0 **不**挂 `/metrics` 端点（那是 W7 的 `deploy/` + 观测收口范围）；
    本函数只保证"这个 gauge 现在就可被暴露"。W7 接真实指标库后，
    应把它并入统一的采集端点，而不是再起第二个。
    """
    return (
        f"# HELP {BINDING_TAU_CALIBRATED} {_BINDING_TAU_HELP}\n"
        f"# TYPE {BINDING_TAU_CALIBRATED} gauge\n"
        f"{BINDING_TAU_CALIBRATED} {_binding_tau_value}\n"
    )

#: **绝对禁止**作为指标标签的键（无界基数）。
#: 这不是性能建议，是可用性红线：一个 `user_id` 标签能在一个下午内把指标存储写满，
#: 而且症状表现为"监控先挂了"，与业务无关却最先被发现。
UNBOUNDED_FORBIDDEN_LABELS: Final[frozenset[str]] = frozenset(
    {
        "trace_id",
        "task_id",
        "session_id",
        "user_id",
        "raw_question",
        "sql_text",
        "clarify_id",
        "idempotency_key",
    }
)

#: **允许**作为标签的键（有界基数）。上界写在括号里，W7 实现时按此设限。
BOUNDED_ALLOWED_LABELS: Final[dict[str, int]] = {
    "stage": 6,            # 07 §14.3 约束 8
    "gate_no": 3,          # 1/2/3
    "rule_id": 20,         # AST-R01…R20（07 §7.2；注意 §14.2 D1 曾误写为 R01…R16，见 U-16）
    "refuse_reason": 4,    # C-12
    "degraded_reason": 8,  # C-08
    "action_taken": 7,     # C-08
    "error_code": 28,      # 附录 A §A.11
    "bucket": 5,           # A.0.6（含全局并发桶）
    "binding_state": 4,    # 四态
    "binding_layer": 4,    # L1–L4（N-27 约束 5）
    "retrieval_mode": 2,   # C-11
    "scope_level": 3,      # A.1.5
    "role": 7,             # 07 §13.2
    "model": 2,            # flash / pro（P0）
    "prompt_version": 8,   # 灰度期上限（超过即说明版本清理没做）
    "graph_version": 8,
}
