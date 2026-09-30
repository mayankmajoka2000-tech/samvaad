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
