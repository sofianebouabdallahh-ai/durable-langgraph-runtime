"""Honest and resilient (phase H4).

- `runs.infra_retries`: how many times this run was released because the
  infrastructure failed (Postgres, Redis); past MAX_INFRA_RETRIES it ends
  `failed(infrastructure)`. Reset by a redrive.
- `runs.redrives`: how many times a person tried a failed run again.
- `notes.author`: which helper saved a note (NULL: the agent itself), so `recall_notes`
  reads back only its own agent's notes, never a helper's or the other way round.
- `notification_deliveries`: one row per notification, the relay's state (the webhook,
  notifications/delivery.py). Kept apart from `outbox_notifications`, whose rows are
  epoch-fenced: marking one sent after its run was reclaimed would trip the fence.
  An AFTER INSERT trigger creates the row, so every notification has exactly one.
  Notifications from before H4 are backfilled as `skipped`: an upgrade never sends old
  notifications by surprise.

Additive only (expand step).

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE runs ADD COLUMN infra_retries integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE runs ADD COLUMN redrives integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE notes ADD COLUMN author text")
    op.execute("""
        CREATE TABLE notification_deliveries (
            key           text PRIMARY KEY
                          REFERENCES outbox_notifications (key) ON DELETE CASCADE,
            status        text        NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'sending', 'delivered', 'failed',
                                            'skipped')),
            attempts      integer     NOT NULL DEFAULT 0,
            next_at       timestamptz NOT NULL DEFAULT now(),
            claim         uuid,                 -- the sender holding it ('sending')
            claimed_until timestamptz,          -- past this, another sender may take it
            last_status   integer,              -- the receiver's last HTTP status
            last_error    text CHECK (char_length(last_error) <= 500),
            delivered_at  timestamptz,
            created_at    timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX ix_notification_deliveries_due ON notification_deliveries (next_at)
        WHERE status IN ('pending', 'sending')
    """)
    op.execute("""
        CREATE FUNCTION notification_delivery_row() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO notification_deliveries (key) VALUES (NEW.key)
            ON CONFLICT (key) DO NOTHING;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER outbox_notifications_delivery
        AFTER INSERT ON outbox_notifications
        FOR EACH ROW EXECUTE FUNCTION notification_delivery_row()
    """)
    op.execute("""
        INSERT INTO notification_deliveries (key, status, last_error)
        SELECT key, 'skipped', 'queued before Nuria delivered notifications'
        FROM outbox_notifications
        ON CONFLICT (key) DO NOTHING
    """)
    # The worker inserts (through the trigger, as itself) and relays; the API lists.
    op.execute("GRANT SELECT, INSERT, UPDATE ON notification_deliveries TO app_worker")
    op.execute("GRANT SELECT ON notification_deliveries, outbox_notifications TO app_api")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS outbox_notifications_delivery ON outbox_notifications")
    op.execute("DROP FUNCTION IF EXISTS notification_delivery_row()")
    op.execute("DROP TABLE IF EXISTS notification_deliveries")
    op.execute("ALTER TABLE notes DROP COLUMN IF EXISTS author")
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS redrives")
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS infra_retries")
