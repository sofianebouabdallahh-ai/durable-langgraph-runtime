"""LocalSpawner (`--local-fanout`): the same limits as the durable fan-out, in-process."""

import pytest

from agent_runtime.graphs import default_registry
from agent_runtime.runs.fanout import ChildSpec, FanOutRejected, LocalSpawner, is_spawn

GRAPHS = default_registry()


def toy(key: str, **inp: object) -> ChildSpec:
    return ChildSpec(key=key, graph="toy", input={"question": "q", **inp})


async def test_children_run_concurrently_and_failures_make_it_partial() -> None:
    fan_in = await LocalSpawner(GRAPHS).spawn([toy("a"), toy("b", fail_at="answer")])
    assert [c.status for c in fan_in.children] == ["completed", "failed"]
    assert fan_in.partial is True
    assert fan_in.children[0].output is not None and fan_in.children[1].reason


@pytest.mark.parametrize(
    ("children", "reason"),
    [
        ([], "at least one child"),
        ([toy("a"), toy("a")], "unique"),
        ([toy(str(i)) for i in range(3)], "max_children=2"),
        ([ChildSpec(key="a", graph="assistant", input={"message": "m"})], "workflow graphs only"),
    ],
)
async def test_rejections(children: list[ChildSpec], reason: str) -> None:
    with pytest.raises(FanOutRejected, match=reason):
        await LocalSpawner(GRAPHS, max_children=2).spawn(children)


def test_is_spawn() -> None:
    assert is_spawn({"type": "spawn_children", "children": []})
    assert not is_spawn({"type": "tool_approval"}) and not is_spawn("x")
