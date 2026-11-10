"""T-20 归因闭环：run_gate1 真回放三条 R06（离线、零成本、只读沙箱、不建图）。

为什么需要：T-20 里那三条 R06 原先只有两条旁证 —— 别名解析（`payment` 未定义）与
`eval/harness.py:156-179` 的 `detect_gate_self_defect` 均返回 `None`，**从未用
`run_gate1` 真回放**。本件补这一手。

构造法照抄 `eval/harness.py:993-1008` 的 `selfcheck`：
  `Harness(bundle_path=..., db_path=...)`
  -> `harness.semantics.guard_allowlist(identity, max_rows=None)`
  -> `run_gate1(sql, allowlist)`
⚠️ 扁平面（`asset_allowlist`）喂 `run_gate1` 会被拒，见 `eval/harness.py:35-36`。

⚠️ 环境硬约束：`backend/app/core/config.py:355` 的 `Settings` 校验拒收
「`DATABASE_URL` 与 `ANALYTICS_DB_URL` 相同」（N-02 / 07 §3.3）。本件默认给两条
**不同角色**的占位 DSN（元数据 `app_rw` / 只读 `app_ro`）；若外部已注入真实 DSN，
本件的 `setdefault` 不会覆盖。

本件不改仓内任何文件、不写证据件、不取号。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "eval"))
sys.path.insert(0, str(REPO_ROOT / "backend"))

os.environ.setdefault("DEEPSEEK_API_KEY", "sk-placeholder-not-a-real-key")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://app_rw:placeholder@127.0.0.1:5432/ecom")
os.environ.setdefault("ANALYTICS_DB_URL", "postgresql+psycopg://app_ro:placeholder@127.0.0.1:5432/ecom")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("ENABLE_RESULT_CACHE_CONFIRMED", "false")

BUNDLE = REPO_ROOT / "semantic" / "bundle_olist_2018_v2.yaml"
DB = REPO_ROOT / "data" / "olist" / "olist_sandbox.db"
TENANT = "T_A"

#: 三条 `GATE_AST_REJECTED` + `R06` 的记录（source, case_id, turn）。
TARGETS: tuple[tuple[str, str, int], ...] = (
    ("results_multiturn_r11_full15_dialect.json", "mt03", 1),
    ("results_multiturn_r12_u169_inherit.json", "mt02", 1),
    ("results_multiturn_r12_u169_inherit.json", "mt15", 1),
)
#: 已知干净的对照（同 case 的 turn2）：没有正控，「一律拒绝」会被误读成归因成立。
CONTROL: tuple[str, str, int] = ("results_multiturn_r12_u169_inherit.json", "mt02", 2)


def _turn(source: str, case_id: str, turn_no: int) -> dict:
    path = REPO_ROOT / "eval" / "olist" / source
    data = json.loads(path.read_text(encoding="utf-8"))
    for record in data.get("records") or []:
        if not isinstance(record, dict) or str(record.get("case_id")) != case_id:
            continue
        for turn in record.get("turns") or []:
            if isinstance(turn, dict) and int(turn.get("turn") or 0) == turn_no:
                return turn
    raise SystemExit("ABORT: 缺记录 " + case_id + " turn" + str(turn_no))


def main() -> int:
    for path in (BUNDLE, DB):
        if not path.is_file():
            print("ABORT: 缺文件 " + str(path))
            return 2

    from harness import Harness, identity_for_case
    from app.guard import run_gate1

    harness = Harness(bundle_path=str(BUNDLE), db_path=str(DB))
    try:
        identity = identity_for_case("T20REPLAY", TENANT)
        allowlist = harness.semantics.guard_allowlist(identity, max_rows=None)
        print(
            "allowlist assets=%d joins=%d deny_columns=%d"
            % (len(allowlist["assets"]), len(allowlist["joins"]), len(allowlist["deny_columns"]))
        )

        def replay(sql: str) -> dict:
            report = run_gate1(sql, allowlist)
            result = report.gate_result
            gate_no = getattr(result.gate_no, "value", result.gate_no)
            return {
                "passed": bool(result.passed),
                "gate_no": str(gate_no),
                "rule_id": str(result.rule_id),
                "reason": str(result.reason or "")[:120],
            }

        mismatched = 0
        for source, case_id, turn_no in TARGETS:
            turn = _turn(source, case_id, turn_no)
            sql = str(turn.get("sql_text") or "")
            expect_rule = str(turn.get("gate1_reject_rule"))
            expect_code = str(turn.get("terminal_code"))
            got = replay(sql)
            ok = (
                got["passed"] is False
                and got["rule_id"] == expect_rule
                and expect_code == "GATE_AST_REJECTED"
            )
            mismatched += 0 if ok else 1
            print(
                "--- %s | sql_len=%d | expect code=%s rule=%s"
                % (case_id, len(sql), expect_code, expect_rule)
            )
            print("    replay passed=%s gate_no=%s rule_id=%s" % (got["passed"], got["gate_no"], got["rule_id"]))
            print("    reason=%s" % got["reason"][:90])
            print("    consistent=%s" % ok)

        source, case_id, turn_no = CONTROL
        ctrl = _turn(source, case_id, turn_no)
        ctrl_sql = str(ctrl.get("sql_text") or "")
        ctrl_got = replay(ctrl_sql)
        print("--- control %s turn%d | sql_len=%d" % (case_id, turn_no, len(ctrl_sql)))
        print("    replay passed=%s rule_id=%s" % (ctrl_got["passed"], ctrl_got["rule_id"]))
        print(
            "SUMMARY target_rows=%d mismatched=%d control_passed=%s"
            % (len(TARGETS), mismatched, ctrl_got["passed"])
        )
        return 0
    finally:
        try:
            harness.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main())
