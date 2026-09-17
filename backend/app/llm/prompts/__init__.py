"""版本化 prompt 资产目录（`{task}_v{n}.txt`，07 §10.3）。

本文件只做导出，业务逻辑在 `loader.py`。
"""

from __future__ import annotations

from app.llm.prompts.loader import (
    FORBIDDEN_PREFIX_VARS,
    PROMPTS_DIR,
    STABLE_PREFIX_VARS,
    PromptAsset,
    available_versions,
    load_prompt,
    prefix_hash,
    render_messages,
)

__all__ = [
    "PromptAsset",
    "load_prompt",
    "available_versions",
    "render_messages",
    "prefix_hash",
    "STABLE_PREFIX_VARS",
    "FORBIDDEN_PREFIX_VARS",
    "PROMPTS_DIR",
]
