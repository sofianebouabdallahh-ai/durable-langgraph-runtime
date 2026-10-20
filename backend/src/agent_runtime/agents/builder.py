"""Describe it, improve it (CR-006 R17.3, R17.2): the Studio's builder agents.

"Describe your agent" and "Improve my instructions" are agents themselves: hidden
built-in agents (`backend/agents/agent-builder/`, `…/instructions-coach/`), each with
one tool whose arguments *are* the structured answer:

    description ─► agent-builder ─► propose_draft(DraftProposal)
                                     └─ mapped onto a Studio document and checked by the
                                        one validator; issues go back to the model, which
                                        repairs (its few turns are the repair rounds)
    instructions ─► instructions-coach ─► propose_instructions(instructions, what_changed)

They run as ordinary runs: the default model, budgets, retries, the breaker and crash
recovery all apply, and tool calling is exactly what a model's test proved (L3b).
Nothing is saved: the result is a proposal the person accepts, edits or drops.

Offline, the demo drafter (a keyword Strategy, like the demo responder) proposes a
draft from the description, so the flow works without a model and is deterministic
in CI.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import Field

from agent_runtime.agents.schema import MAIN_PLACEHOLDERS, PLACEHOLDER
from agent_runtime.tools.spec import ToolArgs, ToolContext, ToolRegistry

BUILDER, COACH = "agent-builder", "instructions-coach"
BUILDER_TOOLS = ("propose_draft", "propose_instructions")
Effort = Annotated[str, Field(pattern="^(quick|standard|thorough)$")]


class BuilderError(Exception):
    """What's wrong with a proposal, in plain words (the model reads it and repairs)."""


class HelperProposal(ToolArgs):
    display_name: Annotated[
        str, Field(min_length=1, max_length=60, description="Its name, e.g. 'Flight finder'")
    ]
    description: Annotated[
        str, Field(min_length=1, max_length=300, description="What it does, in one sentence")
    ]
    instructions: Annotated[
        str, Field(min_length=1, max_length=4000, description="How it should do its job")
    ]
    tools: list[str] = Field(default_factory=list, description="From the tools offered")


class DraftProposal(ToolArgs):
    display_name: Annotated[
        str,
        Field(min_length=1, max_length=60, description="The assistant's name, e.g. 'Trip planner'"),
    ]
    description: Annotated[
        str, Field(min_length=1, max_length=300, description="What it's for, in one sentence")
    ]
    instructions: Annotated[
        str,
        Field(
            min_length=1,
            max_length=6000,
            description=(
                "Its instructions, written to it ('You are…'): what it does, how it answers, "
                "what it never does. Placeholders allowed: {{date}}"
            ),
        ),
    ]
    tools: list[str] = Field(default_factory=list, description="From the tools offered")
    effort: Effort = Field(default="standard", description="quick, standard or thorough")
    helpers: Annotated[list[HelperProposal], Field(max_length=3)] = Field(
        default_factory=list, description="Only if the job has clearly separate parts"
    )
    skills: list[str] = Field(
        default_factory=list, description="Names of skills from the library that fit"
    )


class InstructionsProposal(ToolArgs):
    instructions: Annotated[str, Field(min_length=1, max_length=6000)]
    what_changed: Annotated[
        str, Field(min_length=1, max_length=300, description="One sentence for the person")
    ]


# ------------------------------------------------------------------ the mapping


def to_document(proposal: DraftProposal, name: str, settings: Any) -> dict[str, Any]:
    """The proposal as a Studio document (the form's shape), with the protections a
    new agent gets by default and the effort as a preset within the ceilings."""
    from agent_runtime.agents.studio import PROTECTIONS, TOOLS, presets, slug

    tiers = presets(settings)
    hooks: dict[str, list[str]] = {}
    helper_hooks: dict[str, list[str]] = {}
    for hook, (point, _, _, default) in PROTECTIONS.items():
        if default:
            hooks.setdefault(point, []).append(hook)
            if point in ("pre_tool", "post_tool"):
                helper_hooks.setdefault(point, []).append(hook)
    offered = [t for t in TOOLS]
    helpers = []
    for h in proposal.helpers:
        helpers.append(
            {
                "name": slug(h.display_name),
                "display_name": h.display_name,
                "description": h.description,
                "instructions": h.instructions,
                "tools": [{"name": t} for t in h.tools if t in offered and t != "notify"],
                "max_turns": tiers["helper"]["max_turns"],
                "limits": tiers["helper"]["limits"],
                "hooks": helper_hooks,
            }
        )
    tier = tiers[proposal.effort]
    return {
        "name": name,
        "display_name": proposal.display_name,
        "description": proposal.description,
        "instructions": proposal.instructions,
        "tools": [{"name": t} for t in proposal.tools if t in offered],
        "max_turns": tier["max_turns"],
        "limits": tier["limits"],
        "hooks": hooks,
        "helpers": helpers,
        "skills": list(dict.fromkeys(proposal.skills)),
    }


