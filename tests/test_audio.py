import numpy as np

from samvaad.audio import SAMPLE_RATE, AlarmDetector, Endpointer, common_prefix_words
from samvaad.beacon import name_heard


def tone(freq, seconds, amp=0.2):
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def speechlike(seconds, amp=0.15, seed=0):
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 1, int(seconds * SAMPLE_RATE)).astype(np.float32)
    env = 0.6 + 0.4 * np.sin(np.linspace(0, 12 * np.pi, noise.size))
    return (amp * noise * env / 3).astype(np.float32)


def silence(seconds):
    return (np.random.default_rng(1).normal(0, 0.001, int(seconds * SAMPLE_RATE))).astype(np.float32)


def feed_in_blocks(ep, audio, block=1600):
    events = []
    for i in range(0, len(audio), block):
        events += ep.feed(audio[i:i + block])
    return events


def test_endpointer_finds_one_utterance():
    ep = Endpointer()
    audio = np.concatenate([silence(1.0), speechlike(2.0), silence(1.2)])
    events = feed_in_blocks(ep, audio)
    kinds = [k for k, _ in events]
    assert kinds == ["start", "end"]
    utterance = events[-1][1]
    assert 1.9 < len(utterance) / SAMPLE_RATE < 3.2


def test_endpointer_flush_closes_early():
    ep = Endpointer()
    feed_in_blocks(ep, np.concatenate([silence(0.5), speechlike(1.0)]))
    assert ep.in_speech
    events = ep.flush()
    assert events and events[0][0] == "end"


def test_endpointer_ignores_blips():
    ep = Endpointer()
    events = feed_in_blocks(ep, np.concatenate([silence(1.0), speechlike(0.12), silence(1.0)]))
    assert "end" not in [k for k, _ in events]


def test_alarm_detector_fires_on_3khz_tone_only():
    det = AlarmDetector()
    assert not any(det.feed(b) for b in np.array_split(speechlike(3.0), 30))
    det = AlarmDetector()
    assert any(det.feed(b) for b in np.array_split(tone(3200, 3.0), 30))


def test_partial_agreement():
    assert common_prefix_words("take one 500", "take one 500 mg tablet") == len("take one 500")
    assert common_prefix_words("", "hello there") == 0


def test_name_heard_across_scripts():
    assert name_heard(["Good morning, Priya."], "Priya")
    assert name_heard(["सुप्रभात, प्रिया।"], "Priya")
    assert not name_heard(["Good morning, Priyanka."], "Priya")
