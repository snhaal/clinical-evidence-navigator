"""
Supabase JWT authentication dependency.

Supports both authenticated users (valid JWT from Supabase Auth)
and anonymous guests (missing Authorization header).
"""

import logging
from typing import Annotated

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)


class User(BaseModel):
    """Authenticated user representation."""

    id: str
    email: str | None = None


def decode_access_token(token: str, secret: str) -> dict:
    """
    Decodes and validates a Supabase HS256 JWT using the project's JWT secret.
    Raises HTTPException(401) on any failure (expired, invalid signature, malformed).
    """
    if not secret:
        logger.error("SUPABASE_JWT_SECRET is not configured on the server.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication service is improperly configured.",
        )
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please sign in again.",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization token.",
        ) from exc


async def verify_supabase_token(
    token: str, supabase_url: str, supabase_anon_key: str
) -> dict:
    """
    Verifies a bearer token with Supabase Auth REST endpoint:
    GET {SUPABASE_URL}/auth/v1/user
    Headers:
      Authorization: Bearer <token>
      apikey: <SUPABASE_ANON_KEY>

    Returns the user JSON object containing 'id', 'email', etc.
    Raises HTTPException(401) on invalid/expired tokens or authentication failure.
    """
    if not supabase_url or not supabase_anon_key:
        logger.error("SUPABASE_URL or SUPABASE_ANON_KEY is not configured on the server.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication service is improperly configured.",
        )

    endpoint = f"{supabase_url.rstrip('/')}/auth/v1/user"
    headers = {
        "Authorization": f"Bearer {token}",
        "apikey": supabase_anon_key,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(endpoint, headers=headers)
    except httpx.RequestError as exc:
        logger.error(f"Failed to connect to Supabase Auth service: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to verify authorization token with authentication service.",
        ) from exc

    if response.status_code == 200:
        return response.json()

    # Parse error message from Supabase Auth response
    detail = "Invalid authorization token."
    try:
        error_body = response.json()
        error_msg = (
            error_body.get("msg")
            or error_body.get("message")
            or error_body.get("error_description")
        )
        if error_msg:
            if "expired" in error_msg.lower():
                detail = "Token has expired. Please sign in again."
            else:
                detail = error_msg
    except Exception:
        pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
    )


async def get_optional_user(request: Request) -> User | None:
    """
    Extracts and validates Supabase JWT from 'Authorization: Bearer <token>' header.
    - If header is missing: returns None (guest mode).
    - If header is present and valid: returns User(id, email).
    - If header is malformed, invalid, or expired: raises HTTP 401 Unauthorized.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None

    parts = auth_header.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must have format 'Bearer <token>'.",
        )

    token = parts[1]
    settings = get_settings()

    has_supabase_service = (
        isinstance(settings.supabase_url, str)
        and bool(settings.supabase_url.strip())
        and isinstance(settings.supabase_anon_key, str)
        and bool(settings.supabase_anon_key.strip())
    )

    # 1. Primary: Verify directly with Supabase Auth REST endpoint (supports asymmetric ES256 and symmetric HS256)
    if has_supabase_service:
        user_data = await verify_supabase_token(
            token=token,
            supabase_url=settings.supabase_url.strip(),
            supabase_anon_key=settings.supabase_anon_key.strip(),
        )
        user_id = user_data.get("id") or user_data.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token does not contain a valid user identity.",
            )
        email = user_data.get("email") or user_data.get("user_metadata", {}).get("email")
        return User(id=str(user_id), email=email)

    # 2. Fallback: Symmetric JWT secret decoding if configured (legacy HS256 / offline tests)
    if settings.supabase_jwt_secret and str(settings.supabase_jwt_secret).strip():
        payload = decode_access_token(token, str(settings.supabase_jwt_secret).strip())
        user_id = payload.get("sub") or payload.get("id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token does not contain a valid user identity.",
            )
        email = payload.get("email") or payload.get("user_metadata", {}).get("email")
        return User(id=str(user_id), email=email)

    logger.error(
        "Authentication service is not configured (missing SUPABASE_URL/SUPABASE_ANON_KEY and SUPABASE_JWT_SECRET)."
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication service is improperly configured.",
    )


async def get_required_user(
    user: Annotated[User | None, Depends(get_optional_user)],
) -> User:
    """
    Strict auth dependency: requires a valid authenticated user,
    raising HTTP 401 Unauthorized for guests.
    """
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to access this resource.",
        )
    return user
