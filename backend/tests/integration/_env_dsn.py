"""U-114 防线① 的共享 DSN 守卫（2026-09-22，W2A）。

历史根因：集成夹具曾用
`os.environ.get("COMMERCEQL_TEST_RW_DSN", "postgresql://…@localhost:5432/<共享库名>")`
—— 字面默认值指向**共享库**，任何窗口漏带 env 就会静默打到共享库
（2026-09-22 `embed_doc` 派生列一天被清两轮的帮凶之一）。

判据（arch RELAY §24.2）：
- 集成夹具文件里 grep 不到指向共享库的字面默认 DSN（本文件也不落该字面量）；
- 缺 env 必须 **fail/error，禁止 skip**（skip = 假绿，与"缩门禁 scope"同族）。

CI 安全性：ci.yml 唯一的 pytest 步骤（全量测试）已注入 RW/RO/SUPER 三个 env
（`ci.yml:125-127`）；本地门禁按路径收集（tests/unit、tests/contract），
不 import 本包 —— 因此 import 期抛错不影响任何离线运行。
"""

from __future__ import annotations

import os

__all__ = ["env_dsn"]


def env_dsn(env_name: str) -> str:
    """读集成测试 DSN。缺失 = **当场 RuntimeError**（fail，不是 skip、不是默认值）。"""
    val = os.environ.get(env_name, "")
    if not val:
        raise RuntimeError(
            f"环境变量 {env_name} 未设置 —— U-114 防线①：集成测试拒绝共享库字面默认值，"
            "缺 env 必须 fail/error（禁止 skip）。"
            "请把它指向**一次性测试库**（不要指向共享 ecom）后重跑。"
        )
    return val
