"""W7 量具变异检查（U-120 / A-1）：**退回旧行为必须红**，否则守卫是装饰。

跑法（CommerceQL 根）：
    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 .venv/Scripts/python.exe \
      backend/reports/w7/scratch_g6_mutation_check.py

三条自设规矩（都烧过时间，写在代码里防再犯）：
  ① 先跑**未注入的基线**，基线不绿就整轮判"无法判定"——否则"全都红"可能只是脚本坏了；
  ② 每处变异必须**断言替换真的发生了**（按精确串替换、替换次数不匹配即判该条无效）；
  ③ 变异只写在临时目录的副本上，**绝不回写 `deploy/loadtest/driver.py`**。

退出码：0 = 全部变异被抓；1 = 有变异逃跑（守卫分离力不足）；2 = 基线不绿，本轮不可判。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

DRIVER = os.path.join("deploy", "loadtest", "driver.py")

#: (名字, 原串, 变异串, 这条防的是什么)
MUTATIONS: list[tuple[str, str, str, str]] = [
    ("M1 退回无条件布尔",
     '"g6_p95_le_8s": _g6_boolean(p95_total, admission),',
     '"g6_p95_le_8s": (p95_total is not None and p95_total <= 8000.0),',
     "U-120 主病灶：admitted=5 也给出可被引用的布尔"),
    ("M2 去掉「没有 p95」这一支",
     "    if p95_ms is None or not admission:\n        return None",
     "    if not admission:\n        return None",
     "架构补充①：没有数被写成 false = 「不达标」的假话"),
    ("M3 去掉准入样本门槛",
     "    if admission.get(\"admitted\", 0) < MIN_ADMITTED_FOR_P95:\n        return None",
     "    pass",
     "07 §16.5「准入 < 20 不出 P95」"),
    ("M4 把门槛常量改成 1",
     "MIN_ADMITTED_FOR_P95: Final[int] = 20",
     "MIN_ADMITTED_FOR_P95: Final[int] = 1",
     "常量与判定点脱钩（值改了判据还在假装）"),
    ("M5 roll-up 只算 caveat 不算布尔",
     "    new_bool = _g6_boolean((s.get(\"latency_ms\") or {}).get(\"p95\"), admission)",
     "    new_bool = s.get(\"g6_p95_le_8s\")",
     "A-1：历史件的 stale true 不降档，改了新写端旧件继续被引用"),
    ("M6 roll-up 越界改读数",
     "    s[\"g6_caveat\"], s[\"g6_p95_le_8s\"] = new_caveat, new_bool",
     "    s[\"g6_caveat\"], s[\"g6_p95_le_8s\"] = new_caveat, new_bool\n"
     "    s[\"admission\"] = None",
     "「只动派生量」这条边界没有守卫"),
]


def _run_self_check(driver_path: str) -> int:
    proc = subprocess.run([sys.executable, driver_path, "--self-check"],
                          capture_output=True, text=True, encoding="utf-8",
                          cwd=os.path.dirname(driver_path) or ".", env={**os.environ,
                          "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    return int(proc.returncode)


def main() -> int:
    src = Path(DRIVER).read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        base = os.path.join(td, "driver.py")
        Path(base).write_text(src, encoding="utf-8")
        if _run_self_check(base) != 0:
            print(json.dumps({"verdict": "无法判定",
                              "why": "未注入的基线 --self-check 就不绿，后面所有红都不能归因给变异"},
                             ensure_ascii=False))
            return 2
        results: list[dict[str, object]] = []
        for name, old, new, prevents in MUTATIONS:
            hit = src.count(old)
            mutated_dir = os.path.join(td, f"m{len(results)}")
            os.makedirs(mutated_dir, exist_ok=True)
            mutated = os.path.join(mutated_dir, "driver.py")
            if hit != 1:
                results.append({"mutation": name, "injected": False, "anchor_hits": hit,
                                "self_check_exit": None, "caught": False})
                continue
            Path(mutated).write_text(src.replace(old, new, 1), encoding="utf-8")
            code = _run_self_check(mutated)
            results.append({"mutation": name, "injected": True, "anchor_hits": hit,
                            "self_check_exit": code, "caught": code != 0, "prevents": prevents})
        escaped = [r["mutation"] for r in results if not r.get("caught")]
        print(json.dumps({"baseline_green": True, "mutations": len(results),
                          "caught": len(results) - len(escaped), "escaped": escaped,
                          "detail": results}, ensure_ascii=False, indent=1))
        return 1 if escaped else 0


if __name__ == "__main__":
    sys.exit(main())
