"""Spotify login. Signing in is what makes someone a host; players never do."""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import is_https
from app.core.database import get_session
from app.core.security import COOKIE, SESSION_SECONDS, account_for, make_session
from app.integrations import spotify
from app.models import Account, Quiz

router = APIRouter()

# Short-lived CSRF states for the redirect round-trip. In-process is fine: the
# flow starts and finishes against this same server.
_pending_states: set[str] = set()


@router.get("/auth/login")
async def login():
    """Send the browser to Spotify's consent screen."""
    state = secrets.token_urlsafe(16)
    _pending_states.add(state)
    return RedirectResponse(spotify.authorize_url(state))


@router.get("/auth/callback")
async def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    if error:
        raise HTTPException(status_code=400, detail=f"Spotify denied access: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    if state not in _pending_states:
        raise HTTPException(status_code=400, detail="Unknown or expired login attempt")
    _pending_states.discard(state)

    tokens = await spotify.exchange_code(code)
    profile = await spotify.current_user(tokens["access_token"])

    account = await session.scalar(
        select(Account).where(Account.spotify_user_id == profile["id"])
    )
    if account is None:
        account = Account(spotify_user_id=profile["id"], refresh_token="")
        session.add(account)
    account.display_name = profile.get("display_name") or profile["id"]
    account.access_token = tokens["access_token"]
    # Spotify omits the refresh token when re-approving; keep the one we have.
    account.refresh_token = tokens.get("refresh_token") or account.refresh_token
    account.token_expires_at = spotify.expires_at(tokens.get("expires_in", 3600))
    await session.flush()

    # Quizzes from before hosts had accounts belong to whoever shows up first.
    await session.execute(
        update(Quiz).where(Quiz.owner_id.is_(None)).values(owner_id=account.id)
    )
    await session.commit()

    response = RedirectResponse("/")
    response.set_cookie(
        COOKIE,
        make_session(account.id),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=is_https(),
    )
    return response


@router.get("/api/me")
async def me(request: Request, session: AsyncSession = Depends(get_session)):
    account = await account_for(request, session)
    return {
        "configured": spotify.is_configured(),
        "connected": account is not None,
        "display_name": account.display_name if account else None,
    }


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    response.delete_cookie(COOKIE)
