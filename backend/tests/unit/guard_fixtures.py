"""guard 测试夹具（W2C 所有，docs/08 §4.1 "随被测模块"）。

allowlist **直接从真语义包构建**（单一事实来源）——不手工抄一份列清单，
否则语义包演进时测试夹具会静默漂移（第二真相）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.core.contracts import IdentityContext
from app.core.enums import Role

#: backend/tests/unit/guard_fixtures.py → parents[2] = backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
BUNDLE_PATH = REPO_ROOT / "semantic" / "bundle_2026.09.14.1.yaml"
REDTEAM_PATH = REPO_ROOT / "eval" / "red_team_cases_v1.json"


def load_bundle_yaml() -> dict[str, Any]:

    return yaml.safe_load(open(BUNDLE_PATH, encoding="utf-8"))


def build_allowlist(bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    """把语义包 YAML 转成 guard 的 allowlist 输入形状（见 app/guard/ast_gate.py docstring）。

    ⚠️ 这是 W2A ``asset_allowlist(ctx)`` 的**预期形状** —— 对齐点已登记
    reports/w2c/RELAY.md；W2A 交付后本夹具应改为直接调其运行时。
    """

    b = bundle if bundle is not None else load_bundle_yaml()
    assets: dict[str, Any] = {}
    for a in b["assets"]:
        assets[a["physical_asset"]] = {
            "logical_name": a["logical_name"],
            "domain": a["domain"],
            "tenant_scoped": bool(a["tenant_scoped"]),
            "columns": {c["name"]: c["type"] for c in a["columns"]},
        }
    joins = [
        {
            "left": j["left"].split(".")[0],
            "right": j["right"].split(".")[0],
            "on_columns": list(j["on_columns"]),
        }
        for j in b["joins"]
    ]
    deny: list[str] = []
    for p in b["policies"]:
        deny.extend(p.get("deny_columns") or [])
    default_predicates = {
        domain: [p["predicate"] for p in preds]
        for domain, preds in b["default_predicates"].items()
    }
    return {
        "bundle_version": b["meta"]["version"],
        "assets": assets,
        "joins": joins,
        "deny_columns": deny,
        "default_predicates": default_predicates,
        # R14 第③类"语义包声明常量"：当前 bundle 无声明区 → 空（R14 口径见 ast_gate.py）
        "allowed_constants": [],
    }


class FakeSemanticBundle:
    """``SemanticBundlePort`` 的测试桩（形状见 app/core/contracts.py）。"""

    def __init__(self, allowlist: dict[str, Any], version: str | None = None) -> None:
        self._allowlist = allowlist
        self._version = version if version is not None else allowlist["bundle_version"]

    def active_version(self) -> str:
        return self._version

    def asset_allowlist(self, ctx: IdentityContext) -> dict[str, Any]:
        return self._allowlist

    def time_semantics(self):  # pragma: no cover - gate2 不消费
        raise NotImplementedError

    def policy(self) -> dict[str, Any]:
        return {"deny_columns": self._allowlist["deny_columns"]}


def make_ctx(
    *,
    role: Role = Role.ANALYST,
    tenant_id: str = "T_A",
    scope_claims: tuple[str, ...] = (),
    shop_ids: tuple[str, ...] = (),
) -> IdentityContext:
    return IdentityContext(
        trace_id="trace-test",
        task_id="task-test",
        session_id="session-test",
        tenant_id=tenant_id,
        user_id="user-test",
        role=role,
        scope_claims=scope_claims,
        shop_ids=shop_ids,
    )