def _problems(proposal: DraftProposal) -> list[str]:
    """Everything wrong with a proposal, by the one validator plus the builder's rules."""
    from agent_runtime.agents.document import AgentDocument, to_raw
    from agent_runtime.agents.loader import Ceilings, validate_definition
    from agent_runtime.agents.studio import TOOLS
    from agent_runtime.catalog import default_catalog
    from agent_runtime.config import get_agent_settings

    settings = get_agent_settings()
    problems = [
        f"unknown tool “{t}”: choose from {', '.join(TOOLS)}"
        for t in {*proposal.tools, *(t for h in proposal.helpers for t in h.tools)}
        if t not in TOOLS
    ]
    problems += [
        f"helper “{h.display_name}” can't send notifications: only the main agent "
        "can (they need a person's approval)"
        for h in proposal.helpers
        if "notify" in h.tools
    ]
    names = [h.display_name.strip().lower() for h in proposal.helpers]
    if len(set(names)) < len(names):
        problems.append("two helpers have the same name")
    document = AgentDocument.model_validate(to_document(proposal, "draft", settings))
    main, helpers = to_raw(document, 1)
    _, issues = validate_definition(
        main, helpers, default_catalog(), Ceilings.from_settings(settings)
    )
    return problems + [str(i) for i in issues]


# ------------------------------------------------------------------ the tools


async def propose_draft(args: DraftProposal, ctx: ToolContext) -> dict[str, Any]:
    """Propose the assistant: its name, purpose, instructions, tools, effort, helpers and
    skills. If something is wrong you'll get the problems: fix them and propose again."""
    if problems := _problems(args):
        raise BuilderError("Not valid yet: " + "; ".join(problems))
    return {"accepted": True, "proposal": args.model_dump(mode="json")}


async def propose_instructions(args: InstructionsProposal, ctx: ToolContext) -> dict[str, Any]:
    """Propose the improved instructions and say in one sentence what changed."""
    unknown = sorted(
        {m for m in PLACEHOLDER.findall(args.instructions) if m not in MAIN_PLACEHOLDERS}
    )
    if unknown:
        raise BuilderError(
            f"Only these placeholders exist: {', '.join(sorted(MAIN_PLACEHOLDERS))}"
            f" (not {', '.join(unknown)})"
        )
    return {"accepted": True, "proposal": args.model_dump(mode="json")}


def register(registry: ToolRegistry) -> ToolRegistry:
    registry.tool("propose_draft", args=DraftProposal, risk_class="read", side_effect=False)(
        propose_draft
    )
    registry.tool(
        "propose_instructions", args=InstructionsProposal, risk_class="read", side_effect=False
    )(propose_instructions)
    return registry


def proposal_of(messages: list[Any]) -> dict[str, Any] | None:
    """The last accepted proposal in a builder run's messages (its output)."""
    import json

    from langchain_core.messages import ToolMessage

    from agent_runtime.untrusted import unwrap

    for m in reversed(messages):
        if isinstance(m, ToolMessage) and m.name in BUILDER_TOOLS and m.status != "error":
            try:
                result = json.loads(unwrap(str(m.content)))
            except ValueError:
                continue
            if isinstance(result, dict) and result.get("accepted"):
                proposal: dict[str, Any] = result["proposal"]
                return proposal
    return None


# ------------------------------------------------------------------ the messages


def describe_message(description: str, skills: list[tuple[str, str]]) -> str:
    """What the builder is asked: the person's words, and what it may choose from."""
    from agent_runtime.agents.studio import TOOLS

    tools = "\n".join(f"- {name}: {desc}" for name, (_, desc) in TOOLS.items())
    library = "\n".join(f"- {n}: {d}" for n, d in skills[:30]) or "(none yet)"
    return (
        f"Tools offered:\n{tools}\n\nSkills in the library:\n{library}\n\n"
        f"The person's description:\n{description.strip()}"
    )[:7900]


