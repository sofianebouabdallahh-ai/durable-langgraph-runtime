"""The Standard Webhooks wire format and the retry schedule (phase H4)."""

import base64
import hashlib
import hmac
import time

from agent_runtime.notifications.delivery import (
    BACKOFF_CAP_S,
    backoff_s,
    sign,
    signing_key,
    verify,
)

SECRET = "whsec_" + base64.b64encode(b"a-very-secret-key-32-bytes-long!").decode()


def test_a_whsec_secret_is_base64_decoded_as_the_spec_says() -> None:
    assert signing_key(SECRET) == b"a-very-secret-key-32-bytes-long!"
    assert signing_key("plain") == b"plain"


def test_the_signature_is_hmac_sha256_over_id_timestamp_body() -> None:
    key, body = signing_key(SECRET), b'{"type":"notification.created"}'
    mac = hmac.new(key, b"msg_1.1700000000." + body, hashlib.sha256).digest()
    assert sign(key, "msg_1", 1700000000, body) == "v1," + base64.b64encode(mac).decode()


def test_a_receiver_verifies_it_and_refuses_tampering_and_replays() -> None:
    key, body, now = signing_key(SECRET), b'{"a":1}', int(time.time())
    headers = {"Webhook-Id": "msg_1", "Webhook-Timestamp": str(now),
               "Webhook-Signature": sign(key, "msg_1", now, body)}  # fmt: skip
    assert verify(key, headers, body)
    assert not verify(key, headers, b'{"a":2}')  # the body changed
    assert not verify(signing_key("whsec_" + base64.b64encode(b"other").decode()), headers, body)
    old = now - 3600
    resigned = sign(key, "msg_1", old, body)
    stale = headers | {"Webhook-Timestamp": str(old), "Webhook-Signature": resigned}
    assert not verify(key, stale, body)  # a replay, an hour later
    rotated = headers | {"Webhook-Signature": "v1,bm9wZQ== " + headers["Webhook-Signature"]}
    assert verify(key, rotated, body)  # any of the offered signatures (key rotation)


def test_retries_back_off_exponentially_up_to_an_hour() -> None:
    assert [backoff_s(n) for n in (1, 2, 3, 4)] == [5.0, 10.0, 20.0, 40.0]
    assert backoff_s(30) == BACKOFF_CAP_S
