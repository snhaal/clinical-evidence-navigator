"""Unit tests for Supabase JWT authentication layer in app.auth."""

import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException

from app.auth import User, decode_access_token, get_optional_user, get_required_user

TEST_SECRET = "super-secret-test-jwt-key-minimum-32-chars-long"
TEST_USER_ID = "c5b2069b-3ee7-4185-9337-3316687483b4"
TEST_EMAIL = "doctor@example.com"


def _create_token(
    user_id: str = TEST_USER_ID,
    email: str = TEST_EMAIL,
    expires_in: int = 3600,
    secret: str = TEST_SECRET,
) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": "authenticated",
        "aud": "authenticated",
        "exp": int(time.time()) + expires_in,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def test_decode_valid_token():
    token = _create_token()
    payload = decode_access_token(token, TEST_SECRET)
    assert payload["sub"] == TEST_USER_ID
    assert payload["email"] == TEST_EMAIL


def test_decode_expired_token_raises_401():
    token = _create_token(expires_in=-60)
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(token, TEST_SECRET)
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


def test_decode_invalid_signature_raises_401():
    token = _create_token(secret="wrong-secret-key-that-does-not-match")
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(token, TEST_SECRET)
    assert exc_info.value.status_code == 401
    assert "invalid" in exc_info.value.detail.lower()


def test_decode_empty_secret_raises_401():
    token = _create_token()
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(token, "")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_optional_user_missing_header_returns_none():
    request = MagicMock()
    request.headers.get.return_value = None

    user = await get_optional_user(request)
    assert user is None


@pytest.mark.asyncio
async def test_get_optional_user_valid_token():
    token = _create_token()
    request = MagicMock()
    request.headers.get.return_value = f"Bearer {token}"

    with patch("app.auth.get_settings") as mock_settings:
        mock_settings.return_value.supabase_jwt_secret = TEST_SECRET
        user = await get_optional_user(request)

    assert user is not None
    assert user.id == TEST_USER_ID
    assert user.email == TEST_EMAIL


@pytest.mark.asyncio
async def test_get_optional_user_malformed_header():
    request = MagicMock()
    request.headers.get.return_value = "Basic 12345"

    with pytest.raises(HTTPException) as exc_info:
        await get_optional_user(request)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_optional_user_expired_token():
    token = _create_token(expires_in=-10)
    request = MagicMock()
    request.headers.get.return_value = f"Bearer {token}"

    with patch("app.auth.get_settings") as mock_settings:
        mock_settings.return_value.supabase_jwt_secret = TEST_SECRET
        with pytest.raises(HTTPException) as exc_info:
            await get_optional_user(request)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_required_user_authenticated():
    user = User(id=TEST_USER_ID, email=TEST_EMAIL)
    res = await get_required_user(user)
    assert res == user


@pytest.mark.asyncio
async def test_get_required_user_unauthenticated_raises_401():
    with pytest.raises(HTTPException) as exc_info:
        await get_required_user(None)
    assert exc_info.value.status_code == 401
    assert "required" in exc_info.value.detail.lower()
