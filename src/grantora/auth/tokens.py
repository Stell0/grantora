from __future__ import annotations

import hashlib
import hmac
import secrets

AGENT_TOKEN_PREFIX = "grt_agent_"
TOKEN_HASH_ALGORITHM = "hmac-sha256"
TOKEN_HASH_PREFIX = f"{TOKEN_HASH_ALGORITHM}:"


def create_agent_token() -> str:
    return f"{AGENT_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def hash_token(plaintext_token: str, pepper: str) -> str:
    if not plaintext_token:
        raise ValueError("plaintext_token must not be empty")
    if not pepper:
        raise ValueError("pepper must not be empty")

    digest = hmac.new(
        pepper.encode("utf-8"),
        plaintext_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{TOKEN_HASH_PREFIX}{digest}"


def verify_token(plaintext_token: str, stored_hash: str, pepper: str) -> bool:
    if not stored_hash.startswith(TOKEN_HASH_PREFIX):
        return False

    try:
        expected_hash = hash_token(plaintext_token, pepper)
    except ValueError:
        return False

    return hmac.compare_digest(expected_hash, stored_hash)
