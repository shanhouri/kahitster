"""Points rules. Everything tunable about scoring lives in this file."""

TITLE_POINTS = 500
ARTIST_POINTS = 500

# A correct answer at the last second is still worth this share of the points.
SLOWEST_ANSWER_FACTOR = 0.5

# The exact year scores YEAR_POINTS, and each year off costs YEAR_STEP:
# 2 years off is 300, 5 or more is nothing. Shown to players as this rule.
YEAR_POINTS = 500
YEAR_STEP = 100


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
    return max(0, YEAR_POINTS - YEAR_STEP * years_off(guess, actual))


def years_off(guess: int | None, actual: int | None) -> int | None:
    if guess is None or actual is None:
        return None
    return abs(guess - actual)


def rules() -> dict:
    """The numbers the screens need to explain scoring to players."""
    return {
        "title": TITLE_POINTS,
        "artist": ARTIST_POINTS,
        "year": YEAR_POINTS,
        "year_step": YEAR_STEP,
    }
