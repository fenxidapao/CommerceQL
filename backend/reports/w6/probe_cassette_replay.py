"""匣带**可复算性**探针（§C.6.1 纪律二的成立条件；不是批次读数）。

同一批 20 题（`smoke_batch_ids.json` 的确定性选题）在 `--mode replay` 下重放一遍，
只回答一个问题：**报告里那些回放读数今天还能不能零成本重算**。

为什么需要它（实测来由）：09-21 发现 `eval/cassettes/w6_batch.jsonl` 的 48 个报文指纹
对今天的出站报文 **20/20 全 miss** —— 上游 `fbae176`（W2A）把 `metrics()/aliases()` 枚举器
接进语义摘要，system 段多出一整块 `## 指标口径`（首条 6,401 → 11,343 字符）。
匣带按 `path + 报文指纹` 命中 ⇒ prompt 一变整批失效，而"失效"这件事本身**没人报**，
下一轮就会以为 `--mode replay` 随时可用。⇒ 把命中率变成一个有产物的读数。

跑法（CommerceQL 根目录）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/probe_cassette_replay.py
产物：同目录 `cassette_replay_probe.json`（由 `eval/runner.py` 落盘；本窗口只搬运）。
⚠️ 探针**不出网**：`--mode replay` 下 `CassetteTransport` 不构造 upstream（结构上不可能偷偷真打）。
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # reports/w6 → backend → 仓库根
sys.path.insert(0, os.path.join(ROOT, "eval"))

import runner  # noqa: E402  # 导入即完成 _bootstrap 的环境与 sys.path 装配

OUT = os.path.join(HERE, "cassette_replay_probe.json")
PROVENANCE = (
    "匣带可复算性探针（**不是**批次读数）：同一批 20 题重放旧匣带，只测命中率；"
    "批次读数请看 eval/results_v1.json 与 reports/w6/results_w6_live20.json"
)


def main() -> int:
    with open(os.path.join(HERE, "smoke_batch_ids.json"), encoding="utf-8") as fh:
        ids = json.load(fh)["case_ids"]
    rc = runner.main([
        "--mode", "replay", "--yes", "--cases", ",".join(ids),
        "--out", OUT, "--provenance", PROVENANCE,
    ])
    if not os.path.exists(OUT):
        print("[FAIL] 探针没产出产物 ⇒ 不可复算性无法判定（不得据此声称纪律二成立）", file=sys.stderr)
        return rc or 1
    with open(OUT, encoding="utf-8") as fh:
        probe = json.load(fh)
    recs = list(probe.get("records") or [])
    miss = sum(1 for r in recs if "cassette_miss" in str(r.get("infra_error") or ""))
    print(f"[OK] 匣带命中率读数：{len(recs) - miss}/{len(recs)} 命中，miss={miss}"
          f" ⇒ 产物 {os.path.relpath(OUT, ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
