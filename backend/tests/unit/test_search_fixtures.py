"""The fixture SearchTool (R3.3, SC20): deterministic, exact then fuzzy, never a guess."""

from pathlib import Path

from agent_runtime.tools.search import normalise, search

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "search"


def test_exact_alias_and_normalised_queries_match() -> None:
    assert normalise("  Redis Streams, vs. KAFKA?! ") == "redis streams vs kafka"
    exact = search(FIXTURES, "redis streams vs kafka", 5)
    assert exact[0]["url"] == "https://docs.example.org/redis/streams-intro"
    assert search(FIXTURES, "Kafka vs Redis Streams", 5) == exact  # an alias


def test_fuzzy_matches_close_queries() -> None:
    assert (
        search(FIXTURES, "postgres advisory lock", 2)[0]["title"] == "Advisory locks in PostgreSQL"
    )
    assert search(FIXTURES, "langgraph checkpointer postgres", 5)


def test_k_limits_and_unknown_queries_return_nothing() -> None:
    assert len(search(FIXTURES, "redis streams vs kafka", 1)) == 1
    assert search(FIXTURES, "best pizza in naples", 5) == []


def test_results_are_deterministic() -> None:
    assert search(FIXTURES, "fencing token", 5) == search(FIXTURES, "fencing token", 5)
