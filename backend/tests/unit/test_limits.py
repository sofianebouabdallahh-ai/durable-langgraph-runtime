"""Every server ceiling always applies (phase H2): ceilings ≥ profile ≥ options."""

import pytest

from agent_runtime.config import Settings
from agent_runtime.runs.limits import LimitAboveCeiling, Profile, RunOptions, resolve_limits


@pytest.fixture
def settings() -> Settings:
    return Settings.model_construct(**{
        name: field.default for name, field in Settings.model_fields.items()
        if field.default is not None and not callable(field.default)
    })  # fmt: skip


@pytest.mark.parametrize(
    "option", ["max_model_calls", "max_tool_calls", "max_tokens", "max_cost_usd"]
)
def test_an_option_above_a_ceiling_is_refused_even_when_the_agent_sets_no_limit(
    settings: Settings, option: str
) -> None:
    """The review's finding: an agent with no `limits` of its own had no tool ceiling,
    and `max_tool_calls: 1000000` was accepted."""
    with pytest.raises(LimitAboveCeiling, match=f"options.{option}"):
        resolve_limits(settings, RunOptions(**{option: 100_000_000}), Profile(max_model_calls=10))


def test_every_ceiling_is_stored_for_every_run(settings: Settings) -> None:
    for profile in (None, Profile(max_model_calls=10)):
        limits = resolve_limits(settings, RunOptions(), profile)
        assert limits.max_tool_calls == settings.ceiling_tool_calls
        assert limits.max_tokens == settings.ceiling_tokens
        assert limits.max_cost_usd == settings.ceiling_cost_usd
        assert limits.max_model_calls == (10 if profile else settings.ceiling_model_calls)


def test_tighter_layers_still_win(settings: Settings) -> None:
    limits = resolve_limits(
        settings, RunOptions(max_tool_calls=3), Profile(max_model_calls=10, max_tool_calls=5)
    )
    assert (limits.max_model_calls, limits.max_tool_calls) == (10, 3)
