"""Points rules. Everything tunable about scoring lives in this file."""

TITLE_POINTS = 500
ARTIST_POINTS = 500

# A correct answer at the last second is still worth this share of the points.
SLOWEST_ANSWER_FACTOR = 0.5

# Points by how many years off the guess is; anything further scores nothing.
YEAR_POINTS = {0: 500, 1: 400, 2: 300, 3: 200, 4: 100, 5: 100}


def speed_factor(elapsed: float, limit: float) -> float:
    """1.0 for an instant answer, sliding to SLOWEST_ANSWER_FACTOR at the bell."""
    if limit <= 0:
        return 1.0
    used = min(max(elapsed / limit, 0.0), 1.0)
    return 1.0 - (1.0 - SLOWEST_ANSWER_FACTOR) * used


def text_points(full: int, correct: bool, speed: float) -> int:
    return round(full * speed) if correct else 0


def year_points(guess: int | None, actual: int | None) -> int:
    if guess is None or actual is None:
        return 0
    return YEAR_POINTS.get(abs(guess - actual), 0)
