import pytest

from app.services.matching import matches_artist, matches_title, normalize


def test_normalize_folds_case_accents_and_articles():
    assert normalize("The Beatles") == "beatles"
    assert normalize("Beyoncé") == "beyonce"
    assert normalize("Don't Stop Me Now!") == "dont stop me now"
    assert normalize("Guns N' Roses") == "guns n roses"


def test_normalize_keeps_hebrew():
    assert normalize("יהלומים בשמיים") == "יהלומים בשמיים"


@pytest.mark.parametrize(
    "guess, title",
    [
        ("under pressure", "Under Pressure - Remastered 2011"),
        ("stan", "Stan (feat. Dido)"),
        ("Take on me", "Take On Me"),
        ("wonderwal", "Wonderwall"),                 # one typo
        ("dontstop believin", "Don't Stop Believin'"),
        ("heroes", '"Heroes" - 2017 Remaster'),
        ("shape of you", "Shape of You"),
        ("מתחת לשמיים", "מתחת לשמיים"),
        ("livin on a prayer", "Livin' On A Prayer"),
    ],
)
def test_title_accepted(guess, title):
    assert matches_title(guess, title)


@pytest.mark.parametrize(
    "guess, title",
    [
        ("", "Yesterday"),
        ("   ", "Yesterday"),
        ("tomorrow", "Yesterday"),
        ("stam", "Stan"),             # short names leave no room for typos
        ("help", "Hello"),
        ("under", "Under Pressure"),  # half a title is not the title
    ],
)
def test_title_rejected(guess, title):
    assert not matches_title(guess, title)


def test_extra_titles_are_accepted():
    assert not matches_title("etmol", "Yesterday")
    assert matches_title("etmol", "Yesterday", ["Etmol"])


@pytest.mark.parametrize(
    "guess, artists",
    [
        ("beatles", ["The Beatles"]),
        ("david bowie", ["Queen", "David Bowie"]),      # either credited artist
        ("Queen and David Bowie", ["Queen", "David Bowie"]),
        ("simon and garfunkel", ["Simon & Garfunkel"]),
        ("beyonce", ["Beyoncé"]),
        ("acdc", ["AC/DC"]),
        ("emenem", ["Eminem"]),
    ],
)
def test_artist_accepted(guess, artists):
    assert matches_artist(guess, artists)


@pytest.mark.parametrize(
    "guess, artists",
    [("", ["Queen"]), ("king", ["Queen"]), ("the", ["The Beatles"]), ("and", ["Queen"])],
)
def test_artist_rejected(guess, artists):
    assert not matches_artist(guess, artists)
