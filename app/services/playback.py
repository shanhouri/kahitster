"""Bridges a live game to its host's Spotify account."""
from app.core.database import SessionLocal
from app.integrations import spotify


class SpotifyPlayback:
    """Plays on the host's device. Opens its own DB session per call, since a
    game outlives any single request."""

    def __init__(self, account_id: int):
        self.account_id = account_id

    async def _token(self) -> str:
        async with SessionLocal() as session:
            return await spotify.access_token(session, self.account_id)

    async def play(self, spotify_id: str, position_ms: int, device_id: str | None) -> None:
        await spotify.start_track(await self._token(), spotify_id, position_ms, device_id)

    async def pause(self) -> None:
        await spotify.pause(await self._token())
