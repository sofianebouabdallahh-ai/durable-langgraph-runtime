"""Least-privilege group roles (R14.13).

The migrator (the role running this) owns the schema. Each component connects
as its own login user, a member of exactly one of these NOLOGIN group roles,
with only the privileges it needs. No passwords here: login users are created
by infrastructure (`runtime db provision-users`; a Kubernetes Job in phase 12).

LangGraph's checkpoint tables are created later by `runtime db upgrade`, which
also grants them to app_worker explicitly (explicit grants over broad default
privileges: every grant is visible in review).

Roles are cluster-wide and other databases may use them, so `downgrade` revokes
this database's grants but never drops the roles.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = ("app_api", "app_worker", "app_ingest", "app_sandboxd")

GRANTS: dict[str, list[str]] = {
    # API: creates runs and their first event, reads status/results, cancels,
    # flips the kill switch. Never deletes; never touches checkpoints or tools.
    "app_api": [
        "SELECT, INSERT, UPDATE ON runs, run_events, sessions, session_messages",
        "SELECT, INSERT ON agent_definitions",
        "SELECT ON run_results, subagent_invocations",
        "SELECT, UPDATE ON admin_state",
    ],
    # Worker: executes runs and writes everything a run produces. No DELETE, no DDL.
    "app_worker": [
        "SELECT, INSERT, UPDATE ON runs, run_events, run_results, tool_invocations, findings,"
        " session_messages, subagent_invocations",
        "SELECT, UPDATE ON sessions",
        "SELECT, INSERT ON agent_definitions",
        "SELECT ON admin_state, documents, chunks",
    ],
    # Ingest job (R4.5): owns the retrieval corpus, nothing else.
    "app_ingest": ["SELECT, INSERT, UPDATE, DELETE ON documents, chunks"],
    # sandboxd (CR-002 R13.5): only what GC and fencing need.
    "app_sandboxd": ["SELECT (id, status, epoch) ON runs"],
}


def upgrade() -> None:
    for role in ROLES:
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                    CREATE ROLE {role} NOLOGIN;
                END IF;
            END $$
        """)
    # Nobody gets anything by default; each role gets exactly what's listed.
    op.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {', '.join(ROLES)}")
    for role, grants in GRANTS.items():
        for grant in grants:
            op.execute(f"GRANT {grant} TO {role}")


def downgrade() -> None:
    for role in ROLES:
        op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}")
        op.execute(f"REVOKE USAGE ON SCHEMA public FROM {role}")
    op.execute("GRANT USAGE ON SCHEMA public TO PUBLIC")
