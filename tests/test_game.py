import asyncio

import pytest

from app.services.game import Game, GameError, Phase
from tests.conftest import song


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, message):
        self.sent.append(message)

    async def close(self):
        pass


class FakePlayback:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def play(self, spotify_id, position_ms, device_id):
        if self.fail:
            raise RuntimeError("No active Spotify device.")
        self.calls.append(("play", spotify_id, position_ms, device_id))

    async def pause(self):
        self.calls.append(("pause",))


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def make_game(n_songs=2, playback=None, **quiz):
    clock = Clock()
    playback = playback or FakePlayback()
    game = Game(
        "123456",
        {"name": "Party", "guess_year": True, "seconds_per_song": 30} | quiz,
        [song(n) for n in range(1, n_songs + 1)],
        playback=playback,
        clock=clock,
    )
    return game, clock, playback


def join(game, name):
    player = game.add_player(name)
    player.sockets.add(FakeSocket())
    return player


async def test_full_game_scores_and_ranks():
    game, clock, playback = make_game()
    ann, bob = join(game, "Ann"), join(game, "Bob")

    await game.start()
    assert game.phase is Phase.QUESTION
    assert playback.calls == [("play", "id1", 0, None)]

    game.submit_answer(ann.id, "song 1", "artist 1", 1991)      # instant, all right
    assert not game.everyone_answered()
    clock.now += 30
    game.submit_answer(bob.id, "song 1", "nobody", 1993)        # last second, 2 years off
    assert game.everyone_answered()

    await game.end_question()
    assert game.phase is Phase.REVEAL
    assert playback.calls[-1] == ("pause",)
    assert game.score(ann.id) == 500 + 500 + 500
    assert game.score(bob.id) == 250 + 0 + 300

    game.show_leaderboard()
    await game.next()
    assert game.phase is Phase.QUESTION and game.index == 1
    await game.end_question()            # nobody answers song 2
    game.show_leaderboard()
    await game.next()
    assert game.phase is Phase.FINISHED

    board = game.leaderboard()
    assert [(row["name"], row["rank"]) for row in board] == [("Ann", 1), ("Bob", 2)]


async def test_answer_is_hidden_until_reveal():
    game, _, _ = make_game()
    ann = join(game, "Ann")
    await game.start()

    for state in (game.host_state(), game.player_state(ann)):
        assert "song" not in state and "answers" not in state
        assert "Song 1" not in str(state) and "Artist 1" not in str(state)

    await game.end_question()
    assert game.host_state()["song"]["title"] == "Song 1"
    assert game.player_state(ann)["song"]["title"] == "Song 1"


async def test_host_override_changes_the_score():
    game, _, _ = make_game()
    ann = join(game, "Ann")
    await game.start()
    game.submit_answer(ann.id, "sonng wun", "artist 1")
    await game.end_question()
    assert game.score(ann.id) == 500

    game.override(ann.id, "title", True)
    assert game.score(ann.id) == 1000
    game.override(ann.id, "artist", False)
    assert game.score(ann.id) == 500


async def test_rules_are_enforced():
    game, _, _ = make_game()
    with pytest.raises(GameError):
        await game.start()                        # nobody has joined
    ann = join(game, "Ann")
    with pytest.raises(GameError):
        game.add_player(" ann ")                  # same name, different case
    with pytest.raises(GameError):
        game.add_player("   ")
    with pytest.raises(GameError):
        game.submit_answer(ann.id, "x", "y")      # not started

    await game.start()
    game.submit_answer(ann.id, "x", "y")
    with pytest.raises(GameError):
        game.submit_answer(ann.id, "song 1", "artist 1")   # one answer per round
    with pytest.raises(GameError):
        await game.next()                         # round still running
    with pytest.raises(GameError):
        game.override(ann.id, "title", True)      # not revealed yet
    await game.finish()


async def test_year_is_ignored_when_the_quiz_does_not_ask_for_it():
    game, _, _ = make_game(guess_year=False)
    ann = join(game, "Ann")
    await game.start()
    game.submit_answer(ann.id, "", "", 1991)
    await game.end_question()
    assert game.score(ann.id) == 0


async def test_timer_ends_the_round():
    game, _, _ = make_game(seconds_per_song=0.05)
    join(game, "Ann")
    await game.start()
    await asyncio.sleep(0.3)
    assert game.phase is Phase.REVEAL


async def test_disconnected_players_are_not_waited_for():
    game, _, _ = make_game()
    ann, bob = join(game, "Ann"), join(game, "Bob")
    bob.sockets.clear()
    await game.start()
    game.submit_answer(ann.id, "x", "y")
    assert game.everyone_answered()
    await game.finish()


async def test_playback_failure_does_not_stop_the_game():
    game, _, _ = make_game(playback=FakePlayback(fail=True))
    join(game, "Ann")
    await game.start()
    assert game.phase is Phase.QUESTION
    assert "No active Spotify device" in game.host_state()["playback_error"]
    await game.finish()


async def test_random_start_stays_inside_the_track():
    game, _, playback = make_game(start_mode="random")
    join(game, "Ann")
    await game.start()
    position = playback.calls[0][2]
    assert 30_000 <= position <= 120_000
    await game.finish()


async def test_kick_removes_player_and_their_score():
    game, _, _ = make_game()
    ann, bob = join(game, "Ann"), join(game, "Bob")
    await game.start()
    game.submit_answer(bob.id, "song 1", "artist 1")
    await game.kick(bob.id)
    assert [row["name"] for row in game.leaderboard()] == ["Ann"]
    assert game.player_by_token(bob.token) is None
    await game.finish()
