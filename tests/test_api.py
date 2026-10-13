import time
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core import security
from app.core.database import engine_config
from app.services import game as games
from tests.conftest import SITE, song

GUEST = {"host": SITE}


def make_quiz(client, host, n_songs=2, **settings):
    quiz = client.post("/api/quizzes", json={"name": "Party"}, headers=host).json()
    if settings:
        client.patch(f"/api/quizzes/{quiz['id']}", json=settings, headers=host)
    if n_songs:
        client.post(
            f"/api/quizzes/{quiz['id']}/songs",
            json={"songs": [song(n) for n in range(1, n_songs + 1)]},
            headers=host,
        )
    return quiz["id"]


def new_game(client, host, **kwargs) -> str:
    quiz_id = make_quiz(client, host, **kwargs)
    return client.post("/api/games", json={"quiz_id": quiz_id}, headers=host).json()["pin"]


def join(client, pin, name):
    return client.post("/api/join", json={"pin": pin, "name": name})


def read_state(ws, phase, index=None):
    """Skip snapshots until the game reaches `phase` (of song `index`, if given)."""
    while True:
        message = ws.receive_json()
        if message.get("type") != "state" or message["phase"] != phase:
            continue
        if index is None or message["index"] == index:
            return message


# --- Signing in --------------------------------------------------------------

def test_sign_in_makes_you_a_host(client, host):
    assert client.get("/api/me").json()["connected"] is False
    assert client.get("/api/me", headers=host).json() == {
        "configured": True, "connected": True, "display_name": "Itamar",
    }


def test_login_sends_the_browser_to_spotify_with_the_public_callback(client):
    location = client.get("/auth/login", follow_redirects=False).headers["location"]
    assert location.startswith("https://accounts.spotify.com/authorize?")
    assert "redirect_uri=https%3A%2F%2Fkahitster.example%2Fauth%2Fcallback" in location


def test_callback_rejects_a_login_it_did_not_start(client):
    assert client.get("/auth/callback?code=x&state=made-up").status_code == 400


def test_session_cookies_cannot_be_forged_or_reused_after_expiry(monkeypatch):
    cookie = security.make_session(7)
    assert security.read_session(cookie) == 7

    account, expires, signature = cookie.split(".")
    assert security.read_session(f"8.{expires}.{signature}") is None      # other account
    assert security.read_session(f"{account}.{expires}.{'0' * 64}") is None
    for junk in (None, "", "7", "a.b.c", "7.9999999999"):
        assert security.read_session(junk) is None

    monkeypatch.setattr(time, "time", lambda: float(expires) + 1)
    assert security.read_session(cookie) is None


def test_requests_from_another_website_are_not_trusted():
    def conn(origin):
        headers = {"host": SITE} | ({"origin": origin} if origin else {})
        return SimpleNamespace(headers=headers)

    assert security.same_origin(conn(None))
    assert security.same_origin(conn(f"https://{SITE}"))
    assert not security.same_origin(conn("https://evil.example"))


# --- Quiz building -----------------------------------------------------------

def test_quiz_crud(client, host):
    quiz_id = make_quiz(client, host, n_songs=3)

    quiz = client.get(f"/api/quizzes/{quiz_id}", headers=host).json()
    assert [s["title"] for s in quiz["songs"]] == ["Song 1", "Song 2", "Song 3"]
    assert quiz["guess_year"] is False and quiz["seconds_per_song"] == 30

    # Adding a song the quiz already has adds nothing.
    again = client.post(
        f"/api/quizzes/{quiz_id}/songs", json={"songs": [song(1), song(4)]}, headers=host
    )
    assert again.json() == {"added": 1, "skipped": 1}

    updated = client.patch(
        f"/api/quizzes/{quiz_id}", json={"guess_year": True, "seconds_per_song": 45}, headers=host
    ).json()
    assert updated["guess_year"] is True and updated["seconds_per_song"] == 45
    bad = client.patch(f"/api/quizzes/{quiz_id}", json={"seconds_per_song": 1}, headers=host)
    assert bad.status_code == 422

    ids = [s["id"] for s in updated["songs"]]
    order = f"/api/quizzes/{quiz_id}/order"
    assert client.put(order, json={"song_ids": ids[::-1]}, headers=host).status_code == 204
    assert client.put(order, json={"song_ids": ids[:2]}, headers=host).status_code == 400
    quiz = client.get(f"/api/quizzes/{quiz_id}", headers=host).json()
    assert [s["id"] for s in quiz["songs"]] == ids[::-1]

    assert client.delete(f"/api/songs/{ids[0]}", headers=host).status_code == 204
    listed = client.get("/api/quizzes", headers=host).json()
    assert next(q for q in listed if q["id"] == quiz_id)["song_count"] == 3

    assert client.delete(f"/api/quizzes/{quiz_id}", headers=host).status_code == 204
    assert client.get(f"/api/quizzes/{quiz_id}", headers=host).status_code == 404


