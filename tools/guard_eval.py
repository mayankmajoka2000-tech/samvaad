"""Measure the numbers-and-names guard on deliberately corrupted translations.

    python tools/guard_eval.py

Takes correct English->Hindi/Spanish translation pairs, corrupts each in several
ways (changed digit, dropped number, changed number word, lost name), and reports
how many corruptions the guard catches, plus false alarms on the untouched pairs.
Every number here is computed; nothing is estimated.
"""

from __future__ import annotations

import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samvaad import guard  # noqa: E402

PAIRS = [
    ("en", "Take one 500 mg tablet twice a day, after meals, for 5 days.", "hi", "खाने के बाद दिन में दो बार 500 mg की एक गोली लें, 5 दिन तक।", []),
    ("en", "Your temperature is 101 degrees.", "hi", "आपका तापमान 101 डिग्री है।", []),
    ("en", "Come back on Friday, 2 October, if the fever continues.", "hi", "अगर बुखार बना रहे तो शुक्रवार, 2 अक्टूबर को फिर आइए।", [("October", "अक्टूबर")]),
    ("en", "Good morning, Priya. What brings you in today?", "hi", "सुप्रभात, प्रिया। आज आप किस वजह से आई हैं?", [("Priya", "प्रिया")]),
    ("en", "The fee is 1,200 rupees, due in 30 days.", "hi", "फीस 1,200 रुपये है, जो 30 दिनों में देनी है।", []),
    ("en", "Your appointment is at 3:30 in room 12.", "hi", "आपकी अपॉइंटमेंट 3:30 बजे कमरा 12 में है।", []),
    ("en", "Drink two litres of water and rest for three days.", "hi", "दो लीटर पानी पिएँ और तीन दिन आराम करें।", []),
    ("en", "Rahul will call you at 9 tomorrow.", "hi", "राहुल आपको कल 9 बजे फ़ोन करेंगे।", [("Rahul", "राहुल")]),
    ("en", "The train leaves from platform 4 at 18:45.", "es", "El tren sale del andén 4 a las 18:45.", []),
    ("en", "The project cost 240 million euros.", "es", "El proyecto costó 240 millones de euros.", []),
    ("en", "Take 2.5 ml of syrup every 8 hours.", "es", "Tome 2,5 ml de jarabe cada 8 horas.", []),
    ("en", "Meet Anita at gate 7.", "es", "Encuentra a Anita en la puerta 7.", [("Anita", "Anita")]),
    ("en", "We need 50,000 masks by Monday.", "hi", "हमें सोमवार तक 50,000 मास्क चाहिए।", []),
    ("en", "Give the child 10 drops, three times a day.", "hi", "बच्चे को दिन में तीन बार 10 बूंदें दें।", []),
    ("en", "Your blood pressure is 140 over 90.", "hi", "आपका रक्तचाप 140 बटा 90 है।", []),
    ("en", "Room 204 is on the second floor.", "es", "La habitación 204 está en el segundo piso.", []),
]

DIGITS = re.compile(r"\d+(?:[.,:]\d+)*")


def change_digit(text: str, rng: random.Random) -> str | None:
    found = list(DIGITS.finditer(text))
    if not found:
        return None
    m = rng.choice(found)
    s = m.group(0)
    choices = [s + "0", s[:-1] if len(s) > 1 else None, s[:-1] + str((int(s[-1]) + rng.randint(1, 8)) % 10)]
    new = rng.choice([c for c in choices if c and c != s])
    return text[:m.start()] + new + text[m.end():]


def drop_number(text: str, rng: random.Random) -> str | None:
    found = list(DIGITS.finditer(text))
    if not found:
        return None
    m = rng.choice(found)
    return (text[:m.start()] + text[m.end():]).replace("  ", " ")


WORD_SWAPS = {"दो": "तीन", "तीन": "चार", "एक": "दो"}


def change_word(text: str, rng: random.Random) -> str | None:
    words = [w for w in WORD_SWAPS if re.search(rf"(?<!\S){w}(?!\S)", text)]
    if not words:
        return None
    w = rng.choice(words)
    return re.sub(rf"(?<!\S){w}(?!\S)", WORD_SWAPS[w], text, count=1)


def lose_name(text: str, names, rng: random.Random) -> str | None:
    if not names:
        return None
    src, tgt = rng.choice(names)
    return text.replace(tgt, "").replace("  ", " ") if tgt in text else None


def main() -> None:
    rng = random.Random(7)
    results = {"changed digit": [0, 0], "dropped number": [0, 0], "changed number word": [0, 0], "lost name": [0, 0]}
    false_alarms = 0
    for src_lang, src, tgt_lang, tgt, names in PAIRS:
        if guard.check(src, src_lang, tgt, tgt_lang, names).status in ("hold", "confirm"):
            false_alarms += 1
        for _ in range(8):
            for label, fn in (("changed digit", change_digit), ("dropped number", drop_number), ("changed number word", change_word)):
                bad = fn(tgt, rng)
                if bad and bad != tgt:
                    results[label][1] += 1
                    if guard.check(src, src_lang, bad, tgt_lang, names).status in ("hold", "confirm"):
                        results[label][0] += 1
            bad = lose_name(tgt, names, rng)
            if bad:
                results["lost name"][1] += 1
                if guard.check(src, src_lang, bad, tgt_lang, names).status == "hold":
                    results["lost name"][0] += 1

    caught = sum(c for c, _ in results.values())
    total = sum(t for _, t in results.values())
    print("| Corruption | Caught | Cases | Rate |")
    print("| --- | ---: | ---: | ---: |")
    for label, (c, t) in results.items():
        print(f"| {label} | {c} | {t} | {100 * c / t:.1f}% |")
    print(f"| **All** | **{caught}** | **{total}** | **{100 * caught / total:.1f}%** |")
    print(f"\nFalse alarms on {len(PAIRS)} correct translations: {false_alarms}")


if __name__ == "__main__":
    main()
