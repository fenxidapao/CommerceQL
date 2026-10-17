"""绑定式匣带回放入口（W8 第 52 轮）。

问题：`runner.py` 默认环境里的 `DEEPSEEK_BASE_URL` / 模型名可能与录制时不同，
而匣带 key 覆盖“URL path + 请求体” ⇒ 同一个 prompt 也会因 base path 或 model
不同而 `cassette_miss`（第 51 轮 QA 实测）。

本入口只读匣带首行/响应里的非秘密字段，推导：
- URL path 对应的 base URL；
- 请求体实际使用的 model IDs；
然后把这三项注入环境，再原样转发给官方 `runner.py`。

用法：
    python eval/replay_bound.py --cases E-VER-07 --mode replay \
      --cassette eval/cassettes/w8_r52_stab_E-VER-07_1.jsonl \
      --out /tmp/result.json --provenance "..." --yes

它不读取 `deploy/.env`，不构造上游，也不在 replay 模式回退网络。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "runner.py"


def _base_url_for(path: str) -> str:
    """按录制报文 path 还原 base URL；未知 path 拒绝猜测。"""
    if path == "/v1/chat/completions":
        return "https://kuaipao.pro/v1"
    if path == "/chat/completions":
        return "https://api.deepseek.com"
    raise ValueError(f"无法从匣带 path={path!r} 推导 base URL")


def infer_replay_env(cassette_path: str | Path) -> dict[str, str]:
    """读取匣带中的 path/model，返回需要注入的环境变量。"""
    records: list[dict[str, Any]] = []
    with Path(cassette_path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    if not records:
        raise ValueError(f"匣带为空：{cassette_path}")
    paths = {str(record.get("path") or "") for record in records}
    if len(paths) != 1:
        raise ValueError(f"同一匣带混有多个 path，拒绝猜测：{sorted(paths)}")
    models = {
        str((record.get("request") or {}).get("model") or "")
        for record in records
        if (record.get("request") or {}).get("model")
    }
    if not models:
        raise ValueError(f"匣带没有任何请求 model：{cassette_path}")
    ordered = sorted(models)
    flash_candidates = [m for m in ordered if "flash" in m]
    pro_candidates = [m for m in ordered if "pro" in m]
    # 同时有 `deepseek-flash` 与带版本号的 flash 时，取更具体的那个。
    fast = max(flash_candidates, key=len) if flash_candidates else ordered[0]
    strong = max(pro_candidates, key=len) if pro_candidates else fast
    return {
        "DEEPSEEK_BASE_URL": _base_url_for(next(iter(paths))),
        "LLM_MODEL_FAST": fast,
        "LLM_MODEL_STRONG": strong,
    }


def _cassette_arg(argv: list[str]) -> str | None:
    for i, arg in enumerate(argv):
        if arg == "--cassette" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--cassette="):
            return arg.split("=", 1)[1]
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cassette = _cassette_arg(args)
    if cassette is None:
        print("replay_bound: 缺少 --cassette", file=sys.stderr)
        return 2
    binding = infer_replay_env(cassette)
    os.environ.update(binding)
    print(
        "replay_bound: "
        f"base_url={binding['DEEPSEEK_BASE_URL']} "
        f"fast={binding['LLM_MODEL_FAST']} strong={binding['LLM_MODEL_STRONG']}",
        flush=True,
    )
    return subprocess.call([sys.executable, str(RUNNER), *args], cwd=str(HERE.parent))


if __name__ == "__main__":
    raise SystemExit(main())
