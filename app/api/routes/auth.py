import os
import logging
from uuid import UUID
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import jwt as pyjwt
import httpx

from app.db.deps import get_db
from app.db.models import User

load_dotenv()

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

router = APIRouter()
security = HTTPBearer()

_jwks_cache: dict | None = None


async def get_jwks(force_refresh: bool = False) -> dict:
    global _jwks_cache
    if _jwks_cache and not force_refresh:
        return _jwks_cache
    if not SUPABASE_URL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SUPABASE_URL configuration is missing",
        )
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.get(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json")
        res.raise_for_status()
        _jwks_cache = res.json()
    return _jwks_cache


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials

    try:
        jwks = await get_jwks()

        unverified_header = pyjwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        alg = unverified_header.get("alg", "RS256")

        matching_key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if not matching_key:
            # Refresh JWKS in case keys rotated
            jwks = await get_jwks(force_refresh=True)
            matching_key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)

        if not matching_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No matching key found in JWKS",
            )

        if alg == "RS256":
            public_key = pyjwt.algorithms.RSAAlgorithm.from_jwk(matching_key)
        elif alg == "ES256":
            public_key = pyjwt.algorithms.ECAlgorithm.from_jwk(matching_key)
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Unsupported algorithm: {alg}",
            )

        payload = pyjwt.decode(
            token,
            public_key,
            algorithms=[alg],
            options={"verify_aud": False},
        )

        user_id_str: str | None = payload.get("sub")
        email: str = payload.get("email", "")

        if not user_id_str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing subject",
            )

        user_uuid = UUID(user_id_str)

    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except pyjwt.InvalidTokenError as e:
        logger.warning(f"JWT validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate token",
        )
    except Exception as e:
        logger.warning(f"Authentication processing error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
        )

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()

    # Auto-provision user if authenticated by Supabase but not yet in PostgreSQL
    if not user:
        user = User(id=user_uuid, email=email)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return user


@router.get("/auth/me")
async def me(user: User = Depends(get_current_user)):
    return {
        "id": str(user.id),
        "email": user.email,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }