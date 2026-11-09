"""What a model call costs (phase H2, R14.1): never silently zero.

A turn's prices are resolved once, when it is created, and pinned with its model
bindings (a turn keeps the price it started with). For each model, the first answer
wins (Chain of Responsibility):

    1 connection   the price set for this model on its connection (Settings → Models)
    2 settings     MODEL_PRICES in .env, exact name, then longest prefix
    3 built-in     the table below, by longest prefix (providers report dated snapshot
                   ids such as gpt-4o-mini-2024-07-18)
    4 local        a model on this machine or network (Ollama…) is free
    5 estimate     a deliberately high default, marked `estimated`, so budgets still bind

All input tokens are priced at the full input rate (cached input is cheaper), which
errs high: the safe side for a budget.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

Source = Literal["connection", "settings", "built-in", "local", "estimate"]

# USD per 1M tokens (input, output), standard tier, short context, from OpenAI's price
# list (https://developers.openai.com/api/docs/pricing), checked 2026-11-08. Prices
# change: a connection's own price, or MODEL_PRICES, always wins over this table.
BUILT_IN_AS_OF = "2026-11-08"
BUILT_IN: dict[str, tuple[float, float]] = {
    "gpt-6-astra": (10.00, 50.00),
    "gpt-6.1-sol": (2.00, 10.00),
    "gpt-6.1-terra": (1.00, 5.00),
    "gpt-6-sol": (2.00, 10.00),
    "gpt-6-luna": (0.10, 0.50),
    "gpt-5.6-sol": (4.00, 20.00),
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5.6-luna": (0.20, 1.20),
    "gpt-5.5-pro": (30.00, 180.00),
    "gpt-5.5": (5.00, 30.00),
    "gpt-5.4-pro": (30.00, 180.00),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.2-pro": (21.00, 168.00),
    "gpt-5.2": (1.75, 14.00),
    "gpt-5.1": (1.25, 10.00),
    "gpt-5-pro": (15.00, 120.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5": (1.25, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "o3-pro": (20.00, 80.00),
    "o3": (2.00, 8.00),
}

# An unknown model's estimate: high on purpose (a flagship's price), so a budget fires
# early rather than never. Setting the real price takes a minute in Settings → Models.
ESTIMATE: tuple[float, float] = (5.00, 30.00)


@dataclass(frozen=True, slots=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float
    source: Source

    @property
    def estimated(self) -> bool:
        return self.source == "estimate"

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        return (tokens_in * self.input_per_mtok + tokens_out * self.output_per_mtok) / 1e6

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_per_mtok": self.input_per_mtok,
            "output_per_mtok": self.output_per_mtok,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Price:
        return cls(
            float(value["input_per_mtok"]),
            float(value["output_per_mtok"]),
            value.get("source", "settings"),
        )


def longest_prefix[T](table: Mapping[str, T], model: str) -> T | None:
    """The entry for `model`: its exact name, else the longest name it extends (with a
    `-` after it: `gpt-4o-mini-2024-07-18` → `gpt-4o-mini`, never `gpt-4o`)."""
    key = model.strip().lower()
    if key in table:
        return table[key]
    best: str | None = None
    for name in table:
        if key.startswith(f"{name}-") and (best is None or len(name) > len(best)):
            best = name
    return table[best] if best is not None else None


def resolve_price(
    model: str,
    *,
    connection_prices: Mapping[str, Mapping[str, Any]] | None = None,
    settings_prices: Mapping[str, Any] | None = None,
    local: bool = False,
) -> Price:
    """The price of one call to `model` (USD per 1M tokens), by the rules above."""
    if connection_prices and (own := connection_prices.get(model)):
        return Price(float(own["input_per_mtok"]), float(own["output_per_mtok"]), "connection")
    configured = {k.lower(): v for k, v in (settings_prices or {}).items()}
    if (found := longest_prefix(configured, model)) is not None:
        return Price(_field(found, "input_per_mtok"), _field(found, "output_per_mtok"), "settings")
    if (known := longest_prefix(BUILT_IN, model)) is not None:
        return Price(known[0], known[1], "built-in")
    if local:
        return Price(0.0, 0.0, "local")
    return Price(ESTIMATE[0], ESTIMATE[1], "estimate")


def _field(price: Any, name: str) -> float:
    """A MODEL_PRICES entry: the settings' ModelPrice, or a plain mapping."""
    return float(price[name] if isinstance(price, Mapping) else getattr(price, name))
