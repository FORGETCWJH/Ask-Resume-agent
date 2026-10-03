"""create the MVP schema in a fresh database"""

from alembic import op


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The declarative metadata is the single schema definition for this local MVP.
    # create_all is idempotent, which also lets an existing pre-Alembic database adopt migrations.
    from app import models  # noqa: F401
    from app.db import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts "
            "USING fts5(evidence_id UNINDEXED, content, source_path)"
        )


def downgrade() -> None:
    from app import models  # noqa: F401
    from app.db import Base

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("DROP TABLE IF EXISTS evidence_fts")
    Base.metadata.drop_all(bind=bind)
