"""One version everywhere (L5): VERSION is the release; everything else follows it."""

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_every_part_carries_the_release_version() -> None:
    version = (ROOT / "VERSION").read_text().strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    backend = tomllib.loads((ROOT / "backend/pyproject.toml").read_text())["project"]["version"]
    ui = json.loads((ROOT / "frontend/package.json").read_text())["version"]
    charts = {
        chart: re.search(
            r'^appVersion: "([^"]+)"', (ROOT / f"infra/helm/{chart}/Chart.yaml").read_text(), re.M
        )
        for chart in ("agent-runtime", "nuria-data")
    }
    assert backend == ui == version
    assert {c: m.group(1) if m else None for c, m in charts.items()} == dict.fromkeys(
        charts, version
    )
