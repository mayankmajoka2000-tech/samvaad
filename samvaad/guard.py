"""The numbers-and-names guard.

Every translation is checked before it is shown or spoken: the numbers (digits and
number words), the names, the days of the week and the months in the source
sentence must survive into the translation. A changed digit, day or month, or a
lost name, holds the line for review; a mismatch in number *words* or in the time
of day (morning, evening...) only asks the listener to confirm.

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


# Days of the week and months, mapped to English, for the languages with number words.
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"]


def _table(names: list[str], words: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for canonical, variants in zip(names, words):
        for w in variants.split("|"):
            out[w] = canonical
    return out


DATE_WORDS: dict[str, dict[str, str]] = {
    "en": _table(_DAYS + _MONTHS, [d.lower() for d in _DAYS] + [m.lower() for m in _MONTHS]),
    "hi": _table(_DAYS + _MONTHS, [
        "सोमवार", "मंगलवार", "बुधवार", "गुरुवार|बृहस्पतिवार|वीरवार", "शुक्रवार", "शनिवार", "रविवार|इतवार",
        "जनवरी", "फरवरी|फ़रवरी", "मार्च", "अप्रैल|अप्रेल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर|सितम्बर",
        "अक्टूबर|अक्तूबर", "नवंबर|नवम्बर", "दिसंबर|दिसम्बर"]),
    "mr": _table(_DAYS + _MONTHS, [
        "सोमवार", "मंगळवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार",
        "जानेवारी", "फेब्रुवारी", "मार्च", "एप्रिल", "मे", "जून", "जुलै", "ऑगस्ट", "सप्टेंबर", "ऑक्टोबर",
        "नोव्हेंबर", "डिसेंबर"]),
    "es": _table(_DAYS + _MONTHS, [
        "lunes", "martes", "miércoles|miercoles", "jueves", "viernes", "sábado|sabado", "domingo",
        "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre|setiembre",
        "octubre", "noviembre", "diciembre"]),
    "fr": _table(_DAYS + _MONTHS, [
        "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
        "janvier", "février|fevrier", "mars", "avril", "mai", "juin", "juillet", "août|aout", "septembre",
        "octobre", "novembre", "décembre|decembre"]),
}

# Time of day: a swap (10 in the morning -> 10 at night) asks the listener to confirm.
TIME_WORDS: dict[str, dict[str, str]] = {
    "en": {"morning": "morning", "afternoon": "afternoon", "evening": "evening", "night": "night",
           "tonight": "night"},
    "hi": {"सुबह": "morning", "सवेरे": "morning", "प्रातः": "morning", "प्रात": "morning", "दोपहर": "afternoon",
           "शाम": "evening", "सायं": "evening", "रात": "night", "रात्रि": "night"},
    "mr": {"सकाळ": "morning", "सकाळी": "morning", "दुपार": "afternoon", "दुपारी": "afternoon",
           "संध्याकाळ": "evening", "संध्याकाळी": "evening", "रात्र": "night", "रात्री": "night"},
    "es": {"noche": "night"},
    "fr": {"matin": "morning", "soir": "evening", "soirée": "evening", "nuit": "night"},
}

# Greetings are not times: "Good morning" often becomes "नमस्ते" or "सुप्रभात".
_GREETINGS_RE = re.compile(
    r"\bgood\s+(morning|afternoon|evening|night)\b|शुभ\s+(रात्रि|संध्या|सकाळ|रात्री)|"
    r"\bbonne\s+nuit\b|\bbon\s+matin\b|\bbuenas\s+noches\b", re.I)


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
    dates: list[str] = field(default_factory=list)   # "Friday", "October"
    times: list[str] = field(default_factory=list)   # "morning", "night"

    @property
    def all(self) -> list[str]:
        return self.digits + self.words


def _base(lang: str) -> str:
    return (lang or "").split("-")[0].lower()


def extract_facts(text: str, lang: str) -> Facts:
    """Facts found in ``text``: digits in any script, plus number words, days, months and
    times of day for ``lang``."""
    t = normalise_digits(text or "")
    facts = Facts(digits=[normalise_number(m.group(0)) for m in _NUM_RE.finditer(t)])
    code = _base(lang)
    words, dates, times = NUMBER_WORDS.get(code), DATE_WORDS.get(code), TIME_WORDS.get(code)
    tokens = [x for x in _SPLIT_RE.split(t.lower()) if x]
    for i, token in enumerate(tokens):
        if words and token in words:
            facts.words.append(str(words[token]))
        if dates and token in dates:
            # English "may" is usually a verb: count it only next to a number ("2 May", "May 2").
            near_number = any(_NUM_RE.fullmatch(tokens[j]) for j in (i - 1, i + 1) if 0 <= j < len(tokens))
            if not (code == "en" and token == "may" and not near_number):
                facts.dates.append(dates[token])
    if times:
        for token in _SPLIT_RE.split(_GREETINGS_RE.sub(" ", t.lower())):
            if token in times:
                facts.times.append(times[token])
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
    dates: list[str] = field(default_factory=list)
    dates_missing: list[str] = field(default_factory=list)
    dates_extra: list[str] = field(default_factory=list)
    times_changed: list[str] = field(default_factory=list)

    @property
    def speakable(self) -> bool:
        return self.status != "hold"

    def message(self) -> str:
        if self.status == "pass":
            parts = []
            if self.numbers:
                parts.append("Numbers match: " + " · ".join(self.numbers))
            if self.dates:
                parts.append("Dates match: " + " · ".join(self.dates))
            if self.names:
                kept = [s if s == t else f"{s} → {t}" for s, t in self.names]
                parts.append("Names kept: " + ", ".join(kept))
            return ". ".join(parts)
        if self.status == "hold":
            bits = []
            missing, extra = self.missing + self.dates_missing, self.extra + self.dates_extra
            if missing:
                verb = "are" if len(missing) > 1 else "is"
                bits.append(f"{', '.join(missing)} {verb} in the original but missing here")
            if extra:
                verb = "appear" if len(extra) > 1 else "appears"
                bits.append(f"{', '.join(extra)} {verb} instead")
            if self.lost_names:
                bits.append("name " + ", ".join(s for s, _ in self.lost_names) + " was lost")
            if self.times_changed:
                bits.append("time of day changed (" + " → ".join(self.times_changed) + ")")
            detail = "; ".join(bits) or "numbers differ"
            return f"Held for review: {detail}. Not spoken aloud; ask the speaker to repeat."
        if self.status == "confirm":
            bits = []
            if self.missing or self.extra:
                bits.append("number words differ (" + ", ".join(self.missing + self.extra) + ")")
            if self.times_changed:
                bits.append("time of day changed (" + " → ".join(self.times_changed) + ")")
            return "Please confirm: " + "; ".join(bits) + "."
        return "No numbers or names to check"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "numbers": self.numbers,
            "missing": self.missing,
            "extra": self.extra,
            "names": [list(p) for p in self.names],
            "lost_names": [list(p) for p in self.lost_names],
            "dates": self.dates,
            "dates_missing": self.dates_missing,
            "dates_extra": self.dates_extra,
            "times_changed": self.times_changed,
            "message": self.message(),
        }


def check(source: str, source_lang: str, translation: str, target_lang: str,
          names: list[tuple[str, str]] | None = None) -> GuardResult:
    """Compare the numbers, dates and names in ``source`` with those in ``translation``."""
    # Only names that are really in this sentence: models sometimes list names from earlier lines.
    source_lower = (source or "").lower()
    names = [(str(s), str(t)) for s, t in (names or []) if s and t and str(s).lower() in source_lower]
    a = extract_facts(source, source_lang)
    b = extract_facts(translation, target_lang)
    missing = _minus(a.all, b.all)
    extra = _minus(b.all, a.all)
    digit_problem = any(d not in b.all for d in a.digits) or any(d not in a.all for d in b.digits)
    lowered = (translation or "").lower()
    lost = [(s, t) for s, t in names if t.lower() not in lowered]
    # Days, months and times are compared only when both languages have word lists.
    both_dates = _base(source_lang) in DATE_WORDS and _base(target_lang) in DATE_WORDS
    dates_missing = _minus(a.dates, b.dates) if both_dates else []
    dates_extra = _minus(b.dates, a.dates) if both_dates else []
    both_times = _base(source_lang) in TIME_WORDS and _base(target_lang) in TIME_WORDS
    times_changed = []
    if both_times and a.times and b.times and set(a.times) != set(b.times):
        times_changed = [" / ".join(_unique(a.times)), " / ".join(_unique(b.times))]
    checked_dates = _unique(a.dates) if both_dates else []


    if digit_problem or lost or dates_missing or dates_extra:
        status = "hold"
    elif missing or extra or times_changed:
        status = "confirm"
    elif not a.all and not names and not checked_dates:
        status = "none"
    else:
        status = "pass"
    return GuardResult(status, _unique(a.all), _unique(missing), _unique(extra), names, lost,
                       checked_dates, _unique(dates_missing), _unique(dates_extra), times_changed)


def numbers_supported(answer: str, answer_lang: str, sources: list[tuple[str, str]]) -> list[str]:
    """Digits in ``answer`` that appear in none of the (text, lang) ``sources``."""
    pool: list[str] = []
    for text, lang in sources:
        pool.extend(extract_facts(text, lang).all)
    return _unique([d for d in extract_facts(answer, answer_lang).digits if d not in pool])
