"""add resume recognition drafts and evidence links"""

from alembic import op
import sqlalchemy as sa


revision = "0002_resume_recognition"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 creates the current declarative schema for fresh databases. These guards
    # make adoption of databases initialized by the pre-Alembic app safe.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("resume_extraction_drafts"):
        op.create_table(
            "resume_extraction_drafts",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("material_id", sa.String(length=36), sa.ForeignKey("materials.id", ondelete="CASCADE"), nullable=False),
            sa.Column("revision_id", sa.String(length=36), sa.ForeignKey("material_revisions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("draft_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("warnings_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("confirmed_sections_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("extractor_version", sa.String(length=80), nullable=False, server_default="resume-v1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    inspector = sa.inspect(bind)
    existing_indexes = {item["name"] for item in inspector.get_indexes("resume_extraction_drafts")}
    if "ix_resume_extraction_drafts_material_id" not in existing_indexes:
        op.create_index("ix_resume_extraction_drafts_material_id", "resume_extraction_drafts", ["material_id"])
    if "ix_resume_extraction_drafts_revision_id" not in existing_indexes:
        op.create_index("ix_resume_extraction_drafts_revision_id", "resume_extraction_drafts", ["revision_id"])
    if not inspector.has_table("resume_evidence_links"):
        op.create_table(
            "resume_evidence_links",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("draft_id", sa.String(length=36), sa.ForeignKey("resume_extraction_drafts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("section", sa.String(length=40), nullable=False),
            sa.Column("field_path", sa.String(length=240), nullable=False),
            sa.Column("evidence_chunk_id", sa.String(length=36), sa.ForeignKey("evidence_chunks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("page_number", sa.Integer(), nullable=True),
            sa.Column("source_path", sa.String(length=1000), nullable=True),
            sa.Column("origin", sa.String(length=24), nullable=False, server_default="model"),
        )
    inspector = sa.inspect(bind)
    existing_indexes = {item["name"] for item in inspector.get_indexes("resume_evidence_links")}
    for name, column in (
        ("ix_resume_evidence_links_draft_id", "draft_id"),
        ("ix_resume_evidence_links_section", "section"),
        ("ix_resume_evidence_links_evidence_chunk_id", "evidence_chunk_id"),
    ):
        if name not in existing_indexes:
            op.create_index(name, "resume_evidence_links", [column])


def downgrade() -> None:
    op.drop_index("ix_resume_evidence_links_evidence_chunk_id", table_name="resume_evidence_links")
    op.drop_index("ix_resume_evidence_links_section", table_name="resume_evidence_links")
    op.drop_index("ix_resume_evidence_links_draft_id", table_name="resume_evidence_links")
    op.drop_table("resume_evidence_links")
    op.drop_index("ix_resume_extraction_drafts_revision_id", table_name="resume_extraction_drafts")
    op.drop_index("ix_resume_extraction_drafts_material_id", table_name="resume_extraction_drafts")
    op.drop_table("resume_extraction_drafts")