def test_editing_a_song(client, host):
    quiz_id = make_quiz(client, host, n_songs=0)
    client.post(
        f"/api/quizzes/{quiz_id}/songs", json={"songs": [song(1, year_suspect=True)]}, headers=host
    )
    song_id = client.get(f"/api/quizzes/{quiz_id}", headers=host).json()["songs"][0]["id"]

    edited = client.patch(
        f"/api/songs/{song_id}", json={"year": 1975, "extra_titles": [" Etmol ", ""]}, headers=host
    ).json()
    assert edited["year"] == 1975
    assert edited["year_suspect"] is False        # confirmed by the host
    assert edited["extra_titles"] == ["Etmol"]
    assert client.patch(f"/api/songs/{song_id}", json={"year": 12}, headers=host).status_code == 422


def test_empty_quiz_cannot_be_played(client, host):
    quiz_id = make_quiz(client, host, n_songs=0)
    assert client.post("/api/games", json={"quiz_id": quiz_id}, headers=host).status_code == 400


# --- Who may do what ---------------------------------------------------------

def test_host_features_need_a_sign_in(client, host):
    quiz_id = make_quiz(client, host)
    pin = client.post("/api/games", json={"quiz_id": quiz_id}, headers=host).json()["pin"]

    for method, url in [
        ("GET", "/api/quizzes"),
        ("POST", "/api/quizzes"),
        ("GET", f"/api/quizzes/{quiz_id}"),
        ("DELETE", f"/api/quizzes/{quiz_id}"),
        ("POST", "/api/games"),
        ("GET", f"/api/games/{pin}/qr.svg"),
        ("POST", f"/api/games/{pin}/device"),
        ("GET", "/api/spotify/devices"),
        ("GET", "/api/spotify/search?q=x"),
    ]:
        assert client.request(method, url, headers=GUEST).status_code == 401, (method, url)

    forged = {"cookie": f"{security.COOKIE}=1.9999999999.{'0' * 64}", "host": SITE}
    assert client.get("/api/quizzes", headers=forged).status_code == 401

    # A real cookie sent by a page on another site is refused too.
    assert client.get("/api/quizzes", headers=host | {"origin": "https://evil.example"}).status_code == 401

    for headers in (GUEST, forged):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/host/{pin}", headers=headers):
                pass


def test_hosts_cannot_touch_each_others_quizzes_or_games(client, host, other_host):
    quiz_id = make_quiz(client, host)
    song_id = client.get(f"/api/quizzes/{quiz_id}", headers=host).json()["songs"][0]["id"]
    pin = client.post("/api/games", json={"quiz_id": quiz_id}, headers=host).json()["pin"]

    assert client.get("/api/quizzes", headers=other_host).json() == []
    for method, url in [
        ("GET", f"/api/quizzes/{quiz_id}"),
        ("PATCH", f"/api/quizzes/{quiz_id}"),
        ("DELETE", f"/api/quizzes/{quiz_id}"),
        ("PATCH", f"/api/songs/{song_id}"),
        ("DELETE", f"/api/songs/{song_id}"),
        ("GET", f"/api/games/{pin}/qr.svg"),
    ]:
        response = client.request(method, url, headers=other_host, json={})
        assert response.status_code == 404, (method, url)
    started = client.post("/api/games", json={"quiz_id": quiz_id}, headers=other_host)
    assert started.status_code == 404

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/host/{pin}", headers=other_host):
            pass

    # Untouched for its owner.
    assert len(client.get(f"/api/quizzes/{quiz_id}", headers=host).json()["songs"]) == 2


def test_pages(client, host):
    assert "join.js" in client.get("/").text            # strangers get the PIN box
    assert "home.js" in client.get("/", headers=host).text
    assert "home.js" in client.get("/home").text
    assert "join.js" in client.get("/join/123456").text
    assert "play.js" in client.get("/play/123456").text
    assert client.get("/static/common.js").status_code == 200
    assert client.get("/healthz").json() == {"ok": True}

    # Host screens send a signed-out visitor to the sign-in page.
    for url in ("/quiz/1", "/host/123456"):
        assert client.get(url, follow_redirects=False).headers["location"] == "/home"
        assert client.get(url, headers=host).status_code == 200


# --- Playing -----------------------------------------------------------------

def test_join_rules(client, host):
    pin = new_game(client, host)

    assert join(client, "000000", "Ann").status_code == 404
    seat = join(client, pin, "  Ann  ")
    assert seat.status_code == 200 and seat.json()["name"] == "Ann"
    assert join(client, pin, "ANN").status_code == 409
    assert join(client, pin, "").status_code == 409


def test_qr_points_at_the_public_join_page(client, host):
    pin = new_game(client, host)
    response = client.get(f"/api/games/{pin}/qr.svg", headers=host)
    assert response.status_code == 200 and "<svg" in response.text
    assert games.get_game(pin).join_url == "https://kahitster.example"


