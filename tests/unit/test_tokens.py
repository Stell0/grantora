import pytest

from grantora.auth import TOKEN_HASH_ALGORITHM, create_agent_token, hash_token, verify_token


def test_agent_token_creation_returns_single_plaintext_value() -> None:
    first_token = create_agent_token()
    second_token = create_agent_token()

    assert first_token.startswith("grt_agent_")
    assert second_token.startswith("grt_agent_")
    assert first_token != second_token


def test_token_hash_uses_pepper_and_does_not_include_plaintext() -> None:
    plaintext_token = "grt_agent_plaintext"
    token_hash = hash_token(plaintext_token, "pepper-one")

    assert token_hash.startswith(f"{TOKEN_HASH_ALGORITHM}:")
    assert plaintext_token not in token_hash
    assert hash_token(plaintext_token, "pepper-two") != token_hash


def test_token_verification_requires_same_token_and_pepper() -> None:
    token_hash = hash_token("grt_agent_plaintext", "pepper-one")

    assert verify_token("grt_agent_plaintext", token_hash, "pepper-one") is True
    assert verify_token("grt_agent_other", token_hash, "pepper-one") is False
    assert verify_token("grt_agent_plaintext", token_hash, "pepper-two") is False
    assert verify_token("grt_agent_plaintext", "sha256:legacy", "pepper-one") is False


def test_token_hash_rejects_missing_secret_material() -> None:
    with pytest.raises(ValueError):
        hash_token("", "pepper")

    with pytest.raises(ValueError):
        hash_token("grt_agent_plaintext", "")
