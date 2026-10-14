from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Account(Base):
    """A host: someone who has signed in with Spotify."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    spotify_user_id: Mapped[str] = mapped_column(String(128), unique=True)
    display_name: Mapped[str] = mapped_column(String(256))
    access_token: Mapped[str]
    refresh_token: Mapped[str]
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    guess_year: Mapped[bool] = mapped_column(default=False)
    seconds_per_song: Mapped[int] = mapped_column(default=30)
    # "beginning" or "random" -- where in the track playback starts.
    start_mode: Mapped[str] = mapped_column(String(16), default="beginning")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    songs: Mapped[list["QuizSong"]] = relationship(
        back_populates="quiz",
        cascade="all, delete-orphan",
        order_by="QuizSong.position",
    )


class QuizSong(Base):
    __tablename__ = "quiz_songs"

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"), index=True)
    position: Mapped[int] = mapped_column(default=0)

    spotify_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(512))
    artists: Mapped[list[str]] = mapped_column(JSON)
    album: Mapped[str] = mapped_column(String(512), default="")
    image_url: Mapped[str] = mapped_column(String(512), default="")
    duration_ms: Mapped[int] = mapped_column(default=0)

    year: Mapped[int | None]
    # Spotify dates the pressing, not the song; set when the album looks like a
    # remaster or compilation, cleared once the host confirms a year.
    year_suspect: Mapped[bool] = mapped_column(default=False)

    # Other spellings the host is willing to accept, e.g. a transliteration.
    extra_titles: Mapped[list[str]] = mapped_column(JSON, default=list)
    extra_artists: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Whether names in the second language were looked up (services/names.py).
    names_checked: Mapped[bool] = mapped_column(default=False)

    quiz: Mapped[Quiz] = relationship(back_populates="songs")
