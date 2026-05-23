from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import jwt as pyjwt
import httpx
import os
from dotenv import load_dotenv
from app.db.deps import get_db
from app.db.models import User
from uuid import UUID

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_JWT_SECRET = os.getenv('SUPABASE_JWT_SECRET')

security = HTTPBearer()

_jwks_cache = None


async def get_jwks():
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json")
        _jwks_cache = res.json()
    return _jwks_cache


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials

    try:
        print("======DECODING TOKEN========")
        jwks = await get_jwks()

        # get the kid from token header to find the right key
        unverified_header = pyjwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        alg = unverified_header.get("alg")

        print(f"Token alg: {alg}, kid: {kid}")

        # find matching key from JWKS
        matching_key = next(
            (k for k in jwks["keys"] if k["kid"] == kid),
            None
        )

        if not matching_key:
            raise HTTPException(status_code=401, detail="No matching key found")

        # load the correct key type based on algorithm
        if alg == "RS256":
            public_key = pyjwt.algorithms.RSAAlgorithm.from_jwk(matching_key)
        elif alg == "ES256":
            public_key = pyjwt.algorithms.ECAlgorithm.from_jwk(matching_key)
        else:
            raise HTTPException(status_code=401, detail=f"Unsupported algorithm: {alg}")

        payload = pyjwt.decode(
            token,
            public_key,
            algorithms=[alg],
            options={"verify_aud": False},
        )

        print("Payload:", payload)

        user_id: str = payload.get("sub")
        email: str = payload.get("email", "")

        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")

    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError as e:
        print("JWT Error:", e)
        raise HTTPException(status_code=401, detail="Could not validate token")

    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()

    return user