"""
Supabase JWT authentication dependency.

Supports both authenticated users (valid JWT from Supabase Auth)
and anonymous guests (missing Authorization header).
"""

import logging
from typing import Annotated

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
    payload = decode_access_token(token, settings.supabase_jwt_secret)

    # Supabase standard sub claim contains the user UUID
    user_id = payload.get("sub") or payload.get("id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token does not contain a valid user identity.",
        )

    email = payload.get("email") or payload.get("user_metadata", {}).get("email")
    return User(id=str(user_id), email=email)


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
