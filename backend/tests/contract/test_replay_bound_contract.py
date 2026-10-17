"""绑定式回放入口的零出站契约（W8 第 52 轮）。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO / "eval" / "replay_bound.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("w8_replay_bound", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_cassette(path: Path, *, endpoint: str, models: list[str]) -> None:
    lines = []
    for model in models:
        lines.append(
            json.dumps(
                {
                    "key": f"sha256:{model}",
                    "path": endpoint,
                    "request": {"model": model},
                    "status": 200,
                    "response": {"choices": []},
                }
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_infers_base_url_and_model_ids_from_cassette(tmp_path: Path) -> None:
    cassette = tmp_path / "bound.jsonl"
    _write_cassette(
        cassette,
        endpoint="/v1/chat/completions",
        models=["deepseek-flash", "deepseek-v4.1-flash"],
    )
    bound = _load_module().infer_replay_env(cassette)
    assert bound == {
        "DEEPSEEK_BASE_URL": "https://kuaipao.pro/v1",
        "LLM_MODEL_FAST": "deepseek-v4.1-flash",
        "LLM_MODEL_STRONG": "deepseek-v4.1-flash",
    }


def test_rejects_unknown_endpoint(tmp_path: Path) -> None:
    cassette = tmp_path / "unknown.jsonl"
    _write_cassette(cassette, endpoint="/custom/chat", models=["m"])
    with pytest.raises(ValueError, match="无法从匣带 path"):
        _load_module().infer_replay_env(cassette)


def test_rejects_mixed_endpoints(tmp_path: Path) -> None:
    cassette = tmp_path / "mixed.jsonl"
    _write_cassette(cassette, endpoint="/v1/chat/completions", models=["m"])
    with cassette.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"path": "/chat/completions", "request": {"model": "m"}}) + "\n")
    with pytest.raises(ValueError, match="多个 path"):
        _load_module().infer_replay_env(cassette)
