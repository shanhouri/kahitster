"""Building quizzes: CRUD, and browsing the host's Spotify for songs to add.

Every route here needs a signed-in host, and a host only ever sees their own
quizzes -- someone else's id answers 404, same as one that does not exist.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_session
from app.core.security import current_host
from app.integrations import spotify
from app.models import Account, Quiz, QuizSong
from app.schemas import (
    QuizCreate,
    QuizOut,
    QuizSummary,
    QuizUpdate,
    Reorder,
    SongOut,
    SongsIn,
    SongUpdate,
)

router = APIRouter(prefix="/api", dependencies=[Depends(current_host)])

MAX_EXTRA_ANSWERS = 10


async def load_quiz(
    quiz_id: int,
    host: Account = Depends(current_host),
    session: AsyncSession = Depends(get_session),
) -> Quiz:
    quiz = await session.scalar(
        select(Quiz)
        .where(Quiz.id == quiz_id, Quiz.owner_id == host.id)
        .options(selectinload(Quiz.songs))
    )
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return quiz


# --- Quizzes -----------------------------------------------------------------

@router.get("/quizzes", response_model=list[QuizSummary])
async def list_quizzes(
    host: Account = Depends(current_host), session: AsyncSession = Depends(get_session)
):
    rows = await session.execute(
        select(Quiz.id, Quiz.name, func.count(QuizSong.id))
        .outerjoin(QuizSong)
        .where(Quiz.owner_id == host.id)
        .group_by(Quiz.id)
        .order_by(Quiz.created_at.desc())
    )
    return [QuizSummary(id=id_, name=name, song_count=count) for id_, name, count in rows]


@router.post("/quizzes", response_model=QuizOut, status_code=status.HTTP_201_CREATED)
async def create_quiz(
    body: QuizCreate,
    host: Account = Depends(current_host),
    session: AsyncSession = Depends(get_session),
):
    quiz = Quiz(name=body.name.strip(), owner_id=host.id, songs=[])
    session.add(quiz)
    await session.commit()
    return quiz


@router.get("/quizzes/{quiz_id}", response_model=QuizOut)
async def get_quiz(quiz: Quiz = Depends(load_quiz)):
    return quiz


@router.patch("/quizzes/{quiz_id}", response_model=QuizOut)
async def update_quiz(
    body: QuizUpdate,
    quiz: Quiz = Depends(load_quiz),
    session: AsyncSession = Depends(get_session),
):
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(quiz, key, value)
    await session.commit()
    return quiz


@router.delete("/quizzes/{quiz_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quiz(quiz: Quiz = Depends(load_quiz), session: AsyncSession = Depends(get_session)):
    await session.delete(quiz)
    await session.commit()


# --- Songs in a quiz ---------------------------------------------------------

@router.post("/quizzes/{quiz_id}/songs")
async def add_songs(
    body: SongsIn,
    quiz: Quiz = Depends(load_quiz),
    session: AsyncSession = Depends(get_session),
):
    """Append songs, skipping any the quiz already has."""
    present = {song.spotify_id for song in quiz.songs}
    position = max((song.position for song in quiz.songs), default=-1) + 1
    added = 0
    for song in body.songs:
        if song.spotify_id in present:
            continue
        present.add(song.spotify_id)
        quiz.songs.append(QuizSong(position=position, **song.model_dump()))
        position += 1
        added += 1
    await session.commit()
    return {"added": added, "skipped": len(body.songs) - added}


@router.put("/quizzes/{quiz_id}/order", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_songs(
    body: Reorder,
    quiz: Quiz = Depends(load_quiz),
    session: AsyncSession = Depends(get_session),
):
    if sorted(body.song_ids) != sorted(song.id for song in quiz.songs):
        raise HTTPException(status_code=400, detail="Order must list every song once")
    positions = {song_id: position for position, song_id in enumerate(body.song_ids)}
    for song in quiz.songs:
        song.position = positions[song.id]
    await session.commit()


async def _load_song(
    song_id: int,
    host: Account = Depends(current_host),
    session: AsyncSession = Depends(get_session),
) -> QuizSong:
    song = await session.scalar(
        select(QuizSong).join(Quiz).where(QuizSong.id == song_id, Quiz.owner_id == host.id)
    )
    if song is None:
        raise HTTPException(status_code=404, detail="Song not found")
    return song


def _clean_extras(values: list[str]) -> list[str]:
    return [v.strip()[:200] for v in values if v.strip()][:MAX_EXTRA_ANSWERS]


@router.patch("/songs/{song_id}", response_model=SongOut)
async def update_song(
    body: SongUpdate,
    song: QuizSong = Depends(_load_song),
    session: AsyncSession = Depends(get_session),
):
    fields = body.model_dump(exclude_unset=True)
    if "year" in fields:
        song.year = fields["year"]
        # The host has looked at it; stop nagging unless they blanked it.
        song.year_suspect = fields["year"] is None
    if fields.get("extra_titles") is not None:
        song.extra_titles = _clean_extras(fields["extra_titles"])
    if fields.get("extra_artists") is not None:
        song.extra_artists = _clean_extras(fields["extra_artists"])
    await session.commit()
    return song


@router.delete("/songs/{song_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_song(
    song: QuizSong = Depends(_load_song), session: AsyncSession = Depends(get_session)
):
    await session.delete(song)
    await session.commit()


# --- Browsing Spotify --------------------------------------------------------

async def _token(
    host: Account = Depends(current_host), session: AsyncSession = Depends(get_session)
) -> str:
    return await spotify.access_token(session, host.id)


@router.get("/spotify/playlists")
async def playlists(host: Account = Depends(current_host), token: str = Depends(_token)):
    return await spotify.my_playlists(token, host.spotify_user_id)


@router.get("/spotify/playlists/{playlist_id}/songs")
async def playlist_songs(playlist_id: str, token: str = Depends(_token)):
    return {"songs": await spotify.playlist_songs(token, playlist_id), "next_offset": None}


@router.get("/spotify/liked")
async def liked(offset: int = Query(0, ge=0), token: str = Depends(_token)):
    return await spotify.liked_songs(token, offset)


@router.get("/spotify/search")
async def search(
    q: str = Query(min_length=1, max_length=200),
    offset: int = Query(0, ge=0),
    token: str = Depends(_token),
):
    return await spotify.search_songs(token, q, offset)


@router.get("/spotify/devices")
async def devices(token: str = Depends(_token)):
    return await spotify.list_devices(token)
