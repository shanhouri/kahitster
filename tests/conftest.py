import os
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Must be set before anything imports app.core.config: tests get their own
# empty database and never see the real .env's Spotify keys.
_tmp = Path(tempfile.mkdtemp(prefix="kahitster-tests-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["SPOTIFY_CLIENT_ID"] = "test-client"
os.environ["SPOTIFY_CLIENT_SECRET"] = "test-secret"
os.environ["SPOTIFY_REDIRECT_URI"] = ""
os.environ["PUBLIC_BASE_URL"] = "https://kahitster.example"
os.environ["RENDER_EXTERNAL_URL"] = ""
os.environ["SECRET_KEY"] = "test-signing-key"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import COOKIE  # noqa: E402
from app.integrations import spotify  # noqa: E402
from app.main import app  # noqa: E402

# The test client dials WebSockets at "testserver" whatever its base URL; say
# where a browser would really be connecting so the same-origin check has
# something to compare.
SITE = "kahitster.example"


@pytest.fixture(scope="session")
def client():
    """One client for the whole run.

    A single instance keeps every request and WebSocket on one event loop,
    which the in-memory games and the DB connection pool both rely on. It
    carries no cookies: tests say who they are per request.
    """
    with TestClient(app, base_url=f"https://{SITE}") as c:
        yield c


@pytest.fixture(autouse=True)
def no_spotify_playback(monkeypatch):
    """Games started through the API would otherwise call the real Spotify."""

    async def offline(*args, **kwargs):
        raise spotify.SpotifyError("Spotify is offline in tests")

    monkeypatch.setattr(spotify, "start_track", offline)
    monkeypatch.setattr(spotify, "pause", offline)
    monkeypatch.setattr(spotify, "list_devices", offline)


def sign_in(client, monkeypatch, user_id: str) -> dict:
    """Walk the real login flow with Spotify stubbed out; return auth headers."""

    async def exchange_code(code):
        return {"access_token": f"access-{user_id}", "refresh_token": "r", "expires_in": 3600}

    async def current_user(token):
        return {"id": user_id, "display_name": user_id.title()}

    monkeypatch.setattr(spotify, "exchange_code", exchange_code)
    monkeypatch.setattr(spotify, "current_user", current_user)

    to_spotify = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(to_spotify.headers["location"]).query)["state"][0]
    back = client.get(f"/auth/callback?code=x&state={state}", follow_redirects=False)
    assert back.status_code == 307, back.text
    cookie = back.cookies[COOKIE]
    client.cookies.clear()
    return {"cookie": f"{COOKIE}={cookie}", "host": SITE}


@pytest.fixture
def host(client, monkeypatch) -> dict:
    return sign_in(client, monkeypatch, "itamar")


@pytest.fixture
def other_host(client, monkeypatch) -> dict:
    return sign_in(client, monkeypatch, "someone-else")


def song(n: int = 1, **overrides) -> dict:
    return {
        "spotify_id": f"id{n}",
        "title": f"Song {n}",
        "artists": [f"Artist {n}"],
        "album": "Album",
        "image_url": "",
        "duration_ms": 200_000,
        "year": 1990 + n,
        "year_suspect": False,
    } | overrides
