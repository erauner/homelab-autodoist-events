import base64
import hashlib
import hmac

from todoist_automation_shared.webhook import verify_todoist_signature


def test_verify_todoist_signature_base64() -> None:
    secret = "abc123"
    raw = b'{"hello":"world"}'
    sig = base64.b64encode(hmac.new(secret.encode(), raw, hashlib.sha256).digest()).decode()
    assert verify_todoist_signature(raw, sig, client_secret=secret)


def test_verify_todoist_signature_rejects_bad() -> None:
    assert not verify_todoist_signature(b"{}", "bad", client_secret="secret")
