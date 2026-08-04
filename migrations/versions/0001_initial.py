"""Initial schema: banks, documents, chunks, conversations, messages,
handoffs, audit_log.

Revision ID: 0001
Revises:
Create Date: 2026-08-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "banks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("primary_color", sa.String(16), nullable=False),
        sa.Column("default_language", sa.String(8), nullable=False),
        sa.Column("admin_token", sa.String(64), nullable=False),
        sa.Column("telegram_bot_token", sa.String(128), nullable=True),
        sa.Column("telegram_webhook_secret", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_banks_slug", "banks", ["slug"], unique=True)

    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("bank_id", sa.String(36), sa.ForeignKey("banks.id"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_documents_bank_id", "documents", ["bank_id"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("bank_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_index("ix_chunks_bank_id", "chunks", ["bank_id"])
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("bank_id", sa.String(36), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("external_user_id", sa.String(64), nullable=True),
        sa.Column("language", sa.String(8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_conversations_bank_id", "conversations", ["bank_id"])
    op.create_index("ix_conversations_external_user_id", "conversations", ["external_user_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=False
        ),
        sa.Column("bank_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(32), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_bank_id", "messages", ["bank_id"])

    op.create_table(
        "handoffs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("bank_id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_handoffs_bank_id", "handoffs", ["bank_id"])
    op.create_index("ix_handoffs_conversation_id", "handoffs", ["conversation_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("bank_id", sa.String(36), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_bank_id", "audit_log", ["bank_id"])


def downgrade() -> None:
    for table in ("audit_log", "handoffs", "messages", "conversations", "chunks", "documents"):
        op.drop_table(table)
    op.drop_table("banks")
