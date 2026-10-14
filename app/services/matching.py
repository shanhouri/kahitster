"""Deciding whether a typed guess names the song or the artist.

Players type on phones, in a hurry, so the comparison forgives case, accents,
punctuation, pressing suffixes ("- Remastered 2011") and a typo or two. It will
still get some answers wrong; the host can overrule it on the reveal screen.
"""
import re
import unicodedata

from rapidfuzz.distance import OSA

# Typos forgiven, by length of the correct answer (spaces not counted). A typo
# is one wrong, missing, extra or swapped letter. Short names get none: one
# changed letter in "Stan" or "Help" is a different word.
_TYPOS_ALLOWED = ((4, 0), (8, 1), (14, 2))
_MAX_TYPOS = 3

# Includes the Hebrew geresh and gershayim, as in צ'ה or צה"ל.
_APOSTROPHES = re.compile(r"['’‘`´\"״׳]")
# A final letter typed mid-word, or a regular one at the end, is a typo
# nobody should lose points for: ך→כ, ם→מ, ן→נ, ף→פ, ץ→צ.
_HEBREW_FINALS = str.maketrans("ךםןףץ", "כמנפצ")
# Extra words a guess may carry around the full title and still count, as in
# "כל הילדים קופצים רוקדים" for "הילדים קופצים".
_EXTRA_WORDS_ALLOWED = 2
_BRACKETED = re.compile(r"\s*[(\[][^)\]]*[)\]]")
_DASH_TAIL = re.compile(r"\s+[-–—]\s+.*$")
_FEAT_TAIL = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s+.*$", re.IGNORECASE)
_ARTIST_SEPARATORS = re.compile(
    r"\s*(?:,|&|\+|/|;|\band\b|\bx\b|\bvs\.?|\bfeat\.?|\bft\.?|\bfeaturing\b)\s*",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    """Fold text to a comparison key: 'The Beatles' -> 'beatles'.

    Unicode-aware on purpose, so Hebrew titles keep their letters instead of
    collapsing to the empty string.
    """
    text = unicodedata.normalize("NFKD", text or "").casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.translate(_HEBREW_FINALS)
    text = _APOSTROPHES.sub("", text).replace("&", " and ")
    text = re.sub(r"[\W_]+", " ", text).strip()
    return text.removeprefix("the ")


def title_variants(title: str) -> set[str]:
    """Every form of a title a player could reasonably mean.

    'Under Pressure - Remastered 2011' is known to everyone as 'Under
    Pressure', and nobody types '(feat. Dido)'.
    """
    no_brackets = _BRACKETED.sub("", title)
    forms = {
        title,
        no_brackets,
        _DASH_TAIL.sub("", title),
        _DASH_TAIL.sub("", no_brackets),
        _FEAT_TAIL.sub("", _DASH_TAIL.sub("", no_brackets)),
    }
    return {key for key in map(normalize, forms) if key}


def similar(guess: str, answer: str) -> bool:
    """Compare two already-normalized strings."""
    if not guess or not answer:
        return False
    if guess == answer:
        return True
    # "dontstop" vs "dont stop": spacing is not worth losing points over.
    tight_guess, tight_answer = guess.replace(" ", ""), answer.replace(" ", "")
    if tight_guess == tight_answer:
        return True
    return OSA.distance(tight_guess, tight_answer) <= _typos_allowed(len(tight_answer))


def _typos_allowed(length: int) -> int:
    return next((typos for limit, typos in _TYPOS_ALLOWED if length <= limit), _MAX_TYPOS)


def matches_title(guess: str, title: str, extra_titles: list[str] = ()) -> bool:
    key = normalize(guess)
    answers = title_variants(title)
    for extra in extra_titles:
        answers |= title_variants(extra)
    return any(similar(key, answer) or _contains(key, answer) for answer in answers)


def _contains(guess: str, answer: str) -> bool:
    """Whether the guess is the whole title plus a word or two around it.

    Players often type a line from the chorus that includes the title. Only
    the whole title counts, never part of it, and only with a little extra --
    otherwise typing a list of songs would always score.
    """
    guess_words, answer_words = guess.split(), answer.split()
    extra = len(guess_words) - len(answer_words)
    if not 0 < extra <= _EXTRA_WORDS_ALLOWED:
        return False
    return any(
        guess_words[start:start + len(answer_words)] == answer_words
        for start in range(extra + 1)
    )


def matches_artist(guess: str, artists: list[str], extra_artists: list[str] = ()) -> bool:
    """True when the guess names any one of the credited artists."""
    answers = {normalize(name) for name in [*artists, *extra_artists]}
    # "Queen and David Bowie" should count for a song credited to both, but
    # "Simon & Garfunkel" is one name -- so try the whole guess and its parts.
    guesses = {normalize(guess), *map(normalize, _ARTIST_SEPARATORS.split(guess or ""))}
    return any(similar(g, answer) for g in guesses for answer in answers)
