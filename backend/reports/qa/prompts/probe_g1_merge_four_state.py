r"""QA 永久反证件：G-1 输入装配的**四态**（T-32 修法 ＋ QA 第 8 轮 §11.4／§11.5 两处新失明的尺）。

零额度：零 LLM 出站、零库连接、零写盘。四份 pytest 日志由本件自造在 `tempfile.mkdtemp()`、
`finally` 删 ⇒ 不依赖本机临时目录，也不需要 `.log` 入库（`.gitignore:47` 全局忽略 `*.log`）。

为什么是四态而不是 W8 那 12 条两态夹具的复制：`eval/reporter.py:898` 的合并支带一个守卫
`if p0 and p0_integration and not p0["integration_ran"]` —— 第一槽只要点过 `tests/integration/*.py`
就**整份跳过第二槽**（件内注释：防同一条红数两遍）。该前提只在"两份日志同源"时成立；
不同源时第二槽的红**静默不计**、器件不喊 ⇒ QA 第 8 轮实测（`reports/qa/RELAY.md §十一.11.4`）。

用法（仓库根跑；cwd 不敏感，件内自带绝对 `sys.path`）：
    PYTHONUTF8=1 .venv/Scripts/python.exe backend/reports/qa/prompts/probe_g1_merge_four_state.py

退出码：0 = 四态实测与 `now` 列逐格相等（= 复现 2026-10-04 22:1x 基准）；1 = 有格子偏离。
两列期望的分工：`now` = 今天已知形状（含 §11.4 那处**未修**）；`want` = `T-34 顺带 A` 交付后应有形状。
⇒ 态③ 今天 `now = PASS` 而 `want = FAIL` ⇒ **这一格的"未修"是刻意的验收位**，
   修法落地后该格应 `now` 与 `want` 同为 FAIL（或器件自描述 ⇒ 届时重取基准并具名订正）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

#: 深度尺：本件在 `backend/reports/qa/prompts/` ⇒ 仓库根 = **`parents[4]`**（`parents[3]` 是 `backend/`）。
#: 🔻 本窗在"相对深度"上第三次踩坑（前两次：`.venv` 与 psql 抽段）⇒ 深度现测、并印出来供对表。
ROOT = Path(__file__).resolve().parents[4]
PY = sys.executable
W6 = ROOT / "backend" / "reports" / "w6"
REAL_LOGS = (W6 / "_full_pytest_1004_rT32.log", W6 / "_integration_pytest_1004_rT32.log")

OFFLINE_RED = """collected 2348 items
tests/unit/test_startup_assertions.py .F
=================================== FAILURES ===================================
FAILED tests/unit/test_startup_assertions.py::test_x - AssertionError: boom
======================== 1 failed, 2347 passed in 90.10s ========================
"""
OFFLINE_CLEAN = """collected 2347 items
tests/unit/test_startup_assertions.py ...........................        [ 10%]
tests/unit/test_config.py ................                              [100%]
======================== 2347 passed in 88.20s =========================
"""
INTEGRATION_CLEAN = """collected 107 items
tests/integration/test_rls_tenant_isolation.py ........................  [100%]
============================= 107 passed in 27.44s ==============================
"""
INTEGRATION_RED = """collected 107 items
tests/integration/test_rls_tenant_isolation.py ......................... [ 98%]
tests/integration/test_audit_append_only.py F                            [100%]
=================================== FAILURES ===================================
FAILED tests/integration/test_audit_append_only.py::test_audit_append_only_x - AssertionError: boom
=================================== ERRORS ====================================
ERROR tests/integration/test_feedback_store_pg.py::test_feedback_store_pg - RuntimeError: teardown boom
=================== 1 failed, 105 passed, 1 error in 30.11s ===================
"""

#: `recompute_gate()` 返的是 `dataclasses.asdict()`（dict）不是 `Gate` 对象 ⇒ 只能按键取
#: （QA 第 8 轮 §11.9 自曝：写 `g.verdict` ⇒ `AttributeError`，rc=1 ＋ stdout 空，易被读成"没跑出东西"）。
SNIPPET = (
    "import sys,json;sys.path[:0]=%s;"
    "import reporter as r;"
    "kw=json.loads(sys.argv[2]);"
    "g=r.recompute_gate('G-1',**kw);"
    "print(json.dumps({'verdict':g['verdict'],'red':g['red_split'],"
    "'measured':str(g['measured'])[-240:]},ensure_ascii=False))"
)


def _fwd(p: object) -> str:
    return str(p).replace("\\", "/")


def run(pytest_log: str, integration_log: str) -> tuple[int, object]:
    """把两把日志喂进**唯一装配口**（`gate_inputs()` 经 `recompute_gate()`）。零额度。"""
    kw = {"pytest_log": pytest_log, "integration_log": integration_log}
    paths = json.dumps([_fwd(ROOT / "eval"), _fwd(ROOT)])
    p = subprocess.run([PY, "-c", SNIPPET % paths, "--", json.dumps(kw)], cwd=_fwd(ROOT),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "").strip()
    if p.returncode != 0 or not out:
        return (p.returncode or 1), (_fwd(out or (p.stderr or "").strip()))[-300:]
    return 0, json.loads(out)


def main() -> int:
    print(f"[件自证] ROOT = {_fwd(ROOT)}（parents[4] 现测）｜夹具目录 = mkdtemp，跑完即删")
    tmp = Path(tempfile.mkdtemp(prefix="qa_g1_four_state_"))
    try:
        def w(name: str, body: str) -> str:
            path = tmp / name
            path.write_text(body, encoding="utf-8")
            return _fwd(path)

        cases = (
            # (说明, 离线槽, 集成槽, 今天实测 now, T-34A 后应有 want)
            ("态① 脏离线／净集成（红在离线 —— T-32 修的就是这一支）",
             w("offline_red.log", OFFLINE_RED), w("integration_clean.log", INTEGRATION_CLEAN),
             "FAIL", "FAIL"),
            ("态② 净离线／脏集成（反向：`failed` 与 `error` 两列都要进判定量）",
             w("offline_clean.log", OFFLINE_CLEAN), w("integration_red.log", INTEGRATION_RED),
             "FAIL", "FAIL"),
            ("态③ 守卫支（离线槽点过集成文件 ⇒ 第二槽整份不参与合并）",
             w("integ_clean_as_offline.log", INTEGRATION_CLEAN),
             w("integration_red_2.log", INTEGRATION_RED), "PASS", "FAIL"),
            ("态④ 净态对照（两槽都 0 红 ⇒ 判据谓词未动，仍应 PASS）",
             w("offline_clean_2.log", OFFLINE_CLEAN), w("integration_clean_2.log", INTEGRATION_CLEAN),
             "PASS", "PASS"),
        )

        drift = 0
        for label, offline, integration, now, want in cases:
            rc, g = run(offline, integration)
            if rc != 0:
                print(f"[ERR ] {label}\n        器件跑不起来 rc={rc}：{g}")
                drift += 1
                continue
            red = g["red"]
            same = g["verdict"] == now
            drift += 0 if same else 1
            print(f"[{'复现' if same else '漂移'}｜{'已修' if g['verdict'] == want else '未修'}] {label}")
            print(f"        verdict = {g['verdict']}（now {now}／want {want}）"
                  f" ｜ assertion_failures = {red.get('assertion_failures')}"
                  f" ｜ environment_errors = {red.get('environment_errors')}"
                  f" ｜ red_total = {red.get('red_total')}")
            print(f"        measured… = {g['measured'][-150:]}")

        if all(p.exists() for p in REAL_LOGS):
            rc, g = run(_fwd(REAL_LOGS[0]), _fwd(REAL_LOGS[1]))
            print(f"[附] 当期真实两把日志（不参与四态计数）→ "
                  f"{g['verdict'] if rc == 0 else str(g)[:220]}")
        else:
            print("[附] 当期真实日志不在位 ⇒ 该臂 UNVERIFIED（`*.log` 不入库属预期）")

        print(f"\n漂移 {drift} 格／4（rc=1 ⇒ 装配面与 2026-10-04 22:1x 基准不一致，须重取基准并具名订正）")
        return 1 if drift else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
