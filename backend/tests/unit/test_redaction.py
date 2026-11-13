"""redaction.py (H10): one fake per pattern, the prose that must stay readable, the values
Nuria holds, and the count an approval card shows."""

import pytest

from agent_runtime.redaction import (
    MIN_KNOWN_CHARS,
    REDACTED,
    SECRET_PATTERNS,
    KnownSecrets,
    known_secrets,
    redact,
    redact_counted,
)

# Assembled at runtime so no secret-shaped literal sits in the source: gitleaks (CI and
# the pre-commit hook) scans the file's text, and an allowlist would weaken it for real
# secrets too. Every value is obviously fake (repeated letters).
_PEM = "-----BEGIN RSA " + "PRIVATE KEY-----\nMIIE\n-----END RSA " + "PRIVATE KEY-----"
FAKES = {
    "openai": "sk-" + "abcdefghijklmnopqrstuvwxyz0123",
    "aws": "AKIA" + "ABCDEFGHIJKLMNOP",
    "github": "ghp_" + "a" * 36,
    "pem": _PEM,
    "bearer": "Bearer " + "abcdefghijklmnop1234",
    "google": "AIza" + "A" * 35,
    "slack_bot": "xoxb-" + "1" * 12 + "-" + "2" * 12 + "-" + "a" * 24,
    "slack_user": "xoxp" + ("-" + "1" * 12) * 3 + "-" + "a" * 32,
    "slack_app": "xapp-1-" + "A" * 10 + "-" + "1" * 13 + "-" + "a" * 64,
    "slack_webhook": (
        "hooks.slack.com/services/" + "T" + "0" * 10 + "/B" + "0" * 10 + "/" + "x" * 24
    ),
    "jwt": "ey" + "J" * 20 + ".ey" + "K" * 20 + "." + "L" * 20,
    "huggingface": "hf_" + "A" * 34,
    "gitlab": "glpat-" + "A" * 20,
    "npm": "npm_" + "a" * 36,
    "stripe": "sk_test_" + "A" * 24,
    "stripe_restricted": "rk_live_" + "a" * 24,
    "azure": "abc" + "1Q~" + "A" * 32,
    "tavily": "tvly-" + "A" * 32,
}

# Prose and names a pattern must leave alone.
NEAR_MISSES = [
    "risk-management-guidelines-2026",
    "the bearer of good news arrived early",
    "post it in #xoxo-team, not #xoxb-team",
    "AIzaShort is not a key, nor is hf_model_card or npm_install_failed",
    "glpat-short, sk_test_short, tvly-short: all too short",
    "eyes.eyes.eyes looks nothing like a token",
    "https://hooks.slack.com/services/short",
    "mod 1Q~ in the margin",
    "export AKIAROUND=1",
]


@pytest.mark.parametrize("name", list(FAKES))
def test_each_pattern_masks_its_fake_wherever_it_sits(name: str) -> None:
    fake = FAKES[name]
    out = redact({"a": [f"use {fake} please"], "b": {"c": fake}, "n": 3})
    assert fake not in str(out) and REDACTED in str(out["a"][0]) and out["n"] == 3
    assert out["b"]["c"].count(REDACTED) == 1  # the whole value, in one marker


def test_every_fake_is_caught_by_at_least_one_pattern() -> None:
    for name, fake in FAKES.items():
        assert any(p.search(fake) for p in SECRET_PATTERNS), name


@pytest.mark.parametrize("text", NEAR_MISSES)
def test_prose_that_only_resembles_a_key_is_left_alone(text: str) -> None:
    assert redact(text) == text


def test_a_redaction_is_idempotent() -> None:
    """The pipeline runs the post_tool hooks again on a cached result (H10)."""
    value = {"keys": list(FAKES.values()), "url": "postgresql://agent:hunter2@db:5432/x"}
    once = redact(value)
    assert redact(once) == once
    assert once["url"] == f"postgresql://{REDACTED}@db:5432/x"


def test_redact_counted_says_how_many_values_it_masked() -> None:
    args = {"to": "ceo", "message": f"keys {FAKES['openai']} and {FAKES['google']}", "n": 1}
    shown, hidden = redact_counted(args)
    assert hidden == 2 and shown["message"] == f"keys {REDACTED} and {REDACTED}"
    # Already redacted (the pre_tool hook ran): the card hides nothing
    assert redact_counted(shown) == (shown, 0)
    assert redact_counted({"to": "ceo"}) == ({"to": "ceo"}, 0)


# ------------------------------------------------------------- known values (H10)


def test_a_value_nuria_holds_is_masked_in_args_results_and_nested_structures() -> None:
    held = "held-connection-key-" + "7" * 24  # unique: it stays registered for the process
    known_secrets.add(held)
    assert held in known_secrets
    out, hidden = redact_counted(
        {"args": {"q": f"token={held}"}, "result": [held, {"deep": [f"x {held} y"]}]}
    )
    assert held not in str(out) and hidden == 3
    assert out == {
        "args": {"q": f"token={REDACTED}"},
        "result": [REDACTED, {"deep": [f"x {REDACTED} y"]}],
    }


def test_short_values_are_never_registered() -> None:
    registry = KnownSecrets()
    registry.add("12345", "", None, "a" * (MIN_KNOWN_CHARS - 1))
    assert len(registry) == 0 and "12345" not in registry
    registry.add("a" * MIN_KNOWN_CHARS)
    assert len(registry) == 1
    assert redact("the pin is 12345") == "the pin is 12345"


def test_a_value_that_contains_another_is_masked_whole() -> None:
    registry = KnownSecrets()
    registry.add("abcdefghij", "abcdefghij-with-a-suffix")
    assert registry.mask("abcdefghij-with-a-suffix") == (REDACTED, 1)
    assert registry.mask("abcdefghij alone") == (f"{REDACTED} alone", 1)
    registry.add("abcdefghij")  # already known: nothing changes
    assert len(registry) == 2


def test_the_settings_secrets_are_known_to_redaction() -> None:
    from pydantic import SecretStr

    from agent_runtime.config import Settings

    token = "settings-sandboxd-token-" + "4" * 16
    Settings(postgres_password="pw", sandboxd_token=SecretStr(token))  # type: ignore[arg-type]
    assert token in known_secrets and "pw" not in known_secrets  # too short to register
    assert redact(f"Authorization: {token}") == f"Authorization: {REDACTED}"


def test_an_opened_secret_is_known_to_redaction() -> None:
    from agent_runtime.keys import LocalKek, open_secret, seal

    kek = LocalKek("k" * 40)
    key = "opened-model-key-" + "9" * 24
    assert open_secret(seal(key, "ws:row:test", kek), "ws:row:test", kek) == key
    assert key in known_secrets and redact({"result": key}) == {"result": REDACTED}
