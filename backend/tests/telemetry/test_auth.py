"""Tests for JWT signing-secret handling in telemetry.auth.

The JWT signing secret must never fall back to the public placeholder that the
project docs publish. When it is missing or equal to that placeholder, the
module must refuse to issue or accept tokens.
"""

import pytest
from jose import jwt

from telemetry import auth


def test_missing_secret_refuses_to_issue_tokens(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        auth.create_access_token({"sub": "1"})


def test_placeholder_secret_refuses_to_issue_and_accept_tokens(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", auth.JWT_SECRET_PLACEHOLDER)
    with pytest.raises(RuntimeError):
        auth.create_access_token({"sub": "1"})
    with pytest.raises(RuntimeError):
        auth.decode_access_token("any.token.value")


def test_token_forged_with_placeholder_is_rejected(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "a-real-non-default-secret")
    forged = jwt.encode(
        {"sub": "attacker-chosen-id"},
        auth.JWT_SECRET_PLACEHOLDER,
        algorithm=auth.ALGORITHM,
    )
    assert auth.decode_access_token(forged) is None


def test_token_signed_with_configured_secret_is_accepted(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "a-real-non-default-secret")
    token = auth.create_access_token({"sub": "42"})
    payload = auth.decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
