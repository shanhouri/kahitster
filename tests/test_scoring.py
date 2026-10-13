import pytest

from app.services.scoring import speed_factor, text_points, year_points


def test_speed_factor_slides_from_full_to_half():
    assert speed_factor(0, 30) == 1.0
    assert speed_factor(15, 30) == 0.75
    assert speed_factor(30, 30) == 0.5
    assert speed_factor(99, 30) == 0.5   # a late answer never drops below half
    assert speed_factor(-1, 30) == 1.0


def test_text_points():
    assert text_points(500, True, 1.0) == 500
    assert text_points(500, True, 0.5) == 250
    assert text_points(500, False, 1.0) == 0


@pytest.mark.parametrize(
    "guess, points",
    [(1985, 500), (1984, 400), (1986, 400), (1987, 300), (1982, 200), (1981, 100),
     (1990, 100), (1991, 0), (1900, 0), (None, 0)],
)
def test_year_points(guess, points):
    assert year_points(guess, 1985) == points


def test_year_points_without_a_known_year():
    assert year_points(1985, None) == 0
