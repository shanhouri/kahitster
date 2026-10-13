"""A live game: who is in the room, which song is up, and who scored what.

Games live in memory only -- a server restart ends them, saved quizzes are
unaffected. The game owns its sockets and pushes a full state snapshot to
everyone after each change, so a client that reconnects needs no catching up.

The song being guessed is never part of a snapshot before the reveal.
"""
import asyncio
import random
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from app.services import matching, scoring

MAX_PLAYERS = 200
MAX_NAME_LENGTH = 20
MAX_ANSWER_LENGTH = 120
# Finished or abandoned games are dropped after this long.
GAME_TTL_SECONDS = 6 * 60 * 60


class Phase(str, Enum):
    LOBBY = "lobby"
    QUESTION = "question"
    REVEAL = "reveal"
    LEADERBOARD = "leaderboard"
    FINISHED = "finished"


class GameError(Exception):
    """A move the rules do not allow; the message is shown to whoever tried."""


class Playback(Protocol):
    async def play(self, spotify_id: str, position_ms: int, device_id: str | None) -> None: ...
    async def pause(self) -> None: ...


@dataclass
class Answer:
    title: str
    artist: str
    year: int | None
    title_ok: bool
    artist_ok: bool
    # Share of the title/artist points kept for answering this fast.
    speed: float
    year_points: int

    @property
    def title_points(self) -> int:
        return scoring.text_points(scoring.TITLE_POINTS, self.title_ok, self.speed)

    @property
    def artist_points(self) -> int:
        return scoring.text_points(scoring.ARTIST_POINTS, self.artist_ok, self.speed)

    @property
    def points(self) -> int:
        return self.title_points + self.artist_points + self.year_points


@dataclass
class Player:
    id: str
    # Secret kept in the player's browser; lets a refreshed phone rejoin as itself.
    token: str
    name: str
    sockets: set = field(default_factory=set)

    @property
    def connected(self) -> bool:
        return bool(self.sockets)


