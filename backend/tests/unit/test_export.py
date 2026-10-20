"""A chat as Markdown (L5): code blocks can't be closed by what they contain."""

from agent_runtime.sessions.export import MAX_RESULT, _block


def test_a_block_is_fenced_longer_than_any_backticks_inside() -> None:
    assert _block({"a": 1}).startswith("```\n{")
    tricky = _block("before ```` after")
    assert tricky.startswith("`````\n") and tricky.endswith("\n`````")


def test_a_long_result_is_cut() -> None:
    assert _block("x" * (MAX_RESULT + 50)).count("x") == MAX_RESULT
    assert "… (cut)" in _block("x" * (MAX_RESULT + 1))
