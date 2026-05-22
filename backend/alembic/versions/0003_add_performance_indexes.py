"""Add performance indexes for common query patterns

Revision ID: 0003_add_performance_indexes
Revises: 0002_add_emergency_calls_and_audit_logs
Create Date: 2026-05-22 00:00:01.000000
"""
from alembic import op

revision = '0003_add_performance_indexes'
down_revision = '0002_add_emergency_calls_and_audit_logs'
branch_labels = None
depends_on = None


def upgrade():
    # Composite index for tenant-scoped time-range queries on emergency_calls
    op.create_index(
        'ix_emergency_calls_tenant_created',
        'emergency_calls',
        ['tenant_id', 'created_at'],
    )

    # Index for severity filtering (dispatchers filter by critical/high)
    op.create_index(
        'ix_emergency_calls_severity',
        'emergency_calls',
        ['severity'],
    )

    # Composite index for call listing with tenant isolation
    op.create_index(
        'ix_calls_tenant_created',
        'calls',
        ['tenant_id', 'created_at'],
    )

    # Index for transcript search by call
    op.create_index(
        'ix_transcripts_call_created',
        'transcripts',
        ['call_id', 'created_at'],
    )


def downgrade():
    op.drop_index('ix_transcripts_call_created')
    op.drop_index('ix_calls_tenant_created')
    op.drop_index('ix_emergency_calls_severity')
    op.drop_index('ix_emergency_calls_tenant_created')
