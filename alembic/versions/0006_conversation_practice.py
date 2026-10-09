"""对话式练习消息、记忆、事实快照和显式偏好。"""
from alembic import op
import sqlalchemy as sa

revision = "0006_conversation_practice"
down_revision = "0005_agent_final_practice"
branch_labels = depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    cid = lambda: sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    identity = lambda: sa.Column("id", sa.String(36), primary_key=True)
    text = lambda name, default="{}": sa.Column(name, sa.Text(), nullable=False, server_default=default)
    time = lambda name: sa.Column(name, sa.DateTime(timezone=True), nullable=False)
    tables = {
        "conversation_practice_states": [sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True), text("snapshot_json"), text("state_json"), sa.Column("busy_input_id", sa.String(36))],
        "practice_events": [identity(), cid(), sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("role", sa.String(20), nullable=False), sa.Column("message_type", sa.String(32), nullable=False), text("content", ""), text("data_json"), time("created_at"), sa.UniqueConstraint("conversation_id", "sequence")],
        "practice_inputs": [identity(), cid(), sa.Column("client_request_id", sa.String(80), nullable=False), text("content", ""), sa.Column("run_id", sa.String(36)), text("snapshot_json"), text("steps_json"), sa.UniqueConstraint("conversation_id", "client_request_id")],
        "practice_preferences": [identity(), sa.Column("key", sa.String(40), nullable=False, unique=True), text("value_json"), sa.Column("revision", sa.Integer(), nullable=False, server_default="1"), sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()), time("created_at"), time("updated_at")],
        "practice_preference_sources": [identity(), sa.Column("preference_id", sa.String(36), sa.ForeignKey("practice_preferences.id", ondelete="CASCADE"), nullable=False), cid(), text("original_instruction", ""), sa.UniqueConstraint("preference_id", "conversation_id")],
    }
    for name, columns in tables.items():
        if name not in existing:
            op.create_table(name, *columns)
            if name not in {"conversation_practice_states", "practice_preferences"}:
                op.create_index(f"ix_{name}_conversation_id", name, ["conversation_id"])
            if name == "practice_preference_sources":
                op.create_index("ix_practice_preference_sources_preference_id", name, ["preference_id"])


def downgrade():
    for name in ["practice_preference_sources", "practice_preferences", "practice_inputs", "practice_events", "conversation_practice_states"]:
        op.drop_table(name)
