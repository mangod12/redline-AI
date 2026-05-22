"""Add emergency_calls and audit_logs tables

Revision ID: 0002_add_emergency_calls_and_audit_logs
Revises: 0001_add_analysis_and_dispatch_tables
Create Date: 2026-05-22 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '0002_add_emergency_calls_and_audit_logs'
down_revision = '0001_add_analysis_and_dispatch_tables'
branch_labels = None
depends_on = None


def upgrade():
    # emergency_calls — main pipeline output table
    op.create_table(
        'emergency_calls',
        sa.Column('call_id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('caller_id', sa.String(255), nullable=True, index=True),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('transcript', sa.Text(), nullable=False),
        sa.Column('intent', sa.String(64), nullable=False, server_default='unknown'),
        sa.Column('emotion', sa.String(64), nullable=False, server_default='neutral'),
        sa.Column('severity', sa.String(16), nullable=False, server_default='low'),
        sa.Column('responder', sa.String(64), nullable=False, server_default='general'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        sa.Column('latency_ms', sa.Integer(), nullable=False, server_default='0'),
    )

    # audit_logs — security audit trail
    op.create_table(
        'audit_logs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action', sa.String(), nullable=False, index=True),
        sa.Column('entity_id', sa.String(), nullable=True),
        sa.Column('entity_type', sa.String(), nullable=True),
        sa.Column('details', JSONB(), server_default='{}', nullable=False),
    )

    # Index for audit log queries
    op.create_index('ix_audit_logs_action_created', 'audit_logs', ['action', 'created_at'])


def downgrade():
    op.drop_index('ix_audit_logs_action_created')
    op.drop_table('audit_logs')
    op.drop_table('emergency_calls')
