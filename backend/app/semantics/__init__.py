"""CommerceQL 后端包：语义层运行时：语义包校验 / 物化 / 版本固定 / policy。

层号：L1｜归属窗口：W2A（docs/08 §4.1 文件归属权表）

公开面（阶段 2A 起收口；下游只 import 这些名字，不 import 内部模块）：
- `load_bundle` / `LoadedBundle` —— 五步校验（07 §6.1）
- `SemanticBundleRuntime` —— `SemanticBundlePort` 实现 + L1/L2/L3 查找面
- `build_semantic_bundle_probe` —— `semantic_bundle_loaded` 探针（注册归 W1B 组装根）
- `validate_bundle_path` —— 启动断言注入物（`repo/startup_assertions` 插槽形态）
"""

from app.semantics.loader import LoadedBundle, load_bundle, validate_bundle_path
from app.semantics.probe import build_semantic_bundle_probe
from app.semantics.runtime import SemanticBundleRuntime

__all__ = [
    "LoadedBundle",
    "SemanticBundleRuntime",
    "build_semantic_bundle_probe",
    "load_bundle",
    "validate_bundle_path",
]
