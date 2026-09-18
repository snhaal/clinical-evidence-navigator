"""Unit tests for Supabase JWT authentication layer in app.auth."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
import pytest
from fastapi import HTTPException

from app.auth import (
    User,
    decode_access_token,
    get_optional_user,
    get_required_user,
    verify_supabase_token,
)

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


@pytest.mark.asyncio
async def test_verify_supabase_token_success():
    supabase_url = "https://my-test-proj.supabase.co"
    anon_key = "anon-key-12345"
    token = "asymmetric-or-es256-jwt-token"
    mock_resp_data = {
        "id": TEST_USER_ID,
        "email": TEST_EMAIL,
        "aud": "authenticated",
        "role": "authenticated",
    }

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_resp_data
        mock_get.return_value = mock_resp

        result = await verify_supabase_token(token, supabase_url, anon_key)

    assert result["id"] == TEST_USER_ID
    assert result["email"] == TEST_EMAIL
    mock_get.assert_called_once_with(
        "https://my-test-proj.supabase.co/auth/v1/user",
        headers={
            "Authorization": f"Bearer {token}",
            "apikey": anon_key,
        },
    )


@pytest.mark.asyncio
async def test_verify_supabase_token_invalid_raises_401():
    supabase_url = "https://my-test-proj.supabase.co"
    anon_key = "anon-key-12345"

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"msg": "Invalid JWT"}
        mock_get.return_value = mock_resp

        with pytest.raises(HTTPException) as exc_info:
            await verify_supabase_token("invalid-tok", supabase_url, anon_key)

    assert exc_info.value.status_code == 401
    assert "invalid" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_verify_supabase_token_expired_raises_401():
    supabase_url = "https://my-test-proj.supabase.co"
    anon_key = "anon-key-12345"

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"msg": "Token expired"}
        mock_get.return_value = mock_resp

        with pytest.raises(HTTPException) as exc_info:
            await verify_supabase_token("expired-tok", supabase_url, anon_key)

    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_verify_supabase_token_network_error_raises_401():
    supabase_url = "https://my-test-proj.supabase.co"
    anon_key = "anon-key-12345"

    with (
        patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Network unreachable")),
        pytest.raises(HTTPException) as exc_info,
    ):
        await verify_supabase_token("some-tok", supabase_url, anon_key)

    assert exc_info.value.status_code == 401
    assert "unable to verify" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_verify_supabase_token_missing_config_raises_401():
    with pytest.raises(HTTPException) as exc_info:
        await verify_supabase_token("some-tok", "", "")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_optional_user_asymmetric_es256_via_supabase_auth():
    es256_token = "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9.asymmetric.signature"
    request = MagicMock()
    request.headers.get.return_value = f"Bearer {es256_token}"

    mock_user_data = {
        "id": "e0b2069b-3ee7-4185-9337-3316687483b4",
        "email": "asymmetric.user@hospital.org",
    }

    with (
        patch("app.auth.get_settings") as mock_settings,
        patch("app.auth.verify_supabase_token", new_callable=AsyncMock) as mock_verify,
    ):
        mock_settings.return_value.supabase_url = "https://test.supabase.co"
        mock_settings.return_value.supabase_anon_key = "anon-123"
        mock_verify.return_value = mock_user_data

        user = await get_optional_user(request)

    assert user is not None
    assert user.id == "e0b2069b-3ee7-4185-9337-3316687483b4"
    assert user.email == "asymmetric.user@hospital.org"
    mock_verify.assert_called_once_with(
        token=es256_token,
        supabase_url="https://test.supabase.co",
        supabase_anon_key="anon-123",
    )

