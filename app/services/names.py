"""Accepting answers in a second language.

Spotify shows a song in the language of whoever is asking, so a Hebrew song
can come back with its title in Hebrew but its artist as "Oded Menashe" --
and a player who types "עודד מנשה" deserves the points. For each song added
to a quiz we ask Spotify once more in the other language and keep any new
names as extra accepted answers, the same list the host edits by hand.

This runs in the background after songs are added, one request at a time to
stay clear of Spotify's rate limits. A song is marked once checked, so the
work is never repeated and an interrupted run resumes next time.
"""
import asyncio
import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.integrations import spotify
from app.models import QuizSong
from app.services.matching import normalize

log = logging.getLogger(__name__)

# Quizzes being worked on right now, so two triggers do not both start.
_running: set[int] = set()
# Strong references; asyncio only keeps weak ones to running tasks.
_tasks: set[asyncio.Task] = set()


def schedule(quiz_id: int, account_id: int) -> None:
    if not get_settings().other_names_language or quiz_id in _running:
        return
    _running.add(quiz_id)
    task = asyncio.create_task(_check_quiz(quiz_id, account_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def add_names(song: QuizSong, other: dict) -> None:
    """Record the other language's names wherever they differ from ours."""
    known_titles = {normalize(t) for t in [song.title, *song.extra_titles]}
    if other["title"] and normalize(other["title"]) not in known_titles:
        song.extra_titles = [*song.extra_titles, other["title"]]

    known_artists = {normalize(a) for a in [*song.artists, *song.extra_artists]}
    new_artists = [a for a in other["artists"] if normalize(a) not in known_artists]
    if new_artists:
        song.extra_artists = [*song.extra_artists, *new_artists]


async def _check_quiz(quiz_id: int, account_id: int) -> None:
    language = get_settings().other_names_language
    try:
        async with SessionLocal() as session:
            token = await spotify.access_token(session, account_id)
            songs = (
                await session.scalars(
                    select(QuizSong).where(
                        QuizSong.quiz_id == quiz_id, QuizSong.names_checked.is_(False)
                    )
                )
            ).all()
            for song in songs:
                try:
                    other = await spotify.names_in(token, song.spotify_id, language)
                except spotify.SpotifyError as exc:
                    if exc.status == 429:
                        break  # rate-limited: leave the rest for next time
                    other = None
                if other:
                    add_names(song, other)
                song.names_checked = True
                await session.commit()
    except Exception:
        # Best effort: a song without its other-language names still plays,
        # and the host can add them by hand.
        log.exception("Looking up %s names for quiz %s failed", language, quiz_id)
    finally:
        _running.discard(quiz_id)