def test_full_game_over_websockets(client, host):
    pin = new_game(client, host, n_songs=2, guess_year=True)
    ann, bob = join(client, pin, "Ann").json(), join(client, pin, "Bob").json()

    with client.websocket_connect(f"/ws/host/{pin}", headers=host) as host_ws, \
         client.websocket_connect(f"/ws/play/{pin}") as ann_ws, \
         client.websocket_connect(f"/ws/play/{pin}") as bob_ws:
        ann_ws.send_json({"type": "hello", "token": ann["token"]})
        bob_ws.send_json({"type": "hello", "token": bob["token"]})
        assert read_state(ann_ws, "lobby")["name"] == "Ann"
        read_state(bob_ws, "lobby")

        host_ws.send_json({"type": "ping"})          # keep-alive; changes nothing
        host_ws.send_json({"type": "start"})
        question = read_state(ann_ws, "question")
        assert question["index"] == 0 and question["total"] == 2
        assert "song" not in question and 0 < question["remaining"] <= 30
        # Spotify is unreachable in tests: the game carries on and tells the host.
        assert read_state(host_ws, "question")["playback_error"]

        ann_ws.send_json({"type": "answer", "title": "Song 1", "artist": "Artist 1", "year": 1991})
        bob_ws.send_json({"type": "answer", "title": "sonng wun", "artist": "artist 1", "year": 1999})

        # Everyone answered, so the round ends without waiting for the timer.
        reveal = read_state(host_ws, "reveal")
        assert reveal["song"]["title"] == "Song 1"
        by_name = {a["name"]: a for a in reveal["answers"]}
        assert by_name["Ann"]["title_ok"] and by_name["Ann"]["artist_ok"]
        assert by_name["Ann"]["year_points"] == 500
        assert not by_name["Bob"]["title_ok"] and by_name["Bob"]["artist_ok"]

        result = read_state(bob_ws, "reveal")
        assert result["result"]["title"] == "sonng wun" and result["rank"] == 2

        # The host decides Bob's spelling was close enough.
        before = by_name["Bob"]["points"]
        host_ws.send_json(
            {"type": "override", "player_id": by_name["Bob"]["id"], "part": "title", "ok": True}
        )
        corrected = read_state(host_ws, "reveal")
        bob_row = next(a for a in corrected["answers"] if a["name"] == "Bob")
        assert bob_row["title_ok"] and bob_row["points"] > before

        host_ws.send_json({"type": "leaderboard"})
        board = read_state(host_ws, "leaderboard")["leaderboard"]
        assert [row["name"] for row in board] == ["Ann", "Bob"]

        host_ws.send_json({"type": "next"})
        assert "song" not in read_state(ann_ws, "question", index=1)
        host_ws.send_json({"type": "end_round"})
        host_ws.send_json({"type": "leaderboard"})
        host_ws.send_json({"type": "next"})
        final = read_state(ann_ws, "finished")
        assert final["rank"] == 1 and final["podium"][0]["name"] == "Ann"


def test_unknown_seat_and_missing_game(client, host):
    pin = new_game(client, host)

    with client.websocket_connect(f"/ws/play/{pin}") as ws:
        ws.send_json({"type": "hello", "token": "made-up"})
        message = ws.receive_json()
        assert message["fatal"] and message["code"] == "unknown_player"

    with client.websocket_connect("/ws/play/000000") as ws:
        assert ws.receive_json()["code"] == "no_game"


def test_player_reconnects_to_the_same_seat(client, host):
    pin = new_game(client, host)
    ann = join(client, pin, "Ann").json()

    with client.websocket_connect(f"/ws/host/{pin}", headers=host) as host_ws:
        with client.websocket_connect(f"/ws/play/{pin}") as ws:
            ws.send_json({"type": "hello", "token": ann["token"]})
            read_state(ws, "lobby")
            host_ws.send_json({"type": "start"})
            read_state(ws, "question")
            ws.send_json({"type": "answer", "title": "Song 1", "artist": "Artist 1"})
            score = read_state(ws, "reveal")["score"]
            assert score > 0

        with client.websocket_connect(f"/ws/play/{pin}") as ws:
            ws.send_json({"type": "hello", "token": ann["token"]})
            again = read_state(ws, "reveal")
            assert again["name"] == "Ann" and again["score"] == score


# --- Hosting -----------------------------------------------------------------

def test_database_urls_from_hosting_providers_are_adapted():
    url, options = engine_config(
        "postgresql://user:pw@ep-x.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    )
    assert url == "postgresql+asyncpg://user:pw@ep-x.eu-central-1.aws.neon.tech/neondb"
    assert options["connect_args"] == {"ssl": "require"} and options["pool_pre_ping"]

    assert engine_config("postgres://u:p@localhost/db")[0] == "postgresql+asyncpg://u:p@localhost/db"
    assert "connect_args" not in engine_config("postgres://u:p@localhost/db")[1]

    sqlite = "sqlite+aiosqlite:///./kahitster.db"
    assert engine_config(sqlite) == (sqlite, {})
