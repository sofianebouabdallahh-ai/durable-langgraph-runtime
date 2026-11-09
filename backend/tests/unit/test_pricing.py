"""Prices are never silently zero (phase H2): the resolver chain and prefix matching."""

import pytest

from agent_runtime.config import ModelPrice
from agent_runtime.models.pricing import BUILT_IN, ESTIMATE, Price, longest_prefix, resolve_price


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-4o-mini", "gpt-4o-mini"),
        ("gpt-4o-mini-2024-07-18", "gpt-4o-mini"),  # a dated snapshot: the longest prefix
        ("gpt-4o-2024-08-06", "gpt-4o"),
        ("gpt-5-mini-2025-08-07", "gpt-5-mini"),  # not gpt-5
        ("GPT-4.1", "gpt-4.1"),
        ("gpt-4.1-mini-2025-04-14", "gpt-4.1-mini"),
    ],
)
def test_longest_prefix_matches_dated_snapshots(model: str, expected: str) -> None:
    assert longest_prefix(BUILT_IN, model) == BUILT_IN[expected]


@pytest.mark.parametrize("model", ["gpt-4ox", "o3x", "llama3.1", "", "gpt"])
def test_a_prefix_must_end_at_a_dash(model: str) -> None:
    assert longest_prefix(BUILT_IN, model) is None


def test_the_resolver_chain_in_order() -> None:
    settings = {"gpt-4o-mini": ModelPrice(input_per_mtok=1, output_per_mtok=2)}
    own = {"gpt-4o-mini": {"input_per_mtok": 3.0, "output_per_mtok": 4.0}}
    assert resolve_price("gpt-4o-mini", connection_prices=own, settings_prices=settings) == Price(
        3.0, 4.0, "connection"
    )
    assert resolve_price("gpt-4o-mini-2024-07-18", settings_prices=settings) == Price(
        1.0, 2.0, "settings"
    )
    assert resolve_price("gpt-4o-mini") == Price(0.15, 0.60, "built-in")
    assert resolve_price("qwen2.5:7b", local=True) == Price(0.0, 0.0, "local")
    unknown = resolve_price("my-azure-deployment")
    assert unknown == Price(*ESTIMATE, "estimate") and unknown.estimated
    # A known model's price wins over "local" (an OpenAI model behind a local proxy).
    assert resolve_price("gpt-4o", local=True).source == "built-in"


def test_scripted_stays_free_through_the_settings() -> None:
    free = {"scripted": ModelPrice(input_per_mtok=0, output_per_mtok=0)}
    price = resolve_price("scripted", settings_prices=free)
    assert price.cost(1_000_000, 1_000_000) == 0 and price.source == "settings"


def test_cost_and_round_trip() -> None:
    price = Price(0.15, 0.60, "built-in")
    assert price.cost(1_000_000, 500_000) == pytest.approx(0.45)
    assert Price.from_dict(price.as_dict()) == price
