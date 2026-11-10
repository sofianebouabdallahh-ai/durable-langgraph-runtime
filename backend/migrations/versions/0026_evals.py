"""Agent evals (phase H6).

- `agent_evals`: a Studio agent's test cases (evals/cases.py), edited in the Tests tab;
  `from_run`: the 👎 reply a case was made from.
- `eval_runs`: one graded turn. The case as it was run (and its hash: editing the case
  makes the result stale), the bundle it ran on (the publish gate compares it with the
  draft's), what the test answers when the agent asks, and the outcome with each check.
  Written by the API when the turn is sent; graded by the worker when the turn ends.
  `agent_id` is NULL for a built-in agent's suite (`runtime eval`).

Additive only (expand step).

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE agent_evals (
            id          uuid PRIMARY KEY,
            agent_id    uuid        NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
            name        text        NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
            "case"      jsonb       NOT NULL,
            from_run    uuid        REFERENCES runs (id) ON DELETE SET NULL,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_agent_evals_agent ON agent_evals (agent_id, created_at)")
    op.execute("""
        CREATE TABLE eval_runs (
            run_id       uuid PRIMARY KEY REFERENCES runs (id) ON DELETE CASCADE,
            agent        text        NOT NULL,
            agent_id     uuid        REFERENCES agents (id) ON DELETE CASCADE,
            case_key     text        NOT NULL,   -- agent_evals.id, or <agent>/<file> (built-in)
            case_hash    text        NOT NULL CHECK (length(case_hash) = 64),
            "case"       jsonb       NOT NULL,
            bundle_hash  text,
            batch        uuid        NOT NULL,   -- one "Run tests"
            status       text        NOT NULL DEFAULT 'running'
                         CHECK (status IN ('running', 'passed', 'failed', 'error')),
            checks       jsonb       NOT NULL DEFAULT '[]',
            created_at   timestamptz NOT NULL DEFAULT now(),
            finished_at  timestamptz
        )
    """)
    op.execute("CREATE INDEX ix_eval_runs_gate ON eval_runs (agent_id, bundle_hash, case_key)")
    op.execute("CREATE INDEX ix_eval_runs_batch ON eval_runs (batch)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON agent_evals TO app_api")
    op.execute("GRANT SELECT, INSERT, UPDATE ON eval_runs TO app_api")  # a redrive regrades
    op.execute("GRANT SELECT, UPDATE ON eval_runs TO app_worker")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS eval_runs")
    op.execute("DROP TABLE IF EXISTS agent_evals")
