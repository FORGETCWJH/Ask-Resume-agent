"""persist answer versions, feedback and follow-up parent links"""

from alembic import op
import sqlalchemy as sa


revision = "0005_agent_final_practice"
down_revision = "0004_clean_compact_resume_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "practice_turns" in tables:
        turn_columns = {column["name"] for column in inspector.get_columns("practice_turns")}
        if "parent_turn_id" not in turn_columns:
            with op.batch_alter_table("practice_turns") as batch:
                batch.add_column(sa.Column("parent_turn_id", sa.String(length=36), nullable=True))
                batch.create_index("ix_practice_turns_parent_turn_id", ["parent_turn_id"], unique=False)
                batch.create_foreign_key("fk_practice_turns_parent_turn_id", "practice_turns", ["parent_turn_id"], ["id"], ondelete="CASCADE")
    if "practice_answers" not in tables:
        op.create_table("practice_answers", sa.Column("id", sa.String(length=36), primary_key=True), sa.Column("turn_id", sa.String(length=36), sa.ForeignKey("practice_turns.id", ondelete="CASCADE"), nullable=False), sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.Column("content", sa.Text(), nullable=False), sa.Column("fingerprint", sa.String(length=64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index("ix_practice_answers_turn_id", "practice_answers", ["turn_id"])
        op.create_index("ix_practice_answers_fingerprint", "practice_answers", ["fingerprint"])
    if "practice_feedback" not in tables:
        op.create_table("practice_feedback", sa.Column("id", sa.String(length=36), primary_key=True), sa.Column("turn_id", sa.String(length=36), sa.ForeignKey("practice_turns.id", ondelete="CASCADE"), nullable=False), sa.Column("answer_id", sa.String(length=36), sa.ForeignKey("practice_answers.id", ondelete="CASCADE"), nullable=False), sa.Column("prompt_version", sa.String(length=40), nullable=False, server_default="feedback-v1"), sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index("ix_practice_feedback_turn_id", "practice_feedback", ["turn_id"])
        op.create_index("ix_practice_feedback_answer_id", "practice_feedback", ["answer_id"])
    if "reference_answers" in tables:
        reference_columns = {column["name"] for column in inspector.get_columns("reference_answers")}
        with op.batch_alter_table("reference_answers") as batch:
            if "question_version_id" not in reference_columns:
                batch.add_column(sa.Column("question_version_id", sa.String(length=36), nullable=True))
                batch.create_index("ix_reference_answers_question_version_id", ["question_version_id"], unique=False)
                batch.create_foreign_key("fk_reference_answers_question_version_id", "question_versions", ["question_version_id"], ["id"], ondelete="CASCADE")
            if "prompt_version" not in reference_columns:
                batch.add_column(sa.Column("prompt_version", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("reference_answers") as batch:
        batch.drop_constraint("fk_reference_answers_question_version_id", type_="foreignkey")
        batch.drop_index("ix_reference_answers_question_version_id")
        batch.drop_column("prompt_version")
        batch.drop_column("question_version_id")
    op.drop_index("ix_practice_feedback_answer_id", table_name="practice_feedback")
    op.drop_index("ix_practice_feedback_turn_id", table_name="practice_feedback")
    op.drop_table("practice_feedback")
    op.drop_index("ix_practice_answers_fingerprint", table_name="practice_answers")
    op.drop_index("ix_practice_answers_turn_id", table_name="practice_answers")
    op.drop_table("practice_answers")
    with op.batch_alter_table("practice_turns") as batch:
        batch.drop_constraint("fk_practice_turns_parent_turn_id", type_="foreignkey")
        batch.drop_index("ix_practice_turns_parent_turn_id")
        batch.drop_column("parent_turn_id")
