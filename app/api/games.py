"""Starting a game from a quiz, and letting players into it."""
import io

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.quizzes import load_quiz
from app.core.config import public_base_url
from app.core.database import get_session
from app.core.security import current_host
from app.integrations import spotify
from app.models import Account
from app.schemas import DeviceChoice, GameCreate, JoinIn
from app.services import game as games
from app.services.playback import SpotifyPlayback

router = APIRouter(prefix="/api")

_SONG_FIELDS = (
    "spotify_id", "title", "artists", "album", "image_url", "duration_ms",
    "year", "extra_titles", "extra_artists",
)


def _game_or_404(pin: str) -> games.Game:
    game = games.get_game(pin)
    if game is None:
        raise HTTPException(status_code=404, detail="No game with that PIN")
    return game


def _own_game(pin: str, host: Account = Depends(current_host)) -> games.Game:
    game = games.get_game(pin)
    # Someone else's game looks the same as no game.
    if game is None or game.owner_id != host.id:
        raise HTTPException(status_code=404, detail="No game with that PIN")
    return game


@router.post("/games")
async def create_game(
    body: GameCreate,
    host: Account = Depends(current_host),
    session: AsyncSession = Depends(get_session),
):
    quiz = await load_quiz(body.quiz_id, host, session)
    if not quiz.songs:
        raise HTTPException(status_code=400, detail="Add some songs to the quiz first")

    # The game works on a copy, so editing the quiz mid-game changes nothing.
    game = games.create_game(
        {
            "name": quiz.name,
            "guess_year": quiz.guess_year,
            "seconds_per_song": quiz.seconds_per_song,
            "start_mode": quiz.start_mode,
        },
        [{key: getattr(song, key) for key in _SONG_FIELDS} for song in quiz.songs],
        owner_id=host.id,
        playback=SpotifyPlayback(host.id),
        join_url=public_base_url(),
    )
    return {"pin": game.pin}


@router.get("/games/{pin}/qr.svg")
async def join_qr(game: games.Game = Depends(_own_game)):
    image = qrcode.make(
        f"{game.join_url}/join/{game.pin}",
        image_factory=qrcode.image.svg.SvgPathImage,
        border=1,
    )
    buffer = io.BytesIO()
    image.save(buffer)
    return Response(buffer.getvalue(), media_type="image/svg+xml")


@router.post("/games/{pin}/device")
async def choose_device(
    body: DeviceChoice,
    game: games.Game = Depends(_own_game),
    session: AsyncSession = Depends(get_session),
):
    """Point the game at a Spotify device, proving we can control it."""
    token = await spotify.access_token(session, game.owner_id)
    await spotify.transfer_playback(token, body.device_id)
    game.device_id = body.device_id
    game.playback_error = None
    await game.broadcast()
    return {"device_id": game.device_id}


@router.post("/join")
async def join(body: JoinIn):
    """The one thing a player does over HTTP: take a seat in a game."""
    game = _game_or_404(body.pin.strip())
    try:
        player = game.add_player(body.name)
    except games.GameError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await game.broadcast()
    return {"pin": game.pin, "token": player.token, "name": player.name}