class Game:
    def __init__(
        self,
        pin: str,
        quiz: dict,
        songs: list[dict],
        *,
        owner_id: int | None = None,
        playback: Playback | None = None,
        join_url: str = "",
        clock=time.monotonic,
    ):
        self.pin = pin
        self.owner_id = owner_id
        self.quiz_name: str = quiz["name"]
        self.guess_year: bool = bool(quiz.get("guess_year"))
        self.seconds: float = quiz.get("seconds_per_song", 30)
        self.start_mode: str = quiz.get("start_mode", "beginning")
        self.songs = songs
        self.join_url = join_url
        self.created = time.time()

        self.phase = Phase.LOBBY
        self.index = -1
        self.players: dict[str, Player] = {}
        # One dict per round played so far: player id -> their answer.
        self.rounds: list[dict[str, Answer]] = []
        self.host_sockets: set = set()

        self.device_id: str | None = None
        self.playback_error: str | None = None

        self._playback = playback
        self._clock = clock
        self._started = 0.0
        self._timer: asyncio.Task | None = None

    # --- Players -------------------------------------------------------------

    def add_player(self, name: str) -> Player:
        name = " ".join((name or "").split())[:MAX_NAME_LENGTH]
        if not name:
            raise GameError("Enter a name")
        if self.phase is Phase.FINISHED:
            raise GameError("This game is over")
        if len(self.players) >= MAX_PLAYERS:
            raise GameError("This game is full")
        if any(p.name.casefold() == name.casefold() for p in self.players.values()):
            raise GameError("That name is taken, pick another")

        player = Player(id=secrets.token_hex(4), token=secrets.token_urlsafe(16), name=name)
        self.players[player.id] = player
        return player

    def player_by_token(self, token: str) -> Player | None:
        return next((p for p in self.players.values() if p.token == token), None)

    async def kick(self, player_id: str) -> None:
        player = self.players.pop(player_id, None)
        if player is None:
            return
        for answers in self.rounds:
            answers.pop(player_id, None)
        for ws in list(player.sockets):
            await _send(ws, fatal("removed", "The host removed you from the game"))
            await _close(ws)

    def score(self, player_id: str) -> int:
        return sum(answers[player_id].points for answers in self.rounds if player_id in answers)

    def leaderboard(self) -> list[dict]:
        last = self.rounds[-1] if self.rounds else {}
        rows = [
            {
                "id": p.id,
                "name": p.name,
                "score": self.score(p.id),
                "gained": last[p.id].points if p.id in last else 0,
            }
            for p in self.players.values()
        ]
        rows.sort(key=lambda row: (-row["score"], row["name"].casefold()))
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        return rows

    # --- Flow ----------------------------------------------------------------

    async def start(self) -> None:
        if self.phase is not Phase.LOBBY:
            raise GameError("The game has already started")
        if not self.players:
            raise GameError("Wait for at least one player to join")
        await self._begin(0)

    async def next(self) -> None:
        if self.phase not in (Phase.REVEAL, Phase.LEADERBOARD):
            raise GameError("Finish the current song first")
        if self.index + 1 < len(self.songs):
            await self._begin(self.index + 1)
        else:
            self.phase = Phase.FINISHED

    async def _begin(self, index: int) -> None:
        # Phase flips before the (slow) Spotify call so a double-clicked "Next"
        # cannot start two songs.
        self.phase = Phase.QUESTION
        self.index = index
        self.rounds.append({})
        await self._play()
        # The clock starts once the music does, so nobody pays for Spotify's lag.
        self._started = self._clock()
        self._timer = asyncio.create_task(self._time_out(index))

    async def _time_out(self, index: int) -> None:
        await asyncio.sleep(self.seconds)
        if self.phase is Phase.QUESTION and self.index == index:
            await self.end_question()
            await self.broadcast()

    async def end_question(self) -> None:
        if self.phase is not Phase.QUESTION:
            return
        self.phase = Phase.REVEAL
        timer, self._timer = self._timer, None
        # When the timer itself got us here, cancelling it would abort this call.
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()
        if self._playback is not None:
            try:
                await self._playback.pause()
            except Exception as exc:  # never let Spotify trouble stall the game
                self.playback_error = str(exc)

    def show_leaderboard(self) -> None:
        if self.phase is not Phase.REVEAL:
            raise GameError("Nothing to show yet")
        self.phase = Phase.LEADERBOARD

    async def finish(self) -> None:
        await self.end_question()
        self.phase = Phase.FINISHED

    async def replay(self) -> None:
        if self.phase is not Phase.QUESTION:
            raise GameError("No song is playing")
        await self._play()

    async def _play(self) -> None:
        self.playback_error = None
        if self._playback is None:
            return
        song = self.songs[self.index]
        position = 0
        duration = song.get("duration_ms") or 0
        if self.start_mode == "random" and duration:
            # Skip intros, but leave enough track that it cannot run out mid-round.
            position = random.randint(int(duration * 0.15), int(duration * 0.6))
        try:
            await self._playback.play(song["spotify_id"], position, self.device_id)
        except Exception as exc:
            self.playback_error = str(exc)

    # --- Answers -------------------------------------------------------------

    def submit_answer(self, player_id: str, title: str, artist: str, year=None) -> None:
        if self.phase is not Phase.QUESTION:
            raise GameError("This round is over")
        answers = self.rounds[self.index]
        if player_id in answers:
            raise GameError("You already answered")

        song = self.songs[self.index]
        title = str(title or "").strip()[:MAX_ANSWER_LENGTH]
        artist = str(artist or "").strip()[:MAX_ANSWER_LENGTH]
        if not self.guess_year or not isinstance(year, int) or isinstance(year, bool):
            year = None

        answers[player_id] = Answer(
            title=title,
            artist=artist,
            year=year,
            title_ok=matching.matches_title(title, song["title"], song.get("extra_titles", [])),
            artist_ok=matching.matches_artist(
                artist, song["artists"], song.get("extra_artists", [])
            ),
            speed=scoring.speed_factor(self._clock() - self._started, self.seconds),
            year_points=scoring.year_points(year, song.get("year")),
        )

    def everyone_answered(self) -> bool:
        """Whether there is no one left in the room to wait for."""
        if self.phase is not Phase.QUESTION:
            return False
        answers = self.rounds[self.index]
        waiting = [p for p in self.players.values() if p.connected and p.id not in answers]
        return bool(answers) and not waiting

    def override(self, player_id: str, part: str, ok: bool) -> None:
        """The host overrules the spell-checker on one answer of this round."""
        if self.phase not in (Phase.REVEAL, Phase.LEADERBOARD):
            raise GameError("Answers can only be corrected after the reveal")
        answer = self.rounds[self.index].get(player_id)
        if answer is None:
            raise GameError("That player did not answer")
        if part == "title":
            answer.title_ok = bool(ok)
        elif part == "artist":
            answer.artist_ok = bool(ok)
        else:
            raise GameError("Unknown answer part")

    # --- Snapshots -----------------------------------------------------------

    def _remaining(self) -> float:
        return max(0.0, self.seconds - (self._clock() - self._started))

    def _revealed(self) -> bool:
        return self.index >= 0 and self.phase in (
            Phase.REVEAL,
            Phase.LEADERBOARD,
            Phase.FINISHED,
        )

    def _song(self) -> dict:
        song = self.songs[self.index]
        return {key: song.get(key) for key in ("title", "artists", "album", "year", "image_url")}

    def _base_state(self) -> dict:
        state = {
            "type": "state",
            "phase": self.phase.value,
            "pin": self.pin,
            "quiz_name": self.quiz_name,
            "guess_year": self.guess_year,
            "index": self.index,
            "total": len(self.songs),
        }
        if self.phase is Phase.QUESTION:
            state["duration"] = self.seconds
            state["remaining"] = self._remaining()
        if self._revealed():
            state["song"] = self._song()
        return state

    def host_state(self) -> dict:
        answers = self.rounds[self.index] if self.index >= 0 else {}
        board = self.leaderboard()
        state = self._base_state() | {
            "join_url": self.join_url,
            "device_id": self.device_id,
            "playback_error": self.playback_error,
            "leaderboard": board,
            "players": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "connected": self.players[row["id"]].connected,
                    "answered": row["id"] in answers,
                }
                for row in board
            ],
        }
        if self._revealed():
            state["answers"] = [
                {"id": row["id"], "name": row["name"], **_answer_view(answers.get(row["id"]))}
                for row in board
            ]
        return state

    def player_state(self, player: Player) -> dict:
        answers = self.rounds[self.index] if self.index >= 0 else {}
        board = self.leaderboard()
        mine = next(row for row in board if row["id"] == player.id)
        state = self._base_state() | {
            "name": player.name,
            "score": mine["score"],
            "rank": mine["rank"],
            "player_count": len(board),
            "answered": player.id in answers,
        }
        if self._revealed():
            state["result"] = _answer_view(answers.get(player.id))
        if self.phase is Phase.FINISHED:
            state["podium"] = [
                {"name": row["name"], "score": row["score"]} for row in board[:3]
            ]
        return state

    # --- Sockets -------------------------------------------------------------

    async def broadcast(self) -> None:
        if self.host_sockets:
            state = self.host_state()
            for ws in list(self.host_sockets):
                if not await _send(ws, state):
                    self.host_sockets.discard(ws)
        for player in list(self.players.values()):
            if not player.sockets:
                continue
            state = self.player_state(player)
            for ws in list(player.sockets):
                if not await _send(ws, state):
                    player.sockets.discard(ws)