def improve_message(display_name: str, purpose: str, instructions: str, tools: list[str]) -> str:
    return (
        f"Assistant: {display_name}\nWhat it's for: {purpose or '(not said)'}\n"
        f"Its tools: {', '.join(tools) or 'none'}\n\nIts instructions now:\n{instructions}"
    )[:7900]


# ------------------------------------------------------------------ offline demo

_TOOL_WORDS = {
    "web_search": r"search|find|look up|research|sources?|web|internet|news|latest",
    "read_webpage": r"read|pages?|articles?|links?|sources?|research|cite",
    "run_python": r"calculat|math|budget|cost|price|sum|convert|numbers?|data|csv|chart|analy[sz]",
    "save_note": r"remember|notes?|keep track|save",
    "notify": r"notify|tell (the )?team|send (a )?message|email|alert",
}
_FILLER = frozenset(
    [
        "a",
        "an",
        "and",
        "the",
        "for",
        "to",
        "of",
        "my",
        "our",
        "your",
        "me",
        "i",
        "it",
        "that",
        "this",
        "with",
        "who",
        "which",
    ]
)
_HELPER = re.compile(r"\b(?:and|with) a helper (?:that|who|to) ([^.;\n]{3,120})", re.IGNORECASE)


def demo_draft(description: str, skills: list[tuple[str, str]]) -> DraftProposal:
    """The offline demo's draft: a deterministic reading of the description."""
    text = " ".join(description.split())
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]+", text) if w.lower() not in _FILLER]
    if len(words) > 2 and re.match(r"(?i)\s*it\s", text) and words[0].lower().endswith("s"):
        words = words[1:]  # "It plans family trips" → "Family Trips"
    topic = " ".join(words[:2]).title() if words else "My"
    name = (topic if "assistant" in topic.lower() else f"{topic} assistant")[:60]
    tools = [t for t, pattern in _TOOL_WORDS.items() if re.search(pattern, text, re.IGNORECASE)]
    helpers = []
    if m := _HELPER.search(text):
        job = m.group(1).strip()
        named = job.split()
        if len(named) > 1 and named[0].lower().endswith("s"):  # "finds kid-friendly …"
            named = named[1:]
        helpers.append(
            HelperProposal(
                display_name=" ".join(named[:2]).title()[:60] or "Helper",
                description=job[:1].upper() + job[1:300],
                instructions=f"You {job}. Be brief.",
                tools=[t for t in tools if t != "notify"],
            )
        )
    lowered = text.lower()
    chosen = [
        n
        for n, d in skills
        if n.replace("-", " ") in lowered or any(w in lowered for w in n.split("-") if len(w) > 3)
    ]
    return DraftProposal(
        display_name=name,
        description=(text[:1].upper() + text[1:280]) or "A helpful assistant.",
        instructions=(
            f"You are {name}. Today is {{{{date}}}}.\n\n"
            f"Your job: {text[:600] or 'help the person'}\n\n"
            "Ask one short question when something important is missing. Answer clearly "
            "and briefly. Never make up facts: say when you don't know."
        ),
        tools=tools,
        effort="standard",
        helpers=helpers,
        skills=chosen[:3],
    )


def demo_improve(instructions: str, display_name: str) -> InstructionsProposal:
    """The offline demo's suggestion: the same text, with a clear structure added."""
    body = instructions.strip() or f"You are {display_name}."
    extra = [
        line
        for line in (
            "" if "{{date}}" in body else "Today is {{date}}.",
            ""
            if re.search(r"\bnever\b", body, re.IGNORECASE)
            else "Never make up facts: say when you don't know.",
            ""
            if re.search(r"\bquestion", body, re.IGNORECASE)
            else "Ask one short question when something important is missing.",
        )
        if line
    ]
    improved = body if not extra else body + "\n\n" + "\n".join(f"- {e}" for e in extra)
    changed = (
        "Added " + ", ".join(e.split(":")[0].rstrip(".").lower() for e in extra)
        if extra
        else "It's already clear: no changes needed"
    )
    return InstructionsProposal(instructions=improved, what_changed=changed[:300])


def demo_script(proposal: DraftProposal | InstructionsProposal) -> list[dict[str, Any]]:
    """The scripted model's turn for a builder run (stored in the run's input)."""
    tool = "propose_draft" if isinstance(proposal, DraftProposal) else "propose_instructions"
    return [
        {"tool_calls": [{"name": tool, "args": proposal.model_dump(mode="json")}]},
        {"content": "Here's a proposal. Check it and change anything you like."},
    ]
