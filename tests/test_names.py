import asyncio

from app.integrations import spotify
from app.models import QuizSong
from app.services import names
from tests.conftest import song


def quiz_song(**overrides):
    fields = {k: v for k, v in song(1).items() if k != "year_suspect"} | overrides
    return QuizSong(extra_titles=[], extra_artists=[], **fields)


def test_other_language_names_become_accepted_answers():
    row = quiz_song(title="יום הולדת שמח", artists=["Oded Menashe"])
    names.add_names(row, {"title": "יום הולדת שמח", "artists": ["עודד מנשה"]})
    assert row.extra_titles == []               # same title, nothing to add
    assert row.extra_artists == ["עודד מנשה"]

    names.add_names(row, {"title": "Yom Huledet Sameach", "artists": ["עודד מנשה"]})
    assert row.extra_titles == ["Yom Huledet Sameach"]
    assert row.extra_artists == ["עודד מנשה"]   # not added twice


def test_adding_songs_looks_up_hebrew_names_in_the_background(client, host, monkeypatch):
    asked = []

    async def names_in(token, spotify_id, language):
        asked.append((spotify_id, language))
        return {"title": "יום שישי", "artists": ["בנזין"]}

    monkeypatch.setattr(spotify, "names_in", names_in)
    quiz = client.post("/api/quizzes", json={"name": "Hebrew"}, headers=host).json()
    client.post(
        f"/api/quizzes/{quiz['id']}/songs",
        json={"songs": [song(1, title="Yom Shishi", artists=["Benzin"])]},
        headers=host,
    )

    for _ in range(50):     # the lookup runs after the response is sent
        loaded = client.get(f"/api/quizzes/{quiz['id']}", headers=host).json()["songs"][0]
        if loaded["extra_artists"]:
            break
        client.portal.call(asyncio.sleep, 0.05)

    assert asked == [("id1", "he")]
    assert loaded["extra_titles"] == ["יום שישי"]
    assert loaded["extra_artists"] == ["בנזין"]
