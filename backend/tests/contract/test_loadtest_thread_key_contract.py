"""`U-138` 的离线契约：压测回执侧的"组"尺**不许**再自称服务端 thread，且两把键必须同框可追。

为什么这张单值得一条契约测试（不是"顺手加个 lint"）
--------------------------------------------------------------------------
`docs/07 §4.8` 台账里 `U-138` 三条判据的现读措辞：① `driver.py` 的 `thread_depth` 分组键与库面同键
（`tenant:user:session`，剔作废）**或**改名（如 `worker_session_groups`）并停止自称 thread；
② 两把不等价时必须同框并报；③ 凡"同一 thread 第 N 轮"的结论只从库面取。

本窗采的是**改名那一支**，理由钉在 `deploy/loadtest/driver.py` 的 docstring 与这里第 1 条测试：
压测件不解 JWT、不连 DB ⇒ 客户端**拼不出** `{tenant}:{user}:{session}`，硬凑只会造出第二份假 thread 真相。
（旧回执里 7 组 vs 库面 3 条 thread 就是不等价的实测形状。）

⚠️ 这里量的是**量具面**：契约绿 ≠ `U-129` 结案，也 ≠ 当期回执已同框并报 —— 后者是运行面读数，
    必须由装配方 `backend/reports/w8/t38_assemble.py` 的 `thread_key_discrepancy` 格给（第 4 条测的是那份归档件还在、且两格都非 null）。
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DRIVER = ROOT / "deploy" / "loadtest" / "driver.py"
R23_SQL = ROOT / "deploy" / "loadtest" / "r23_thread_from_checkpoints.sql"
ASSEMBLED = ROOT / "backend" / "reports" / "w8" / "t38_assembled.json"
README = ROOT / "deploy" / "loadtest" / "README.md"


def _load_driver() -> Any:
    spec = importlib.util.spec_from_file_location("loadtest_driver_under_test", DRIVER)
    assert spec and spec.loader, f"尺坏：载不动 {DRIVER}"
    module = importlib.util.module_from_spec(spec)
    # ⚠️ 必须先注册再 exec：`Sample` 是 `@dataclass(slots=True)`，dataclasses 要用 `sys.modules[cls.__module__]`
    # 的 `__dict__` 解析模块命名空间 —— 没注册时现场炸成 `AttributeError: 'NoneType' object has no attribute '__dict__'`
    # （这是"尺坏"，不是被测面红；本项目第 N 次撞到"先把尺修对再读数"）。
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def _samples(driver: Any) -> list[Any]:
    """3 组 / 4 条：`(0, sA)` 两条、`(1, sB)` 一条、`(2, None)` 一条（无会话桶必须留着暴露 `--reuse-sessions` 没开）。"""
    return [
        driver.Sample("ok", 200, 1.0, 1.0, 1, worker=0, session_id="sA"),
        driver.Sample("ok", 200, 1.5, 1.0, 1, code="GATE_AST_REJECTED", worker=0, session_id="sA"),
        driver.Sample("clarify", 200, 2.0, 1.0, 1, worker=1, session_id="sB"),
        driver.Sample("ok", 200, 2.5, 1.0, 1, worker=2, session_id=None),
    ]


def test_depth_ruler_declares_its_own_key_and_denies_being_a_thread() -> None:
    """判据①（改名支）：这把尺必须**自报**分组键、显式声明它不是服务端 thread，并给出库面尺指针。"""
    driver = _load_driver()
    got = driver._worker_session_depth(_samples(driver))
    assert got["grouping_key"] == "(worker, session_id)", got["grouping_key"]
    assert got["is_server_thread"] is False, "键语义漂回 thread ⇒ U-138① 破"
    assert got["groups"] == 2, got["groups"]  # sA(0) / sB(1) 两组；None 那条进 unsessioned
    assert got["unsessioned"] == 1, got["unsessioned"]
    assert "threads" not in got and "thread_depth" not in got, "旧键名仍在读数面 ⇒ 又自称 thread 了"
    ruler = str(got["server_thread_ruler"])
    assert "r23_thread_from_checkpoints.sql" in ruler and R23_SQL.exists(), f"库面尺指针指空：{ruler}"


def test_server_side_thread_key_shape_is_a_colon_joined_thread_id() -> None:
    """判据②的可追面：库面那把尺的量的是 **`thread_id` 整串**（冒号拼接的多段键），不是二元组。

    两把键"不等价"这件事只有在两边形状都被钉住时才是可判伪的 —— 若哪天有人把 ⑮/⑰ 的分组键
    收成 `usr` 一段（漂向 worker/user 尺），这条立刻红，而不是等到又拿聚合数推序列。
    """
    sql = R23_SQL.read_text(encoding="utf-8").lower()
    assert re.search(r"(partition by\s+ck\.thread_id|count\(distinct\s+(ck\.)?thread_id\))", sql), \
        "库面尺不再按 `thread_id` 整串分组 ⇒ 两把键的同框失去共同参照"
    assert re.search(r"split_part\(\s*ck\.thread_id\s*,\s*':'\s*,\s*2\s*\)", sql), \
        "库面键不再是冒号拼接的多段形状（`split_part(thread_id,':',2)` 取 user 段）"


def test_producer_emits_the_renamed_key_and_no_thread_named_one() -> None:
    """判据①的产出面：`_summarize` 写进回执的键必须是 `worker_session_depth`，不许再写 `thread_depth`。"""
    src = DRIVER.read_text(encoding="utf-8")
    assert '"worker_session_depth": _worker_session_depth(samples)' in src, "产出键没改名"
    assert '"thread_depth":' not in src, '回执里仍有 `"thread_depth":` 这个键 ⇒ 抄本漂回'
    assert "_thread_depth(" not in src, "旧函数名残留"


def test_current_batch_receipt_reports_both_rulers_in_one_frame() -> None:
    """判据②的结案面：当期那把批的**两把键必须同框并报**（缺任一格 = 只交了一把）。"""
    if not ASSEMBLED.exists():
        raise AssertionError(f"当期回执装配件不在盘上（{ASSEMBLED}）⇒ 判据②没落，不许 skip 蒙过（U-114 同形：禁止 skip）")
    cell = json.loads(ASSEMBLED.read_text(encoding="utf-8"))["thread_key_discrepancy"]
    receipt_side = cell["receipt_侧"]["组数"]
    db_side = cell["库面"]["剔作废"]
    assert isinstance(receipt_side, int) and isinstance(db_side, int), (receipt_side, db_side)
    assert receipt_side > db_side, f"两把同框但没暴露不等价：回执 {receipt_side} 组 vs 库面 {db_side} 条"
    assert "tenant:user:session" in cell["库面"]["分组键"], cell["库面"]["分组键"]
    assert cell["receipt_侧"]["分组键"] == "(worker, session_id)", cell["receipt_侧"]["分组键"]


def test_readme_copy_carries_the_new_key_name() -> None:
    """多处抄本同改：`deploy/loadtest/README.md` 是 thread 尺的**对外抄本**，代码改名而抄本不改 = 第二份真相。"""
    text = README.read_text(encoding="utf-8")
    assert "worker_session_depth" in text, "README 没跟上改名 ⇒ U-138 只落了一半"
    assert "U-138" in text, "README 没登记这次改名的依据号"
