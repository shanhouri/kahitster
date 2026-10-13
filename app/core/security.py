"""Who is a host.

Players are anonymous. A host is someone who signed in with Spotify: the login
sets a signed cookie naming their account, and everything that edits quizzes,
touches Spotify or drives a game requires it. Spotify itself decides who may
sign in -- only the people listed under the app's User Management.
"""
import hashlib
import hmac
import time
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.core.config import secret_key
from app.core.database import get_session
from app.models import Account

COOKIE = "kahitster_host"
SESSION_SECONDS = 30 * 24 * 60 * 60


def _signature(payload: str) -> str:
    return hmac.new(secret_key(), payload.encode(), hashlib.sha256).hexdigest()


def make_session(account_id: int) -> str:
    payload = f"{account_id}.{int(time.time()) + SESSION_SECONDS}"
    return f"{payload}.{_signature(payload)}"


def read_session(value: str | None) -> int | None:
    """The account id a cookie vouches for, or None if it is forged or stale."""
    try:
        account_id, expires, signature = (value or "").split(".")
        payload = f"{account_id}.{expires}"
        if not hmac.compare_digest(signature, _signature(payload)):
            return None
        return int(account_id) if int(expires) > time.time() else None
    except ValueError:
        return None


def session_account_id(conn: HTTPConnection) -> int | None:
    return read_session(conn.cookies.get(COOKIE))


def same_origin(conn: HTTPConnection) -> bool:
    """False when another website made the host's browser send this.

    Browsers attach Origin to cross-site writes and to every WebSocket; a
    request without one is a plain page load or not from a browser at all.
    """
    origin = conn.headers.get("origin")
    return not origin or urlparse(origin).netloc == conn.headers.get("host")


async def account_for(conn: HTTPConnection, session: AsyncSession) -> Account | None:
    account_id = session_account_id(conn) if same_origin(conn) else None
    return await session.get(Account, account_id) if account_id else None


async def current_host(
    conn: HTTPConnection, session: AsyncSession = Depends(get_session)
) -> Account:
    account = await account_for(conn, session)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in with Spotify to host",
        )
    return account
