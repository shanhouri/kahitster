from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Year = Annotated[int | None, Field(ge=1000, le=9999)]


class SongIn(BaseModel):
    """A track as the Spotify browse endpoints return it to the editor."""

    spotify_id: str = Field(min_length=1, max_length=64)
    title: str = Field(max_length=512)
    artists: list[str]
    album: str = ""
    image_url: str = ""
    duration_ms: int = 0
    year: Year = None
    year_suspect: bool = False


class SongOut(SongIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    extra_titles: list[str]
    extra_artists: list[str]


class SongsIn(BaseModel):
    songs: list[SongIn]


class SongUpdate(BaseModel):
    year: Year = None
    extra_titles: list[str] | None = None
    extra_artists: list[str] | None = None


class QuizCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class QuizUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    guess_year: bool | None = None
    seconds_per_song: int | None = Field(default=None, ge=10, le=120)
    start_mode: Literal["beginning", "random"] | None = None


class QuizSummary(BaseModel):
    id: int
    name: str
    song_count: int


class QuizOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    guess_year: bool
    seconds_per_song: int
    start_mode: str
    songs: list[SongOut]


class Reorder(BaseModel):
    song_ids: list[int]


class GameCreate(BaseModel):
    quiz_id: int


class DeviceChoice(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)


class JoinIn(BaseModel):
    pin: str = Field(max_length=12)
    name: str = Field(max_length=64)
