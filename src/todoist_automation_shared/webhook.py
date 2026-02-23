import base64
import hashlib
import hmac
from typing import Optional


def parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_csv_set(value: Optional[str]) -> set[str]:
    if not value:
        return set()
    return {part.strip() for part in value.split(",") if part.strip()}


def verify_todoist_signature(raw_body: bytes, header_sig: str, *, client_secret: str) -> bool:
    """Verify Todoist webhook signature over raw body.

    Accepts base64 format (Todoist docs) and hex fallback.
    """
    if not header_sig:
        return False

    digest = hmac.new(client_secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected_b64 = base64.b64encode(digest).decode("utf-8")
    expected_hex = digest.hex()
    header = header_sig.strip()

    return hmac.compare_digest(header, expected_b64) or hmac.compare_digest(header, expected_hex)
