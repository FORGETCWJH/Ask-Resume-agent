"""对话置顶、分组、归档和活动时间。"""

from alembic import op
import sqlalchemy as sa


revision = "0007_conversation_history"
down_revision = "0006_conversation_practice"
branch_labels = depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "conversation_groups" not in tables:
        op.create_table(
            "conversation_groups",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("material_set_id", sa.String(36), sa.ForeignKey("material_sets.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("normalized_name", sa.String(80), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("material_set_id", "normalized_name", name="uq_conversation_group_set_name"),
        )
        op.create_index("ix_conversation_groups_material_set_id", "conversation_groups", ["material_set_id"])

    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("conversations")}
    if "group_id" not in columns:
        with op.batch_alter_table("conversations") as batch:
            batch.add_column(sa.Column("group_id", sa.String(36), nullable=True))
            batch.create_foreign_key("fk_conversations_group_id", "conversation_groups", ["group_id"], ["id"], ondelete="SET NULL")
            batch.create_index("ix_conversations_group_id", ["group_id"])
    if "pinned_at" not in columns:
        op.add_column("conversations", sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True))
    if "archived_at" not in columns:
        op.add_column("conversations", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    if "last_activity_at" not in columns:
        op.add_column("conversations", sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True))
        op.execute("UPDATE conversations SET last_activity_at = updated_at WHERE last_activity_at IS NULL")
        with op.batch_alter_table("conversations") as batch:
            batch.alter_column("last_activity_at", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.drop_index("ix_conversations_group_id")
        batch.drop_constraint("fk_conversations_group_id", type_="foreignkey")
        batch.drop_column("last_activity_at")
        batch.drop_column("archived_at")
        batch.drop_column("pinned_at")
        batch.drop_column("group_id")
    op.drop_index("ix_conversation_groups_material_set_id", table_name="conversation_groups")
    op.drop_table("conversation_groups")
