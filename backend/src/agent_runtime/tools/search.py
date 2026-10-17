"""SearchTool (R3.3): `search(query, k) → [{title, url, snippet, content}]`.

The default implementation serves `fixtures/search/*.json`, so demos, tests and
evals are deterministic and need no key. A query is normalised (lowercase,
punctuation dropped, spaces collapsed) and matched against each fixture's
`query` and `aliases`: exactly first, then by word overlap (Jaccard ≥ 0.5) and
string similarity (≥ 0.6), best first. Nothing close enough → no results, never
a guess. A real provider can replace it behind the same tool (`SEARCH_PROVIDER`,
later).

Fixture file:
    {"query": "...", "aliases": ["..."], "results": [{"title", "url", "snippet", "content"}]}
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

JACCARD_MIN = 0.5
SIMILARITY_MIN = 0.6


def normalise(query: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", query.lower()).split())


@dataclass(frozen=True)
class Fixture:
    keys: tuple[str, ...]  # normalised query + aliases
    results: tuple[dict[str, Any], ...]


@cache
def load(directory: Path) -> tuple[Fixture, ...]:
    fixtures = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        keys = tuple(normalise(q) for q in [data["query"], *data.get("aliases", [])])
        fixtures.append(Fixture(keys, tuple(data["results"])))
    return tuple(fixtures)


def _score(query: str, key: str) -> float:
    if query == key:
        return 2.0
    a, b = set(query.split()), set(key.split())
    jaccard = len(a & b) / len(a | b) if a | b else 0.0
    similarity = difflib.SequenceMatcher(None, query, key).ratio()
    if jaccard < JACCARD_MIN and similarity < SIMILARITY_MIN:
        return 0.0
    return max(jaccard, similarity)


def search(directory: Path, query: str, k: int) -> list[dict[str, Any]]:
    q = normalise(query)
    best = max(
        ((max(_score(q, key) for key in f.keys), f) for f in load(directory)),
        key=lambda pair: pair[0],
        default=(0.0, None),
    )
    score, fixture = best
    if fixture is None or score == 0.0:
        return []
    return [dict(r) for r in fixture.results[:k]]
