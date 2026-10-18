"""Secrets at rest (phase L3b, R18.3, AC45): envelope encryption bound to its place."""

import dataclasses

import pytest

from agent_runtime.keys import (
    LocalKek,
    MasterKeyMissing,
    SecretUnavailable,
    fingerprint,
    open_secret,
    seal,
    secret_aad,
)

KEK = LocalKek("a" * 16 + "0123456789abcdef0123456789")
HERE = secret_aad("local", "conn-1", "api-key")


def test_a_sealed_secret_opens_only_where_it_belongs() -> None:
    sealed = seal("sk-test-123", HERE, KEK)
    assert b"sk-test-123" not in sealed.ciphertext + sealed.wrapped_key
    assert open_secret(sealed, HERE, KEK) == "sk-test-123"
    for elsewhere in (secret_aad("local", "conn-2", "api-key"),
                      secret_aad("other-workspace", "conn-1", "api-key"),
                      secret_aad("local", "conn-1", "something-else")):  # fmt: skip
        with pytest.raises(SecretUnavailable):
            open_secret(sealed, elsewhere, KEK)  # copied to another place: refused


def test_tampering_and_another_master_key_are_refused() -> None:
    sealed = seal("sk-test-123", HERE, KEK)
    flipped = bytes([sealed.ciphertext[0] ^ 1]) + sealed.ciphertext[1:]
    with pytest.raises(SecretUnavailable):
        open_secret(dataclasses.replace(sealed, ciphertext=flipped), HERE, KEK)
    with pytest.raises(SecretUnavailable):
        open_secret(sealed, HERE, LocalKek("b" * 40))


def test_every_seal_is_different_but_the_fingerprint_is_stable() -> None:
    a, b = seal("sk-same", HERE, KEK), seal("sk-same", HERE, KEK)
    assert a.ciphertext != b.ciphertext and a.nonce != b.nonce  # fresh data key and nonce
    assert fingerprint("sk-same", KEK) == fingerprint("sk-same", KEK)
    assert fingerprint("sk-same", KEK) != fingerprint("sk-other", KEK)
    assert fingerprint("sk-same", KEK) != fingerprint("sk-same", LocalKek("c" * 40))  # keyed
    assert len(fingerprint("sk-same", KEK)) == 8


@pytest.mark.parametrize("secret", ["", "short", "change-me-generated-by-setup-xxxxxxxxxxxx"])
def test_a_weak_or_placeholder_master_key_is_refused(secret: str) -> None:
    with pytest.raises(MasterKeyMissing, match=r"setup\.sh"):
        LocalKek(secret)
