"""Spotify Web API client: OAuth, the host's library, search and playback.

Written against the February 2026 Development Mode API: playlist contents live
under /playlists/{id}/items and are only readable for playlists the user owns
or collaborates on, and search returns at most 10 results per page.
"""
import base64
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import http
from app.core.config import get_settings, redirect_uri
from app.models import Account

settings = get_settings()

ACCOUNTS_BASE = "https://accounts.spotify.com"
API_BASE = "https://api.spotify.com/v1"

SCOPES = [
    "user-library-read",            # Liked Songs
    "playlist-read-private",        # the host's own playlists
    "playlist-read-collaborative",
    "user-read-playback-state",     # list devices
    "user-modify-playback-state",   # play / pause on the chosen device
]

SEARCH_PAGE = 10
LIBRARY_PAGE = 50
PLAYLIST_TRACK_CAP = 500

# Album titles that almost always carry a reissue date rather than the year the
# song came out.
_REISSUE_HINTS = re.compile(
    r"remaster|anniversary|deluxe|expanded|re-?issue|greatest hits|best of|"
    r"essential|collection|anthology|compilation|\bhits\b|edition",
    re.IGNORECASE,
)


# "Under Pressure - Remastered 2011" names a pressing; the song is "Under Pressure".
_PRESSING_SUFFIX = re.compile(
    r"\s*(?:-\s*|[(\[])\s*(?:\d{4}\s+)?(?:digital(?:ly)?\s+)?"
    r"(?:remaster(?:ed)?|mono|stereo|single version|album version|radio edit)\b"
    r"[^)\]]*[)\]]?\s*$",
    re.IGNORECASE,
)


class SpotifyError(RuntimeError):
    """Spotify refused a request in a way worth showing to the host."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


# --- OAuth -------------------------------------------------------------------

def is_configured() -> bool:
    return bool(settings.spotify_client_id and settings.spotify_client_secret)


def authorize_url(state: str) -> str:
    if not is_configured():
        raise SpotifyError("Spotify keys are missing; see .env.example", status=500)
    params = {
        "client_id": settings.spotify_client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "scope": " ".join(SCOPES),
        "state": state,
        # Always offer the account chooser: on a shared computer the next host
        # must not be silently signed in as the previous one.
        "show_dialog": "true",
    }
    return f"{ACCOUNTS_BASE}/authorize?{urlencode(params)}"


async def _token_request(payload: dict) -> dict:
    raw = f"{settings.spotify_client_id}:{settings.spotify_client_secret}"
    resp = await http.get_client().post(
        f"{ACCOUNTS_BASE}/api/token",
        data=payload,
        headers={"Authorization": f"Basic {base64.b64encode(raw.encode()).decode()}"},
    )
    if resp.status_code >= 400:
        raise SpotifyError(f"Spotify login failed ({resp.status_code}): {resp.text}")
    return resp.json()


async def exchange_code(code: str) -> dict:
    return await _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(),
        }
    )


def expires_at(expires_in: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in)


async def access_token(session: AsyncSession, account_id: int) -> str:
    """A usable token for a host's account, refreshed and saved if stale."""
    account = await session.get(Account, account_id)
    if account is None:
        raise SpotifyError("Spotify is not connected", status=401)

    expiry = account.token_expires_at
    if expiry.tzinfo is None:
        # SQLite hands back naive datetimes; they were stored as UTC.
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry - timedelta(seconds=60) > datetime.now(timezone.utc):
        return account.access_token

    data = await _token_request(
        {"grant_type": "refresh_token", "refresh_token": account.refresh_token}
    )
    account.access_token = data["access_token"]
    # Spotify only sometimes rotates the refresh token.
    account.refresh_token = data.get("refresh_token") or account.refresh_token
    account.token_expires_at = expires_at(data.get("expires_in", 3600))
    await session.commit()
    return account.access_token


# --- Requests ----------------------------------------------------------------

