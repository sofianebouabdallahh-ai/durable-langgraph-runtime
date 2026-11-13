"""The fenced checkpointer wraps every write LangGraph's saver implements (H10).

`FencedCheckpointer` guards `aput`, `aput_writes` and `adelete_thread`. If a LangGraph
upgrade implements another public write coroutine (`aprune`, `acopy_thread` and
`adelete_for_runs` are `BaseCheckpointSaver` stubs today), a worker that lost its lease
could write through it unfenced. This test lists the installed saver's public write
coroutines and fails until each one is overridden in `checkpointing.py`.
"""

from __future__ import annotations

import inspect
import re
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agent_runtime.checkpointing import FencedCheckpointer

_WRITE = re.compile(r"^a(put|delete|prune|copy)")


def _implemented_writes(saver: type) -> set[str]:
    """The saver's public coroutine methods named like a write, minus the base stubs.

    "Implemented" is decided by where the method is defined, not by parsing its body:
    a method the saver (or a Postgres base of it) defines itself is a real write; one
    inherited unchanged from `BaseCheckpointSaver` is a stub, since the base class
    stores nothing. Reformatting LangGraph's source can't break that. The stub's
    source is checked too, so a base class that one day implements a write itself
    is caught as well.
    """
    writes: set[str] = set()
    for name, member in inspect.getmembers(saver, inspect.iscoroutinefunction):
        if name.startswith("_") or not _WRITE.match(name):
            continue
        owner = next(klass for klass in saver.__mro__ if name in klass.__dict__)
        if owner is BaseCheckpointSaver and "NotImplementedError" in inspect.getsource(member):
            continue
        writes.add(name)
    return writes


def test_every_write_the_saver_implements_is_fenced() -> None:
    writes = _implemented_writes(AsyncPostgresSaver)
    assert writes, "no write coroutine found: LangGraph's saver API changed shape"
    unfenced = {name for name in writes if name not in FencedCheckpointer.__dict__}
    assert not unfenced, f"LangGraph writes not wrapped by FencedCheckpointer: {sorted(unfenced)}"


def test_the_base_class_only_has_stubs() -> None:
    """The detector's ground truth: the base saver implements no write."""
    assert _implemented_writes(BaseCheckpointSaver) == set()


def test_a_write_implemented_in_a_subclass_is_detected() -> None:
    """The detector sees a write the moment a class implements it, however it's written."""

    class Implements(BaseCheckpointSaver):  # type: ignore[type-arg]
        async def aprune(self, *args: Any, **kwargs: Any) -> None:
            return None

    assert "aprune" in _implemented_writes(Implements)
    assert "aprune" not in _implemented_writes(AsyncPostgresSaver)  # a stub in this release
