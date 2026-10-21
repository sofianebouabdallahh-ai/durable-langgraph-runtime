"""OpenTelemetry GenAI attribute names (phase L7a), set next to our own on the spans.

The GenAI semantic conventions are still "Development" (October 2026), so their names are
kept here, in one place, and can follow the spec as it settles. Tools that read them
(Grafana, Phoenix, Langfuse) then understand our traces without a mapping. Never prompts
or completions: only names, ids and counts.
"""

from __future__ import annotations

import uuid
from typing import Any


def _set(**attrs: Any) -> dict[str, Any]:
    return {k.replace("__", "."): v for k, v in attrs.items() if v is not None}


def agent(name: str | None, version: int | None, session_id: uuid.UUID | None) -> dict[str, Any]:
    """On a `run` span: which agent, and the conversation it belongs to."""
    return {
        **_set(gen_ai__operation__name="invoke_agent", gen_ai__agent__name=name or None),
        **_set(agent__version=version),  # ours: the spec has no agent version yet
        **_set(gen_ai__conversation__id=str(session_id) if session_id else None),
    }


def chat(model: str, tokens_in: int, tokens_out: int) -> dict[str, Any]:
    """On an `llm.call` span: one model call."""
    return _set(
        gen_ai__operation__name="chat", gen_ai__request__model=model,
        gen_ai__usage__input_tokens=tokens_in, gen_ai__usage__output_tokens=tokens_out,
    )  # fmt: skip


def tool(name: str, call_id: str) -> dict[str, Any]:
    """On a `tool:{name}` span: one tool call."""
    return _set(gen_ai__operation__name="execute_tool", gen_ai__tool__name=name,
                gen_ai__tool__call__id=call_id)  # fmt: skip
