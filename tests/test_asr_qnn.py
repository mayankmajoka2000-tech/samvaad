"""Tests for the Whisper NPU decode loop, with simulated ONNX sessions.

The real encoder/decoder only run on a Snapdragon NPU, so these fakes stand in for
them. They check the parts Samvaad adds to Qualcomm's sample loop: forcing a
language, choosing between two candidate languages, and detecting the language.
"""

from types import SimpleNamespace

import numpy as np

from samvaad.engines.asr_qnn import QnnWhisper

SOT, EOT, EN, HI, FR, TRANSCRIBE, NOTS = 50258, 50257, 50259, 50276, 50265, 50360, 50364
VOCAB = 50400
WORDS = {100: "Take", 101: "500", 102: "mg"}


class FakeInput:
    def __init__(self, name, type_):
        self.name, self.type = name, type_


class FakeEncoder:
    def get_inputs(self):
        return [FakeInput("input_features", "tensor(float)")]

    def get_outputs(self):
        return [SimpleNamespace(name="k0"), SimpleNamespace(name="v0")]

    def run(self, names, feed):
        return [np.zeros((2, 1, 4, 1500), np.float32), np.zeros((2, 1, 1500, 4), np.float32)]


class FakeDecoder:
    """Returns logits whose argmax follows ``script`` (one entry per call)."""

    def __init__(self, script):
        self.script = script
        self.fed = []

    def get_inputs(self):
        return [FakeInput("input_ids", "tensor(int32)"), FakeInput("attention_mask", "tensor(float)"),
                FakeInput("k_self_0", "tensor(float)"), FakeInput("v_self_0", "tensor(float)"),
                FakeInput("k_cross_0", "tensor(float)"), FakeInput("v_cross_0", "tensor(float)"),
                FakeInput("position_ids", "tensor(int32)")]

    def get_outputs(self):
        return [SimpleNamespace(name=n) for n in ("logits", "k_self_out", "v_self_out")]

    def run(self, names, feed):
        step = len(self.fed)
        self.fed.append(int(feed["input_ids"][0, 0]))
        logits = np.zeros((1, VOCAB), np.float32)
        entry = self.script[min(step, len(self.script) - 1)]
        for token, score in (entry.items() if isinstance(entry, dict) else {entry: 10.0}.items()):
            logits[0, token] = score
        return [logits, feed["k_self_0"], feed["v_self_0"]]


class FakeTokenizer:
    def decode(self, ids, skip_special_tokens=True):
        return " ".join(WORDS[i] for i in ids if i in WORDS)


def make_engine(script):
    eng = QnnWhisper.__new__(QnnWhisper)
    eng.name, eng.config = "fake", SimpleNamespace(decoder_start_token_id=SOT, eos_token_id=EOT,
                                                   decoder_attention_heads=2, d_model=8, decoder_layers=1)
    eng.tokenizer = FakeTokenizer()
    eng.features = lambda audio, sampling_rate, return_tensors: {"input_features": np.zeros((1, 80, 3000), np.float32)}
    eng.encoder, eng.decoder = FakeEncoder(), FakeDecoder(script)
    eng._lock = __import__("threading").Lock()
    eng._transcribe_id, eng._notimestamps_id = TRANSCRIBE, NOTS
    eng._lang_ids = {"en": EN, "hi": HI, "fr": FR}
    eng._id_to_lang = {v: k for k, v in eng._lang_ids.items()}
    return eng


AUDIO = np.zeros(16000, np.float32)


def test_forced_language_prefix_is_fed_then_text_decoded():
    # Calls 0-2 feed the forced prefix (their predictions are ignored); then Take, 500, mg, end.
    eng = make_engine([0, 0, 0, 100, 101, 102, EOT])
    res = eng.transcribe(AUDIO, language="hi")
    assert eng.decoder.fed[:4] == [SOT, HI, TRANSCRIBE, NOTS]
    assert res.text == "Take 500 mg" and res.language == "hi"


def test_candidate_languages_restrict_the_choice():
    # French scores highest overall, but only English or Hindi may be chosen: Hindi wins.
    first = {FR: 9.0, HI: 5.0, EN: 1.0}
    eng = make_engine([first, 0, 0, 100, EOT])
    res = eng.transcribe(AUDIO, candidates=["en", "hi"])
    assert res.language == "hi"
    assert eng.decoder.fed[:4] == [SOT, HI, TRANSCRIBE, NOTS]
    assert res.text == "Take"


def test_free_detection_reports_the_language():
    eng = make_engine([EN, TRANSCRIBE, NOTS, 101, EOT])
    res = eng.transcribe(AUDIO)
    assert res.language == "en" and res.text == "500"
