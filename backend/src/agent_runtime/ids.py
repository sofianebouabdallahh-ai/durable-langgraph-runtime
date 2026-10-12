"""Identifiers.

Run, session and sub-agent ids are UUIDv7 (R1.1): the first 48 bits are a
millisecond timestamp, so ids sort by creation time. That keeps B-tree index
inserts at the right edge (no random page splits as with UUIDv4) and makes ids
roughly chronological in logs. Postgres 16 can't generate v7, so the app does.
"""

import uuid

import uuid_utils


def new_id() -> uuid.UUID:
    """A new time-ordered UUIDv7, as a standard-library UUID."""
    return uuid.UUID(bytes=uuid_utils.uuid7().bytes)
