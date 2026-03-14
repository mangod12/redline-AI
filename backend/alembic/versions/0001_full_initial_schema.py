"""Full initial schema for all 9 tables

Revision ID: 0001_full_initial_schema
Revises:
Create Date: 2026-03-13 00:00:00.000000
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_full_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------
    # 1. tenants  (no FK dependencies)
    # ------------------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------
    # 2. users  (FK -> tenants)
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "super_admin",
                "tenant_admin",
                "dispatcher",
                "viewer",
                name="user_role",
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------
    # 3. calls  (FK -> tenants)
    # ------------------------------------------------------------------
    op.create_table(
        "calls",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("caller_number", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "closed", name="call_status"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------
    # 4. transcripts  (FK -> calls)
    # ------------------------------------------------------------------
    op.create_table(
        "transcripts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "call_id",
            UUID(as_uuid=True),
            sa.ForeignKey("calls.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("original_text", sa.String(), nullable=False),
        sa.Column("translated_text", sa.String(), nullable=True),
        sa.Column("language", sa.String(), server_default="en", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------
    # 5. severity_reports  (FK -> calls)
    # ------------------------------------------------------------------
    op.create_table(
        "severity_reports",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "call_id",
            UUID(as_uuid=True),
            sa.ForeignKey("calls.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("severity_score", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("keywords_detected", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------
    # 6. analysis_results  (FK -> calls)
    # ------------------------------------------------------------------
    op.create_table(
        "analysis_results",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "call_id",
            UUID(as_uuid=True),
            sa.ForeignKey("calls.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("incident_type", sa.String(), nullable=False),
        sa.Column("panic_score", sa.Float(), nullable=False),
        sa.Column("keyword_score", sa.Float(), nullable=False),
        sa.Column("severity_prediction", sa.Integer(), nullable=True),
        sa.Column("location_text", sa.String(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("geo_confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------
    # 7. dispatch_recommendations  (FK -> calls)
    # ------------------------------------------------------------------
    op.create_table(
        "dispatch_recommendations",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "call_id",
            UUID(as_uuid=True),
            sa.ForeignKey("calls.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("unit_id", sa.String(), nullable=False),
        sa.Column("eta_minutes", sa.Float(), nullable=True),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------
    # 8. audit_logs  (FK -> tenants SET NULL, FK -> users SET NULL)
    # ------------------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=True),
        sa.Column("entity_type", sa.String(), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------
    # 9. emergency_calls  (standalone, no BaseModel)
    # ------------------------------------------------------------------
    op.create_table(
        "emergency_calls",
        sa.Column(
            "call_id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("caller_id", sa.String(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(), nullable=False),
        sa.Column("emotion", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("responder", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
    )


def downgrade():
    # Drop in reverse dependency order
    op.drop_table("emergency_calls")
    op.drop_table("audit_logs")
    op.drop_table("dispatch_recommendations")
    op.drop_table("analysis_results")
    op.drop_table("severity_reports")
    op.drop_table("transcripts")
    op.drop_table("calls")
    op.drop_table("users")
    op.drop_table("tenants")

    # Drop enums created by upgrade
    op.execute("DROP TYPE IF EXISTS user_role")
    op.execute("DROP TYPE IF EXISTS call_status")
