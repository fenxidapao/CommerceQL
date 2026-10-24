"""W77-4：b2 匣带卫生 manifest（**不改写匣带**；只登记脏键并禁作证据）。

背景（QA §98.3）：b2 匣带 138 个唯一键，而干净重跑 29 条只有 115 个唯一键。
`CassetteTransport.save()` 按 key 与磁盘旧记录合并 ⇒ 23 个脏树批次的残余键留在文件里。
干净结果 JSON（`results_w76_tau_b2.json`，`git_rev=00260ef` / `dirty=False`）可用，
但**匣带本身不是清洁证据**（D-W77-6）。

本脚本以「干净批次重放产生的调用键」为基准，算出脏键差集，落 manifest：
* `clean_keys` = 干净重放实际命中的唯一键（应为 115）；
* `dirty_keys` = 匣带唯一键 − clean_keys（应为 23）；
* `usable_as_clean_evidence = false`，并写明重放/重建前不得引用。
b1/b3 一律不碰；b2 文件本身也不改写（只读 + 统计 sha256）。

跑法：
    python eval/w77_b2_manifest.py --calls <干净重放的 calls manifest>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CASSETTE = os.path.join(HERE, "cassettes", "w76_tau_b2.jsonl")
OUT = os.path.join(HERE, "cassettes", "w76_tau_b2.manifest.json")
CLEAN_RESULT = os.path.join(HERE, "results_w76_tau_b2.json")
EXPECTED_CLEAN = 115
EXPECTED_DIRTY = 23


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _relative(path: str) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="b2 匣带脏键 manifest")
    parser.add_argument("--cassette", default=CASSETTE)
    parser.add_argument("--calls", required=True, help="/calls manifest（干净重放产出的调用键）")
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args(argv)

    cassette_keys: list[str] = []
    with open(args.cassette, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                cassette_keys.append(json.loads(line)["key"])
    unique_keys = sorted(set(cassette_keys))

    calls_payload = _load(args.calls)
    clean_keys = sorted(set(calls_payload.get("unique") or []))
    dirty_keys = sorted(set(unique_keys) - set(clean_keys))
    missing_from_cassette = sorted(set(clean_keys) - set(unique_keys))

    clean_result = _load(CLEAN_RESULT)
    result_config = clean_result.get("config") or {}

    payload = {
        "schema": "W77_B2_CASSETTE_MANIFEST/v1",
        "cassette": {
            "path": _relative(args.cassette),
            "sha256": _sha256(args.cassette),
            "unique_keys": len(unique_keys),
            "duplicate_lines": len(cassette_keys) - len(unique_keys),
            "rewritten": False,
        },
        "clean_basis": {
            "calls_manifest": _relative(args.calls),
            "calls_manifest_git_rev": calls_payload.get("git_rev"),
            "calls_manifest_git_dirty": calls_payload.get("git_dirty"),
            "live": calls_payload.get("live"),
            "mode": calls_payload.get("mode"),
            "n_calls": calls_payload.get("n_calls"),
            "n_unique": calls_payload.get("n_unique"),
        },
        "clean_keys": clean_keys,
        "dirty_keys": dirty_keys,
        "n_clean_keys": len(clean_keys),
        "n_dirty_keys": len(dirty_keys),
        "clean_shape_holds": len(clean_keys) == EXPECTED_CLEAN,
        "dirty_count_holds": len(dirty_keys) == EXPECTED_DIRTY,
        "clean_keys_missing_from_cassette": missing_from_cassette,
        "usable_as_clean_evidence": False,
        "reason": (
            "b2 匣带混入了脏树批次的残余键（D-W77-6）。干净结果 JSON 可用；"
            "匣带在按 clean_keys 重建前不得作为清洁证据引用"
        ),
        "clean_result_json": {
            "path": _relative(CLEAN_RESULT),
            "git_rev": clean_result.get("git_rev"),
            "git_dirty": clean_result.get("git_dirty"),
            "n_records": len(clean_result.get("records") or []),
            "live": result_config.get("live"),
            "mode": result_config.get("mode"),
            "batch_id": result_config.get("batch_id"),
        },
        "b1_b3_untouched": True,
        "rebuild_note": (
            "如需可作证据的 b2 匣带：仅保留 clean_keys 对应行写入新文件，"
            "并把新文件 sha256 与本 manifest 的 clean_keys 长度一起复核；不要原地改写 b1/b3"
        ),
    }
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"written: {_relative(args.out)}")
    print(
        f"cassette_unique={len(unique_keys)} clean={len(clean_keys)} "
        f"dirty={len(dirty_keys)} missing_clean={len(missing_from_cassette)}"
    )
    print(f"dirty_keys={dirty_keys}")
    return 0 if (not missing_from_cassette and len(clean_keys) == EXPECTED_CLEAN
                 and len(dirty_keys) == EXPECTED_DIRTY) else 1


if __name__ == "__main__":
    raise SystemExit(main())
