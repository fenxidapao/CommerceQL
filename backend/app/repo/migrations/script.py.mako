"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

⚠️ 07 §12.6：**只写 up，不写 down**。`downgrade()` 保留为空实现（alembic 的接口要求），
但**不得**在其中写任何真实回滚逻辑 —— 生产回滚靠"向后兼容发布"，不靠 downgrade。
"""

from __future__ import annotations

from alembic import op

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    # 07 §12.6：刻意留空。见模块文档字符串。
    pass
