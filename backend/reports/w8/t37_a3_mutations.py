"""T-37 A3 的单变量对照：每条变异必须让 `test_eval_launch_dryrun_contract.py` 翻红。

跑法（尺已入库；⚠️ 会**临时改生产件字节** ⇒ 只在没有别窗在途改动时跑，跑完自核 md5）：
    cd backend && PYTHONUTF8=1 PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe reports/w8/t37_a3_mutations.py
每条形如：读原字节 → 打一处变异 → 跑 pytest → 还原字节 → 核 md5。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]        # reports/w8 -> backend
LAUNCH = BACKEND / "app/present/eval_launch.py"
ROUTER = BACKEND / "app/api/routers/admin_eval.py"
DTO = BACKEND / "app/api/dto/eval_run.py"
TEST = "tests/contract/test_eval_launch_dryrun_contract.py"

MUTATIONS: list[tuple[str, Path, str, str]] = [
    ("M1 非 LLM 节点也计数", LAUNCH, "if node in LLM_NODE_NAMES", "if node is not None"),
    (
        "M2 不看 config.live",
        LAUNCH,
        'if cfg.get("live") is not True:\n            continue',
        "if False:\n            continue",
    ),
    ("M3 编一个 run_id", LAUNCH, '"run_id": None,', '"run_id": "run_01J8XA",'),
    ("M4 冒充已排队", LAUNCH, '"status": "dry_run",', '"status": "queued",'),
    ("M5 声称模型已证", LAUNCH, '"evidenced_by_basis": False,', '"evidenced_by_basis": True,'),
    ("M6 保守档取 min", LAUNCH, "max(per_case_max_cost)", "min(per_case_max_cost)"),
    ("M7 峰档乘数按 1 算", LAUNCH, 'ratio = Decimal(_peak_ratio()["multiplier"])', 'ratio = Decimal("1")'),
    (
        "M8 抹掉发起缺口",
        LAUNCH,
        '"launch_blockers": launch_blockers(),',
        '"launch_blockers": [],',
    ),
    (
        "M9 副本当两次独立观测",
        LAUNCH,
        '{(b["git_rev"], b["generated_at"], b["cost_cny_total"], b["cases"]) for b in batches}',
        '{b["artifact"] for b in batches}',
    ),
    (
        "M10 外推说成同集",
        LAUNCH,
        '"extrapolated_from_other_dataset" if batches else "no_live_batch"',
        '"same_dataset" if batches else "no_live_batch"',
    ),
    (
        "M11 吃读取类桶（不是管理员类）",
        ROUTER,
        "check_rate_limit(request, RateLimitBucket.ADMIN, ctx)",
        "check_rate_limit(request, RateLimitBucket.READ, ctx)",
    ),
    (
        "M12 去掉角色门禁",
        ROUTER,
        "        _require_platform_admin(token)\n        quota = await check_rate_limit(request, RateLimitBucket.ADMIN, ctx)",
        "        quota = await check_rate_limit(request, RateLimitBucket.ADMIN, ctx)",
    ),
    (
        "M13 不查评测集在位（→500）",
        ROUTER,
        "if body.dataset_id not in eval_report.dataset_ids():",
        "if False:",
    ),
    ("M14 dry_run 放开成 bool", DTO, "dry_run: Literal[True] = Field(", "dry_run: bool = Field("),
    ("M15 extra 放开成 ignore", DTO, 'model_config = ConfigDict(extra="forbid")', 'model_config = ConfigDict(extra="ignore")'),
]


def run_pytest() -> tuple[int, str]:
    proc = subprocess.run(
        [str(BACKEND.parent / ".venv" / "Scripts" / "python.exe"), "-m", "pytest", TEST, "-q", "-p", "no:cacheprovider"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    tail = (proc.stdout or "").splitlines()[-3:]
    return proc.returncode, " | ".join(tail)


def main() -> int:
    originals: dict[Path, bytes] = {}
    for path in {m[1] for m in MUTATIONS}:
        originals[path] = path.read_bytes()
    lines: list[str] = []
    unclosed = 0
    baseline_rc, baseline_tail = run_pytest()
    lines.append(f"baseline rc={baseline_rc} :: {baseline_tail}")
    if baseline_rc != 0:
        lines.append("!! 基线就红 ⇒ 变异全部作废，先修基线")
        print("\n".join(lines))
        return 2
    for name, path, old, new in MUTATIONS:
        text = originals[path].decode("utf-8")
        if text.count(old) != 1:
            lines.append(f"{name} :: 靶点不唯一（命中 {text.count(old)}）⇒ 变异未生效，不算闭合")
            unclosed += 1
            continue
        mutated = text.replace(old, new).encode("utf-8")
        path.write_bytes(mutated)
        try:
            rc, tail = run_pytest()
        finally:
            path.write_bytes(originals[path])
        closed = rc != 0
        unclosed += 0 if closed else 1
        lines.append(f"{name} :: rc={rc} {'翻红 ✓' if closed else '仍绿 ✗'} :: {tail}")
    restored = all(path.read_bytes() == data for path, data in originals.items())
    lines.append(f"还原后逐文件 md5 与进入前一致 = {restored}")
    for path, data in originals.items():
        lines.append(
            f"  {path.name}: {hashlib.md5(path.read_bytes()).hexdigest()} == {hashlib.md5(data).hexdigest()}"
        )
    lines.append(f"不闭合条数 = {unclosed}")
    out = "\n".join(lines)
    Path(__file__).with_name("t37_a3_mutations_report.txt").write_text(out, encoding="utf-8")
    print(out)
    return 0 if (unclosed == 0 and restored) else 1


if __name__ == "__main__":
    sys.exit(main())
