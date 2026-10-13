from app.integrations.spotify import _songs, track_to_song


def track(**overrides):
    return {
        "id": "abc",
        "type": "track",
        "name": "Under Pressure - Remastered 2011",
        "artists": [{"name": "Queen"}, {"name": "David Bowie"}],
        "duration_ms": 248000,
        "album": {
            "name": "Hot Space (Deluxe Remastered Version)",
            "release_date": "2011-03-14",
            "images": [{"url": "big"}, {"url": "medium"}, {"url": "small"}],
        },
    } | overrides


def test_track_is_reduced_to_quiz_fields():
    assert track_to_song(track()) == {
        "spotify_id": "abc",
        "title": "Under Pressure",
        "artists": ["Queen", "David Bowie"],
        "album": "Hot Space (Deluxe Remastered Version)",
        "image_url": "medium",
        "duration_ms": 248000,
        "year": 2011,
        "year_suspect": True,     # a remaster's date is not the song's year
    }


def test_original_album_year_is_trusted():
    album = {"name": "Hunting High and Low", "release_date": "1985", "images": []}
    song = track_to_song(track(name="Take On Me", album=album))
    assert (song["year"], song["year_suspect"], song["image_url"]) == (1985, False, "")


def test_title_keeps_what_is_part_of_the_name():
    for name, shown in [
        ("Heroes - 2017 Remaster", "Heroes"),
        ("Yesterday (Remastered 2009)", "Yesterday"),
        ("Stan (feat. Dido)", "Stan (feat. Dido)"),
        ("Hotel California - Live", "Hotel California - Live"),
        ("Mono", "Mono"),
    ]:
        assert track_to_song(track(name=name))["title"] == shown


def test_unusable_entries_are_dropped():
    assert track_to_song(None) is None
    assert track_to_song(track(id=None)) is None
    assert track_to_song(track(is_local=True)) is None
    assert track_to_song(track(type="episode")) is None


def test_playlist_entries_in_old_and_new_api_shapes():
    entries = [{"item": track(id="new")}, {"track": track(id="old")}, {"item": None}, None]
    assert [song["spotify_id"] for song in _songs(entries)] == ["new", "old"]
