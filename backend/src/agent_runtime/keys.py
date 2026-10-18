"""Secrets at rest: envelope encryption with AES-256-GCM (CR-006 R18.3, gap G2).

    plaintext ──AES-GCM(data key, aad)──► ciphertext        stored
    data key  ──AES-GCM(master key, aad)──► wrapped key     stored with it
    master key: never stored with the data (locally: NURIA_SECRET_KEY in .env)

- **A fresh data key per secret,** so one leak exposes one secret, and rotating the
  master key re-wraps small keys rather than re-encrypting data.
- **The AAD binds a ciphertext to its place** (workspace, row, purpose): copied to
  another row or workspace, it fails to decrypt (AC45).
- **The master key is behind a port** (Pattern: Strategy). Locally `LocalKek` derives
  it from `NURIA_SECRET_KEY` (HKDF-SHA256); the hosted beta adds a Key Vault one
  (P8) without changing anything else.
- Plaintext secrets live only in memory, for the call that needs them.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

NONCE_BYTES = 12  # 96-bit nonces: the size AES-GCM is specified for
KEY_BYTES = 32  # AES-256
MIN_SECRET_CHARS = 32


class SecretUnavailable(Exception):
    """A secret that can't be opened: another master key, tampered, or moved."""


class MasterKeyMissing(Exception):
    """No usable master key: secrets can be neither saved nor opened."""


@dataclass(frozen=True, slots=True)
class Sealed:
    ciphertext: bytes
    nonce: bytes
    wrapped_key: bytes
    wrapped_nonce: bytes
    kek_version: int


class KeyEncryptionKey(Protocol):
    """The master key: wraps and unwraps data keys. Never leaves its holder."""

    version: int

    def wrap(self, data_key: bytes, aad: bytes) -> tuple[bytes, bytes]: ...

    def unwrap(self, wrapped: bytes, nonce: bytes, aad: bytes) -> bytes: ...

    def fingerprint_key(self) -> bytes: ...


class LocalKek:
    """The local release's master key, derived from a secret in `.env`."""

    version = 1

    def __init__(self, secret: str) -> None:
        if len(secret) < MIN_SECRET_CHARS or secret.startswith("change-me"):
            raise MasterKeyMissing(
                "NURIA_SECRET_KEY must be a random secret of at least 32 characters "
                "(./setup.sh generates one)"
            )
        material = secret.encode()
        self._key = _derive(material, b"nuria/kek/v1")
        self._fingerprints = _derive(material, b"nuria/fingerprint/v1")

    def wrap(self, data_key: bytes, aad: bytes) -> tuple[bytes, bytes]:
        nonce = os.urandom(NONCE_BYTES)
        return AESGCM(self._key).encrypt(nonce, data_key, aad), nonce

    def unwrap(self, wrapped: bytes, nonce: bytes, aad: bytes) -> bytes:
        try:
            return AESGCM(self._key).decrypt(nonce, wrapped, aad)
        except InvalidTag as exc:
            raise SecretUnavailable("this secret can't be opened with this master key") from exc

    def fingerprint_key(self) -> bytes:
        return self._fingerprints


def _derive(material: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=info).derive(material)


def seal(plaintext: str, aad: str, kek: KeyEncryptionKey) -> Sealed:
    data_key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(NONCE_BYTES)
    context = aad.encode()
    ciphertext = AESGCM(data_key).encrypt(nonce, plaintext.encode(), context)
    wrapped, wrapped_nonce = kek.wrap(data_key, context + b"|data-key")
    return Sealed(ciphertext, nonce, wrapped, wrapped_nonce, kek.version)


def open_secret(sealed: Sealed, aad: str, kek: KeyEncryptionKey) -> str:
    """The plaintext, or SecretUnavailable. Keep it in memory, for one call."""
    context = aad.encode()
    data_key = kek.unwrap(sealed.wrapped_key, sealed.wrapped_nonce, context + b"|data-key")
    try:
        return AESGCM(data_key).decrypt(sealed.nonce, sealed.ciphertext, context).decode()
    except InvalidTag as exc:
        raise SecretUnavailable("this secret was changed or moved") from exc


def fingerprint(plaintext: str, kek: KeyEncryptionKey) -> str:
    """8 hex characters that tell keys apart without revealing them. Keyed (HMAC), so
    a short key can't be guessed offline from its fingerprint."""
    digest = hmac.new(kek.fingerprint_key(), plaintext.encode(), hashlib.sha256).hexdigest()
    return digest[:8]


def secret_aad(workspace: str, row: str, purpose: str) -> str:
    """Where a secret belongs: its ciphertext only opens there."""
    return f"{workspace}:{row}:{purpose}"
