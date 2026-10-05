r"""QA 永久反证件：G-1 输入装配的**五态**（T-32 修法 ＋ QA 第 8 轮 §11.4／§11.5 ＋ W8 第 11 轮换法）。

零额度：零 LLM 出站、零库连接、零写盘。五份 pytest 日志由本件自造在 `tempfile.mkdtemp()`、
`finally` 删 ⇒ 不依赖本机临时目录，也不需要 `.log` 入库（`.gitignore:47` 全局忽略 `*.log`）。

为什么是五态而不是 W8 那 15 条夹具的复制：`eval/reporter.py` 的旧守卫（QA 第 8 轮 §11.4）只看
"离线槽有没有点过集成文件名"，那等于**假设**两槽同源；假设不成立时第二槽的红**静默不计**、器件不喊。
W8 第 11 轮把它换成可核的事实 = `covers_integration()`（集成槽点名的文件须逐个出现在离线槽里才允许跳过）
⇒ "跳过"合法（态⑤）与"部分重叠必须合并"（态③）各占一格，另两态测双向红（态①／态②）、一态净态对照（态④）。

用法（仓库根或任意 cwd，件内自带绝对 `sys.path`）：
    PYTHONUTF8=1 .venv/Scripts/python.exe backend/reports/qa/prompts/probe_g1_merge_four_state.py

退出码：0 = 五态的 `verdict` 与 `red_total` 双双等于基准列；1 = 任一格偏离 ⇒ 装配面又动了，须重取基准并具名订正。
`now` 基准列于 **2026-10-05 04:1x 重取**（QA 第 15 轮，HEAD `9e45281`，W8 第 11 轮交付后）⇒ `want` 与 `now` 已并平，
所以本件从"验收位"转成"**回归件**"。
🔴 态⑤ 另钉一条：同源跳过时 `red_total` 必须是 **1 而不是 2** ⇒ 防"干脆改成永远合并"把同一条红数两遍
   （那正是 `merge_p0_logs` 件内注释里"`passed` 会偏成并集上界"的前提）。
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
#: 整树 `-v` 那种日志：既点单元／契约、又**整份覆盖**集成槽点名的文件 ⇒ 这才是守卫支唯一该跳过的形状。
WHOLE_TREE_RED = """collected 2456 items
tests/unit/test_config.py ..............................                 [ 42%]
tests/integration/test_rls_tenant_isolation.py ......................... [ 96%]
tests/integration/test_audit_append_only.py F                            [ 98%]
tests/integration/test_feedback_store_pg.py .                            [100%]
=================================== FAILURES ===================================
FAILED tests/integration/test_audit_append_only.py::test_audit_append_only_x - AssertionError: boom
======================== 1 failed, 2455 passed in 121.30s ========================
"""

#: `recompute_gate()` 返的是 `dataclasses.asdict()`（dict）不是 `Gate` 对象 ⇒ 只能按键取
#: （QA 第 8 轮 §11.9 自曝：写 `g.verdict` ⇒ `AttributeError`，rc=1 ＋ stdout 空，易被读成"没跑出东西"）。
SNIPPET = (
    "import sys,json;sys.path[:0]=%s;"
    "import reporter as r;"
    "kw=json.loads(sys.argv[2]);"
    "g=r.recompute_gate('G-1',**kw);"
    "print(json.dumps({'verdict':g['verdict'],'red':g['red_split'],"
    "'measured':str(g['measured'])[-240:],"
    "'caveats':[str(c)[-260:] for c in g['caveats']]},ensure_ascii=False))"
)


def _fwd(p: object) -> str:
    return str(p).replace("\\", "/")


def newest(prefix: str) -> Path | None:
    """当期那把日志 = 目录里该前缀下 **mtime 最新**的一份。

    🔻 QA 第 15 轮：第一版把文件名写死成 `_…_rT32.log`，下一轮换成了 `rT34b` ⇒ 附臂静默变 SKIP。
    "写死当期文件名"的件天生一轮就烂 ⇒ 按 mtime 取，并把**用的哪一把**印出来。
    """
    cands = sorted(W6.glob(f"{prefix}*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def run(pytest_log: str, integration_log: str) -> tuple[int, object]:
    """把两把日志喂进**唯一装配口**（`gate_inputs()` 经 `recompute_gate()`）。零额度。"""
    kw = {"pytest_log": pytest_log, "integration_log": integration_log}
    paths = json.dumps([_fwd(ROOT / "eval"), _fwd(ROOT)])
    p = subprocess.run([PY, "-c", SNIPPET % paths, "--", json.dumps(kw)], cwd=_fwd(ROOT),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "").strip()
    if p.returncode != 0 or not out:
        return (p.returncode or 1), _fwd(out or (p.stderr or "").strip())[-300:]
    return 0, json.loads(out)


def main() -> int:
    print(f"[件自证] ROOT = {_fwd(ROOT)}（parents[4] 现测）｜夹具目录 = mkdtemp，跑完即删")
    tmp = Path(tempfile.mkdtemp(prefix="qa_g1_five_state_"))
    try:
        def w(name: str, body: str) -> str:
            path = tmp / name
            path.write_text(body, encoding="utf-8")
            return _fwd(path)

        cases = [
            # (说明, 离线槽, 集成槽, 基准 now, 应有 want, 期望 red_total)
            ("态① 脏离线／净集成（红在离线 —— T-32 修的那一支）",
             w("offline_red.log", OFFLINE_RED), w("integration_clean.log", INTEGRATION_CLEAN),
             "FAIL", "FAIL", 1),
            ("态② 净离线／脏集成（反向：`failed` 与 `error` 两列都要进判定量）",
             w("offline_clean.log", OFFLINE_CLEAN), w("integration_red.log", INTEGRATION_RED),
             "FAIL", "FAIL", 2),
            ("态③ 部分重叠（离线槽只点到集成槽的一部分文件 ⇒ 必须合并、不许静默丢红）",
             w("integ_clean_as_offline.log", INTEGRATION_CLEAN),
             w("integration_red_2.log", INTEGRATION_RED), "FAIL", "FAIL", 2),
            ("态④ 净态对照（两槽都 0 红 ⇒ 判据谓词未动，仍应 PASS）",
             w("offline_clean_2.log", OFFLINE_CLEAN), w("integration_clean_2.log", INTEGRATION_CLEAN),
             "PASS", "PASS", 0),
            ("态⑤ 真同源（离线槽整份覆盖集成槽点名的文件 ⇒ 允许跳过合并，红只数一遍）",
             w("whole_tree_red.log", WHOLE_TREE_RED), w("integration_red_3.log", INTEGRATION_RED),
             "FAIL", "FAIL", 1),
        ]

        drift = 0
        for label, offline, integration, now, want, want_red in cases:
            rc, g = run(offline, integration)
            if rc != 0:
                print(f"[ERR ] {label}\n        器件跑不起来 rc={rc}：{g}")
                drift += 1
                continue
            red = g["red"]
            same = g["verdict"] == now
            red_ok = red.get("red_total") == want_red
            drift += 0 if (same and red_ok) else 1
            print(f"[{'复现' if same else '漂移'}｜{'红数对' if red_ok else '红数错'}"
                  f"｜{'达标' if g['verdict'] == want else '偏离'}] {label}")
            print(f"        verdict = {g['verdict']}（now {now}／want {want}）"
                  f" ｜ assertion_failures = {red.get('assertion_failures')}"
                  f" ｜ environment_errors = {red.get('environment_errors')}"
                  f" ｜ red_total = {red.get('red_total')}（期望 {want_red}）")
            print(f"        measured… = {g['measured'][-140:]}")
            for c in (g.get("caveats") or []):
                print(f"        caveat… = {c[-150:]}")

        off_real, int_real = newest("_full_pytest"), newest("_integration_pytest")
        if off_real and int_real:
            rc, g = run(_fwd(off_real), _fwd(int_real))
            print(f"[附] 当期真实两把日志（mtime 最新，不参与计数）→ "
                  f"{g['verdict'] if rc == 0 else str(g)[:220]}"
                  f" ｜ 用的是 {off_real.name} ＋ {int_real.name}")
        else:
            print("[附] 当期真实日志不在位 ⇒ 该臂 UNVERIFIED（`*.log` 不入库属预期）")

        print(f"\n漂移 {drift} 格／5（基准 = 10-05 04:1x 重取，含 W8 第 11 轮 "
              f"`covers_integration()` 与输入自报两件）")
        return 1 if drift else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
