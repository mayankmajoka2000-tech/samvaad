from samvaad import guard


def test_matching_numbers_pass():
    r = guard.check(
        "Take one 500 mg tablet twice a day, after meals, for 5 days.", "en",
        "खाने के बाद दिन में दो बार 500 mg की एक गोली लें, 5 दिन तक।", "hi",
    )
    assert r.status == "pass"
    assert set(r.numbers) == {"500", "5", "1", "2"}


def test_changed_digit_is_held():
    r = guard.check("Take 500 mg.", "en", "50 mg लें।", "hi")
    assert r.status == "hold"
    assert r.missing == ["500"] and r.extra == ["50"]
    assert not r.speakable
    assert "500 is in the original" in r.message()


def test_devanagari_digits_and_thousands_separators():
    assert guard.check("२ अक्टूबर", "hi", "2 October", "en").status == "pass"
    assert guard.check("50.000 viajeros", "es", "50,000 passengers", "en").status == "pass"


def test_number_word_mismatch_only_asks_to_confirm():
    r = guard.check("I have a fever for three days.", "en", "मुझे बुखार है।", "hi")
    assert r.status == "confirm"


def test_lost_name_is_held():
    r = guard.check("Good morning, Priya.", "en", "सुप्रभात।", "hi", [("Priya", "प्रिया")])
    assert r.status == "hold"
    assert r.lost_names == [("Priya", "प्रिया")]


def test_nothing_to_check():
    assert guard.check("Can I take it with milk?", "en", "क्या मैं इसे दूध के साथ ले सकती हूँ?", "hi").status == "none"


def test_answer_numbers_must_come_from_sources():
    sources = [("Take one 500 mg tablet twice a day.", "en")]
    assert guard.numbers_supported("500 mg, twice a day.", "en", sources) == []
    assert guard.numbers_supported("50 mg, twice a day.", "en", sources) == ["50"]


# ---------------------------------------------------------------- days, months, time of day
# The first case is a real Qwen3-4B (q4) output seen while testing on a CPU-only laptop.

def test_changed_day_is_held():
    r = guard.check("Your appointment is on Friday, 2 October, at 10 in the morning.", "en",
              "आपका मिलन शनिवार, 2 अक्टूबर, शाम के 10 बजे है।", "hi")
    assert r.status == "hold"
    assert "Friday" in r.message() and "Saturday" in r.message() and "time of day" in r.message()


def test_correct_date_passes():
    r = guard.check("Your appointment is on Friday, 2 October, at 10 in the morning.", "en",
              "आपकी अपॉइंटमेंट शुक्रवार, 2 अक्टूबर को सुबह 10 बजे है।", "hi")
    assert r.status == "pass" and r.dates == ["Friday", "October"]


def test_time_of_day_swap_asks_to_confirm():
    r = guard.check("Take it at night.", "en", "इसे सुबह लें।", "hi")
    assert r.status == "confirm" and "night → morning" in r.message()


def test_greeting_is_not_a_time():
    assert guard.check("Good morning, Priya.", "en", "सुप्रभात, प्रिया।", "hi", [("Priya", "प्रिया")]).status == "pass"


def test_english_may_is_a_month_only_next_to_a_number():
    assert guard.check("You may take it with milk.", "en", "आप इसे दूध के साथ ले सकते हैं।", "hi").status == "none"
    assert guard.check("Come back on 2 May.", "en", "2 जून को वापस आइए।", "hi").status == "hold"


def test_dates_are_not_claimed_for_unsupported_languages():
    r = guard.check("See you on Monday.", "en", "திங்கள் அன்று சந்திப்போம்.", "ta")
    assert r.status == "none" and r.dates == []


def test_names_from_earlier_lines_are_ignored():
    # Models sometimes return names from the conversation context; only this sentence counts.
    r = guard.check("मुझे तीन दिन से बुखार है।", "hi", "I have had a fever for three days.", "en", [("Priya", "प्रिया")])
    assert r.status == "pass" and r.lost_names == []
