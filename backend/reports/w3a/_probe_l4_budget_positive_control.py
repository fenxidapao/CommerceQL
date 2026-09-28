"""W3A 正向对照探针：把 `L4_SCORE` 的 `output_tokens_hint` 注入回**事故值 512**，
确认新标定测试 `TestL4ScoreBudgetIsCalibratedFromMeasurement` **必须变红**。

归属窗口：W3A（`backend/reports/w3a/**`）。只读被测代码、不写库、不连网、零 DeepSeek 额度。

--------------------------------------------------------------------------
为什么需要这个探针（判别力 ≠ "现状是绿的"）
--------------------------------------------------------------------------
新测试能过，只证明"当前值 2304 满足 2109"。它**不**证明"再有人调回 512 会被拦住" ——
而后者才是这条测试存在的理由（512 事故的复发路径就是"有人觉得 512 够用"）。

本探针把违规**注入进去**：只在内存里替换路由表条目（`dataclasses.replace`，不碰磁盘），
跑那一组测试，要求 `exit_code != 0`。若全绿 ⇒ 测试是摆设（探针自己 exit 1）。

⇒ 这就是"注入 → 必须红 → 还原 → 必须绿"里的前两格；后两格由**不注入**的常规 pytest 承担。
   （还原是自动的：注入只存在于本进程内存，进程退出即散。）

--------------------------------------------------------------------------
跑法（在 `backend/` 下，无需 PG/Redis）
--------------------------------------------------------------------------
    ../.venv/Scripts/python.exe reports/w3a/_probe_l4_budget_positive_control.py

期望输出末行：`[verdict] 判别力 OK`，退出码 0。
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

#: `backend/`（`reports/w3a/xxx.py` → parents[2]）。
_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND))

import pytest  # noqa: E402

from app.llm.router import TASK_ROUTES, LlmTask  # noqa: E402

#: 事故值：512 上限把 `l4_score` 149 次调用里的 96 次截断（L4 整层静默失效 64.4%）。
_INCIDENT_VALUE = 512

_NODE = "::TestL4ScoreBudgetIsCalibratedFromMeasurement"
#: 绝对路径：相对路径会按 **cwd** 解析 —— 从别的目录跑就会"零收集"，
#: 而零收集的退出码也非 0，会被下面的判定误读成"如期被拦住"（自欺）。
_TEST_FILE = str(_BACKEND / "tests" / "unit" / "test_llm_router.py")


def main() -> int:
    route = TASK_ROUTES[LlmTask.L4_SCORE]
    print(f"[inject] 注入前 output_tokens_hint = {route.output_tokens_hint}")

    # 只改 hint，其余字段照抄 —— 注入的是"事故值"本身，不是别的违规。
    TASK_ROUTES[LlmTask.L4_SCORE] = replace(route, output_tokens_hint=_INCIDENT_VALUE)
    print(f"[inject] 注入后 output_tokens_hint = {TASK_ROUTES[LlmTask.L4_SCORE].output_tokens_hint}")

    exit_code = pytest.main(["-q", "--no-header", _TEST_FILE + _NODE])
    print(f"[result] exit_code={exit_code}")

    # 🔴 只认 `TESTS_FAILED`(=1)。其他非 0（收集错误 / 用法错误 / 内部错误）**不算**判别力 ——
    #    把它们当成功，正是"假绿把自己骗过去"的经典形态（探针自身也要有正向对照）。
    discriminating = exit_code == pytest.ExitCode.TESTS_FAILED
    if discriminating:
        print("[verdict] 判别力 OK —— 注入 512 后如期变红")
        return 0
    print(
        f"[verdict] FAIL：注入 512 后期望 exit=1(TESTS_FAILED)，实得 {exit_code} —— "
        "不是'测试拦住违规'，而是'测试根本没跑起来'或'测试是摆设'"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
