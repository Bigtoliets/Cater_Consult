"""reviews 表新增 label_source / dimension_detail —— 区分词典粗判与 Agent 精判

前置节点只做召回（词典打标，Dashboard 即时可见），
Agent 深度加工后回写高精度标签并覆盖 dimensions/risk_level。

Revision ID: 0001_review_label_source
Revises:
Create Date: 2026-09-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_review_label_source"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column(
            "label_source", sa.String(10), nullable=True,
            comment="标签来源：dict=前置节点词典粗判 / llm=Agent 精判（回写覆盖）",
        ),
    )
    op.add_column(
        "reviews",
        sa.Column(
            "dimension_detail", sa.JSON(), nullable=True,
            comment="Agent 精判的结构化维度 [{dimension,severity,count,evidence}]，前置节点不写",
        ),
    )
    # 存量数据：已有 dimensions 的都是词典产物
    op.execute("UPDATE reviews SET label_source = 'dict' WHERE label_source IS NULL")


def downgrade() -> None:
    op.drop_column("reviews", "dimension_detail")
    op.drop_column("reviews", "label_source")