def _answer_view(answer: Answer | None) -> dict:
    if answer is None:
        return {"answered": False, "points": 0}
    return {
        "answered": True,
        "title": answer.title,
        "artist": answer.artist,
        "year": answer.year,
        "title_ok": answer.title_ok,
        "artist_ok": answer.artist_ok,
        "title_points": answer.title_points,
        "artist_points": answer.artist_points,
        "year_points": answer.year_points,
        "points": answer.points,
    }


def fatal(code: str, message: str) -> dict:
    """An error after which the client should stop reconnecting."""
    return {"type": "error", "fatal": True, "code": code, "message": message}


async def _send(ws, message: dict) -> bool:
    try:
        await ws.send_json(message)
        return True
    except Exception:  # the socket died; its own handler cleans up
        return False


async def _close(ws) -> None:
    try:
        await ws.close()
    except Exception:
        pass


# --- Registry ------------------------------------------------------------------

_games: dict[str, Game] = {}


def create_game(quiz: dict, songs: list[dict], **kwargs) -> Game:
    cutoff = time.time() - GAME_TTL_SECONDS
    for pin in [pin for pin, game in _games.items() if game.created < cutoff]:
        del _games[pin]

    while True:
        pin = f"{secrets.randbelow(1_000_000):06d}"
        if pin not in _games:
            break
    game = Game(pin, quiz, songs, **kwargs)
    _games[pin] = game
    return game


def get_game(pin: str) -> Game | None:
    return _games.get(pin)
