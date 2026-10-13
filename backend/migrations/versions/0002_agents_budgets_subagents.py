"""Agent definitions, run budgets, kill switch, sub-agent invocations.

Sources: CR-003 (R14.1 budgets, R14.6 depth, R14.18 kill switch),
CR-004 (R15.4 definition snapshots, run kinds, session hooks),
CR-005 (R16.3 sub-agent invocations).

Additive only (expand step of expand/contract, R10.6): every new column is
nullable or has a default, so code from the previous release keeps working
while a rolling upgrade is in progress.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------- agent_definitions (CR-004 R15.4)
    # Immutable, content-addressed snapshots. A run executes the snapshot it was
    # created with, even if the .md file changes during a rolling upgrade.
    op.execute("""
        CREATE TABLE agent_definitions (
            hash        text PRIMARY KEY CHECK (length(hash) = 64),  -- sha256 of canonical content
            name        text        NOT NULL,       -- 'chat' or, for sub-agents, 'chat/researcher'
            version     integer     NOT NULL CHECK (version > 0),
            kind        text        NOT NULL CHECK (kind IN ('main', 'sub')),
            content     jsonb       NOT NULL,       -- resolved frontmatter + prompt body
            created_at  timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_agent_definitions_name ON agent_definitions (name, version)")

    # ------------------------------------------------------------- runs additions
    op.execute("""
        ALTER TABLE runs
            ADD COLUMN kind text NOT NULL DEFAULT 'workflow'
                CHECK (kind IN ('turn', 'workflow', 'child', 'session_end')),
            ADD COLUMN agent_name    text,
            ADD COLUMN agent_version integer,
            ADD COLUMN agent_hash    text REFERENCES agent_definitions (hash),

            -- effective limits, resolved once at creation: ceilings ∩ profile ∩ options (R14.3)
            ADD COLUMN limits jsonb NOT NULL DEFAULT '{}',

            -- durable usage counters (R14.1); they survive reclaim, never reset
            ADD COLUMN steps            integer NOT NULL DEFAULT 0 CHECK (steps >= 0),
            ADD COLUMN model_calls      integer NOT NULL DEFAULT 0 CHECK (model_calls >= 0),
            ADD COLUMN tool_calls_total integer NOT NULL DEFAULT 0 CHECK (tool_calls_total >= 0),
            ADD COLUMN tool_calls       jsonb   NOT NULL DEFAULT '{}',  -- per-tool counts

            -- fan-out position (R2.8, R14.6)
            ADD COLUMN depth       smallint NOT NULL DEFAULT 0 CHECK (depth >= 0),
            ADD COLUMN root_run_id uuid REFERENCES runs (id)
    """)
    op.execute("CREATE INDEX ix_runs_root ON runs (root_run_id) WHERE root_run_id IS NOT NULL")
    op.execute("""
        CREATE INDEX ix_runs_session ON runs (session_id, created_at)
        WHERE session_id IS NOT NULL
    """)

    # --------------------------------------------------------- sessions additions
    op.execute("""
        ALTER TABLE sessions
            ADD COLUMN agent_name text,
            ADD COLUMN summary    text,          -- written by the session_end hook
            ADD COLUMN ended_at   timestamptz
    """)
    # Idle-session archiving (R15.6) scans active sessions by last activity.
    op.execute("""
        CREATE INDEX ix_sessions_active_idle ON sessions (last_activity_at)
        WHERE status = 'active'
    """)

    # -------------------------------------------------- admin_state (R14.18)
    # Single-row table: the CHECK on a constant primary key makes a second row impossible.
    op.execute("""
        CREATE TABLE admin_state (
            id          boolean PRIMARY KEY DEFAULT true CHECK (id),
            paused      boolean     NOT NULL DEFAULT false,
            reason      text,
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("INSERT INTO admin_state (id) VALUES (true)")

    # ------------------------------------- subagent_invocations (CR-005 R16.3)
    op.execute("""
        CREATE TABLE subagent_invocations (
            handle      uuid PRIMARY KEY,
            run_id      uuid        NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
            agent       text        NOT NULL,            -- 'chat/researcher'
            task        text        NOT NULL,
            context     text,
            status      text        NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running', 'completed', 'failed',
                                          'cancelled', 'timed_out')),
            progress    jsonb       NOT NULL DEFAULT '{}',  -- {message, percent, updates}
            result      jsonb,                           -- {status, summary, result}
            usage       jsonb       NOT NULL DEFAULT '{}',
            thread_id   text        NOT NULL UNIQUE,     -- '<run_id>/sub/<handle>'
            epoch       bigint      NOT NULL,
            -- spawning is idempotent: replaying the spawn tool call finds this row
            spawned_by_tool_call_id text NOT NULL UNIQUE,
            created_at  timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            CONSTRAINT finished_iff_terminal
                CHECK ((finished_at IS NOT NULL) = (status <> 'running'))
        )
    """)
    op.execute("""
        CREATE INDEX ix_subagent_invocations_running ON subagent_invocations (run_id)
        WHERE status = 'running'
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS subagent_invocations")
    op.execute("DROP TABLE IF EXISTS admin_state")
    op.execute("DROP INDEX IF EXISTS ix_sessions_active_idle")
    op.execute("""
        ALTER TABLE sessions DROP COLUMN ended_at, DROP COLUMN summary, DROP COLUMN agent_name
    """)
    op.execute("DROP INDEX IF EXISTS ix_runs_session")
    op.execute("DROP INDEX IF EXISTS ix_runs_root")
    op.execute("""
        ALTER TABLE runs
            DROP COLUMN root_run_id, DROP COLUMN depth,
            DROP COLUMN tool_calls, DROP COLUMN tool_calls_total,
            DROP COLUMN model_calls, DROP COLUMN steps, DROP COLUMN limits,
            DROP COLUMN agent_hash, DROP COLUMN agent_version, DROP COLUMN agent_name,
            DROP COLUMN kind
    """)
    op.execute("DROP TABLE IF EXISTS agent_definitions")