async def _request(token: str, method: str, url: str, *, json=None, **params):
    resp = await http.get_client().request(
        method,
        url if url.startswith("http") else f"{API_BASE}{url}",
        params=params or None,
        json=json,
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code >= 400:
        raise SpotifyError(_explain(resp.status_code, method, url, resp.text), resp.status_code)
    return resp.json() if resp.content else None


def _explain(status: int, method: str, url: str, body: str) -> str:
    if "/me/player" in url:
        if status == 404:
            return (
                "No active Spotify device. Open Spotify on the speaker or phone "
                "and play something for a second, then try again."
            )
        if status == 403:
            return "Spotify refused playback control. This needs Spotify Premium."
    if status == 429:
        return "Spotify is rate-limiting requests; wait a moment and try again."
    return f"Spotify {method} {url} failed ({status}): {body[:200]}"


async def current_user(token: str) -> dict:
    return await _request(token, "GET", "/me")


# --- Library -----------------------------------------------------------------

def _year(date_str: str | None) -> int | None:
    match = re.match(r"(\d{4})", date_str or "")
    return int(match.group(1)) if match else None


def track_to_song(track: dict | None) -> dict | None:
    """Reduce a Spotify track object to the fields a quiz stores.

    Returns None for entries that cannot be quiz songs: local files, podcast
    episodes, or anything without an id.
    """
    if not track or not track.get("id") or track.get("is_local"):
        return None
    if track.get("type", "track") != "track":
        return None

    album = track.get("album") or {}
    images = album.get("images") or []
    year = _year(album.get("release_date"))
    name = track.get("name", "")
    return {
        "spotify_id": track["id"],
        "title": _PRESSING_SUFFIX.sub("", name).strip() or name,
        "artists": [a["name"] for a in track.get("artists", []) if a and a.get("name")],
        "album": album.get("name", ""),
        # Images come largest first; the middle one suits both list and reveal.
        "image_url": images[min(1, len(images) - 1)]["url"] if images else "",
        "duration_ms": track.get("duration_ms") or 0,
        "year": year,
        "year_suspect": year is None or bool(_REISSUE_HINTS.search(album.get("name", ""))),
    }


def _songs(items: list[dict]) -> list[dict]:
    # Playlist entries carry the track under "item" (2026 API) or "track".
    songs = (track_to_song(entry.get("item") or entry.get("track")) for entry in items if entry)
    return [song for song in songs if song]


async def my_playlists(token: str, user_id: str) -> list[dict]:
    playlists: list[dict] = []
    url: str | None = "/me/playlists"
    params = {"limit": LIBRARY_PAGE}
    while url:
        page = await _request(token, "GET", url, **params)
        for item in page.get("items") or []:
            if not item:
                continue
            contents = item.get("items") or item.get("tracks") or {}
            images = item.get("images") or []
            playlists.append(
                {
                    "id": item["id"],
                    "name": item.get("name", ""),
                    "image_url": images[-1]["url"] if images else "",
                    "total": contents.get("total", 0),
                    "readable": (item.get("owner") or {}).get("id") == user_id
                    or bool(item.get("collaborative")),
                }
            )
        url, params = page.get("next"), {}  # `next` already carries limit/offset
    return playlists


async def playlist_songs(token: str, playlist_id: str) -> list[dict]:
    songs: list[dict] = []
    url: str | None = f"/playlists/{playlist_id}/items"
    params = {"limit": LIBRARY_PAGE}
    while url and len(songs) < PLAYLIST_TRACK_CAP:
        try:
            page = await _request(token, "GET", url, **params)
        except SpotifyError as exc:
            if exc.status == 403:
                raise SpotifyError(
                    "Spotify only lets this app read playlists you own or "
                    "collaborate on.",
                    status=403,
                ) from exc
            raise
        songs.extend(_songs(page.get("items") or []))
        url, params = page.get("next"), {}
    return songs[:PLAYLIST_TRACK_CAP]


async def liked_songs(token: str, offset: int = 0) -> dict:
    page = await _request(token, "GET", "/me/tracks", limit=LIBRARY_PAGE, offset=offset)
    return {
        "songs": _songs(page.get("items") or []),
        "next_offset": offset + LIBRARY_PAGE if page.get("next") else None,
    }


async def search_songs(token: str, query: str, offset: int = 0) -> dict:
    page = await _request(
        token, "GET", "/search", q=query, type="track", limit=SEARCH_PAGE, offset=offset
    )
    tracks = page.get("tracks") or {}
    return {
        "songs": [song for song in map(track_to_song, tracks.get("items") or []) if song],
        "next_offset": offset + SEARCH_PAGE if tracks.get("next") else None,
    }


# --- Playback ----------------------------------------------------------------

async def list_devices(token: str) -> list[dict]:
    data = await _request(token, "GET", "/me/player/devices")
    return [
        {
            "id": d["id"],
            "name": d.get("name", ""),
            "type": d.get("type", ""),
            "is_active": bool(d.get("is_active")),
        }
        for d in (data or {}).get("devices", [])
        if d.get("id")
    ]


async def transfer_playback(token: str, device_id: str) -> None:
    """Make a device the active one without starting any music."""
    await _request(token, "PUT", "/me/player", json={"device_ids": [device_id], "play": False})


async def start_track(
    token: str, spotify_id: str, position_ms: int = 0, device_id: str | None = None
) -> None:
    params = {"device_id": device_id} if device_id else {}
    await _request(
        token,
        "PUT",
        "/me/player/play",
        json={"uris": [f"spotify:track:{spotify_id}"], "position_ms": position_ms},
        **params,
    )


async def pause(token: str) -> None:
    try:
        await _request(token, "PUT", "/me/player/pause")
    except SpotifyError as exc:
        # Pausing something already paused (403) or with no device (404) is fine.
        if exc.status not in (403, 404):
            raise
