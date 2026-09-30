"""The numbers-and-names guard.

Every translation is checked before it is shown or spoken: the numbers (digits and
number words) and the names in the source sentence must survive into the
translation. A changed digit or a lost name holds the line for review; a mismatch
in number *words* only asks the listener to confirm.

The checks are deliberately simple and deterministic, so they can be tested and
trusted: no model sits between a doctor's "500 mg" and what the patient hears.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Zero code points of the decimal digit blocks we normalise to ASCII 0-9:
# Devanagari, Bengali, Tamil, Arabic-Indic, Extended Arabic-Indic, Fullwidth,
# Gujarati, Gurmukhi, Kannada, Telugu, Malayalam.
_DIGIT_ZEROS = (0x0966, 0x09E6, 0x0BE6, 0x0660, 0x06F0, 0xFF10, 0x0AE6, 0x0A66, 0x0CE6, 0x0C66, 0x0D66)

_DIGIT_TABLE = {zero + i: str(i) for zero in _DIGIT_ZEROS for i in range(10)}

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
_THOUSANDS_RE = re.compile(r"\d{1,3}(?:[.,]\d{3})+")
_SPLIT_RE = re.compile(r"[\s.,!?;:।॥\"'“”‘’()\[\]\-–—]+")

# Number words per language. Only words that are rarely used in a non-numeric
# sense are listed (Spanish "un/una" are left out because they are articles).
NUMBER_WORDS: dict[str, dict[str, int]] = {
    "en": {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
        "once": 1, "twice": 2, "thrice": 3,
    },
    "hi": {
        "शून्य": 0, "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5, "पांच": 5,
        "छह": 6, "छः": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10, "ग्यारह": 11, "बारह": 12,
    },
    "mr": {
        "शून्य": 0, "एक": 1, "दोन": 2, "तीन": 3, "चार": 4, "पाच": 5, "सहा": 6,
        "सात": 7, "आठ": 8, "नऊ": 9, "दहा": 10,
    },
    "es": {
        "cero": 0, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
        "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    },
    "fr": {
        "zéro": 0, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6,
        "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
    },
}


def normalise_digits(text: str) -> str:
    """Map every non-ASCII decimal digit (e.g. Devanagari ५) to its ASCII form."""
    return text.translate(_DIGIT_TABLE)


def normalise_number(token: str) -> str:
    """Canonical form of a number token: "50.000" and "50,000" -> "50000", "2,5" -> "2.5"."""
    if _THOUSANDS_RE.fullmatch(token):
        return str(int(re.sub(r"[.,]", "", token)))
    try:
        value = float(token.replace(",", "."))
    except ValueError:
        return token
    return str(int(value)) if value.is_integer() else repr(value)


@dataclass
class Facts:
    digits: list[str] = field(default_factory=list)
    words: list[str] = field(default_factory=list)

    @property
    def all(self) -> list[str]:
        return self.digits + self.words


def extract_facts(text: str, lang: str) -> Facts:
    """Numbers found in ``text``: digits in any script, plus number words for ``lang``."""
    t = normalise_digits(text or "")
    facts = Facts(digits=[normalise_number(m.group(0)) for m in _NUM_RE.finditer(t)])
    words = NUMBER_WORDS.get((lang or "").split("-")[0].lower())
    if words:
        for token in _SPLIT_RE.split(t.lower()):
            if token in words:
                facts.words.append(str(words[token]))
    return facts


def _minus(a: list[str], b: list[str]) -> list[str]:
    """Multiset difference a - b."""
    rest, out = list(b), []
    for x in a:
        if x in rest:
            rest.remove(x)
        else:
            out.append(x)
    return out


def _unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for x in items:
        if x not in seen:
            seen.append(x)
    return seen


@dataclass
class GuardResult:
    status: str  # "pass" | "confirm" | "hold" | "none"
    numbers: list[str]
    missing: list[str]
    extra: list[str]
    names: list[tuple[str, str]]
    lost_names: list[tuple[str, str]]

    @property
    def speakable(self) -> bool:
        return self.status != "hold"

    def message(self) -> str:
        if self.status == "pass":
            parts = []
            if self.numbers:
                parts.append("Numbers match: " + " · ".join(self.numbers))
            if self.names:
                kept = [s if s == t else f"{s} → {t}" for s, t in self.names]
                parts.append("Names kept: " + ", ".join(kept))
            return ". ".join(parts)
        if self.status == "hold":
            bits = []
            if self.missing:
                verb = "are" if len(self.missing) > 1 else "is"
                bits.append(f"{', '.join(self.missing)} {verb} in the original but missing here")
            if self.extra:
                verb = "appear" if len(self.extra) > 1 else "appears"
                bits.append(f"{', '.join(self.extra)} {verb} instead")
            if self.lost_names:
                bits.append("name " + ", ".join(s for s, _ in self.lost_names) + " was lost")
            detail = "; ".join(bits) or "numbers differ"
            return f"Held for review: {detail}. Not spoken aloud; ask the speaker to repeat."
        if self.status == "confirm":
            return "Please confirm: number words differ (" + ", ".join(self.missing + self.extra) + ")."
        return "No numbers or names to check"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "numbers": self.numbers,
            "missing": self.missing,
            "extra": self.extra,
            "names": [list(p) for p in self.names],
            "lost_names": [list(p) for p in self.lost_names],
            "message": self.message(),
        }


def check(source: str, source_lang: str, translation: str, target_lang: str,
          names: list[tuple[str, str]] | None = None) -> GuardResult:
    """Compare the numbers and names in ``source`` with those in ``translation``."""
    names = [(str(s), str(t)) for s, t in (names or []) if s and t]
    a = extract_facts(source, source_lang)
    b = extract_facts(translation, target_lang)
    missing = _minus(a.all, b.all)
    extra = _minus(b.all, a.all)
    digit_problem = any(d not in b.all for d in a.digits) or any(d not in a.all for d in b.digits)
    lowered = (translation or "").lower()
    lost = [(s, t) for s, t in names if t.lower() not in lowered]

    if digit_problem or lost:
        status = "hold"
    elif missing or extra:
        status = "confirm"
    elif not a.all and not names:
        status = "none"
    else:
        status = "pass"
    return GuardResult(status, _unique(a.all), _unique(missing), _unique(extra), names, lost)


def numbers_supported(answer: str, answer_lang: str, sources: list[tuple[str, str]]) -> list[str]:
    """Digits in ``answer`` that appear in none of the (text, lang) ``sources``."""
    pool: list[str] = []
    for text, lang in sources:
        pool.extend(extract_facts(text, lang).all)
    return _unique([d for d in extract_facts(answer, answer_lang).digits if d not in pool])
