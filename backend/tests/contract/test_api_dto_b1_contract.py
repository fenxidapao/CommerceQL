"""Phase B B1：新增 DTO 骨架的契约断言（零端点）。

钉三件事：
1. 会话列表字段与附录 A §A.5.4 **逐字**一致（多/少一个字段都算契约漂移）；
2. 注册/登录**不接受** `tenant_id`（客户端传租户 = 自助跨租户建号的入口）；
3. 资产详情**没有** `sensitive` / `denied_columns` 这类"哪里敏感"的字段。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.dto import auth, semantic_asset_detail, sessions

pytestmark = pytest.mark.contract


def test_session_summary_fields_match_a_5_4() -> None:
    assert set(sessions.SessionSummary.model_fields) == {
        "session_id",
        "title",
        "turn_count",
        "last_turn_at",
        "created_at",
        "last_bundle_version",
    }


def test_session_list_shell_matches_a_5_4() -> None:
    assert set(sessions.SessionListData.model_fields) == {
        "items",
        "total",
        "limit",
        "offset",
        "has_more",
    }
    assert set(sessions.CloseSessionData.model_fields) == {"session_id", "closed"}


def test_register_and_login_reject_client_supplied_tenant() -> None:
    with pytest.raises(ValidationError):
        auth.RegisterRequest(username="alice", password="correct-horse", tenant_id="T_B")
    with pytest.raises(ValidationError):
        auth.LoginRequest(username="alice", password="correct-horse", tenant_id="T_B")


def test_password_bounds_are_enforced() -> None:
    with pytest.raises(ValidationError):
        auth.RegisterRequest(username="alice", password="short")
    with pytest.raises(ValidationError):
        auth.RegisterRequest(username="alice", password="x" * 129)


def test_asset_detail_has_no_sensitive_or_denied_fields() -> None:
    fields = set(semantic_asset_detail.AssetDetailData.model_fields)
    column_fields = set(semantic_asset_detail.ColumnDetail.model_fields)
    for forbidden in ("sensitive", "denied_columns"):
        assert forbidden not in fields
        assert forbidden not in column_fields
