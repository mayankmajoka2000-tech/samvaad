# ---------------------------------------------------------------------
# Portions adapted from Qualcomm AI Hub Apps (whisper_windows_py):
#   Copyright (c) 2025-2026 Qualcomm Technologies, Inc. and/or its subsidiaries.
#   SPDX-License-Identifier: BSD-3-Clause
# Samvaad changes: forced/candidate language decoding, language detection,
# timing, and a thread-safe single-utterance API. See THIRD_PARTY_NOTICES.md.
# ---------------------------------------------------------------------
"""Whisper on the Snapdragon NPU.

The encoder and decoder are Qualcomm AI Hub exports (EPContext ONNX wrappers around
precompiled QNN context binaries). ONNX Runtime's QNN Execution Provider runs them
on the Hexagon NPU. A Hugging Face tokenizer, config and feature extractor drive the
autoregressive decode loop.

Requires native ARM64 Python on Windows: x64 Python under emulation cannot reach
the NPU through ONNX Runtime QNN.
"""

from __future__ import annotations

import functools
import threading
import time

import numpy as np

from . import ASRResult

SAMPLE_RATE = 16000
MEAN_DECODE_LEN = 200
MASK_NEG = -100.0

_ORT_TYPE_TO_NP_DTYPE = {
    "tensor(float)": np.float32,
    "tensor(float16)": np.float16,
    "tensor(double)": np.float64,
    "tensor(int32)": np.int32,
    "tensor(int64)": np.int64,
    "tensor(uint16)": np.uint16,
    "tensor(uint8)": np.uint8,
}

# QNN EP options mirroring qai_hub_models' defaults.
_QNN_PROVIDER_OPTIONS = {
    "enable_htp_fp16_precision": "1",
    "htp_performance_mode": "burst",
    "htp_graph_finalization_optimization_mode": "3",
    "offload_graph_io_quantization": "1",
}


def open_qnn_session(model_path: str):
    """Open an ONNX Runtime session on the QNN Execution Provider (plugin or classic EP)."""
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    try:
        import onnxruntime_qnn as qnn  # plugin EP (onnxruntime-qnn >= 2.0.0)
    except ImportError:
        qnn = None

    if qnn is not None:
        _register_qnn(qnn.EP_NAME, qnn.get_library_path())
        devices = [d for d in ort.get_ep_devices() if d.ep_name == qnn.EP_NAME]
        if not devices:
            raise RuntimeError("ONNX Runtime found no QNN (NPU) device. Is this a Snapdragon PC with ARM64 Python?")
        so.add_provider_for_devices(devices, _QNN_PROVIDER_OPTIONS)
        return ort.InferenceSession(model_path, sess_options=so)

    return ort.InferenceSession(
        model_path,
        sess_options=so,
        providers=["QNNExecutionProvider"],
        provider_options=[{**_QNN_PROVIDER_OPTIONS, "backend_path": "QnnHtp.dll"}],
    )


@functools.cache
def _register_qnn(ep_name: str, library_path: str) -> None:
    import onnxruntime as ort

    ort.register_execution_provider_library(ep_name, library_path)


def _run(session, *args: np.ndarray) -> tuple[np.ndarray, ...]:
    """Run ``session`` on positional arrays, cast to the graph's declared input dtypes."""
    inputs = session.get_inputs()
    feed = {i.name: a.astype(_ORT_TYPE_TO_NP_DTYPE[i.type], copy=False) for i, a in zip(inputs, args)}
    names = [o.name for o in session.get_outputs()]
    return tuple(session.run(names, feed))


class QnnWhisper:
    device = "NPU"

    def __init__(self, encoder_path: str, decoder_path: str, model_size: str = "base") -> None:
        from transformers import WhisperConfig, WhisperFeatureExtractor, WhisperTokenizer

        hf_id = f"openai/whisper-{model_size}"
        self.name = f"Whisper-{model_size} (QNN)"
        self.config = WhisperConfig.from_pretrained(hf_id)
        self.tokenizer = WhisperTokenizer.from_pretrained(hf_id)
        self.features = WhisperFeatureExtractor.from_pretrained(hf_id)
        self.encoder = open_qnn_session(encoder_path)
        self.decoder = open_qnn_session(decoder_path)
        self._lock = threading.Lock()

        tok = self.tokenizer
        self._transcribe_id = tok.convert_tokens_to_ids("<|transcribe|>")
        self._notimestamps_id = tok.convert_tokens_to_ids("<|notimestamps|>")
        self._lang_ids: dict[str, int] = {}
        for token in tok.additional_special_tokens:
            code = token.strip("<|>")
            if 2 <= len(code) <= 3 and code.isalpha() and code.islower():
                self._lang_ids[code] = tok.convert_tokens_to_ids(token)
        self._id_to_lang = {v: k for k, v in self._lang_ids.items()}

    def warmup(self) -> None:
        self.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), "en")

    def transcribe(self, audio: np.ndarray, language: str | None = None,
                   candidates: list[str] | None = None, final: bool = True) -> ASRResult:
        """Transcribe one utterance (<= 30 s of 16 kHz mono float32).

        ``language`` forces the spoken language. Otherwise, with ``candidates``, the
        language is chosen among those codes only (e.g. the two people's languages);
        with neither, Whisper detects it freely.
        """
        start = time.perf_counter()
        with self._lock:
            ids = self._decode(audio[: 30 * SAMPLE_RATE], language, candidates)
        detected = self._id_to_lang.get(ids[1]) if len(ids) > 1 else None
        text = self.tokenizer.decode(ids, skip_special_tokens=True).strip()
        return ASRResult(text, language or detected, (time.perf_counter() - start) * 1000)

    def _decode(self, audio: np.ndarray, language: str | None, candidates: list[str] | None) -> list[int]:
        cfg = self.config
        feats = self.features(audio, sampling_rate=SAMPLE_RATE, return_tensors="np")["input_features"]
        cross_flat = _run(self.encoder, feats)
        kv_cross = [cross_flat[i:i + 2] for i in range(0, len(cross_flat), 2)]
        cross = tuple(x for pair in kv_cross for x in pair)

        sot, eot = cfg.decoder_start_token_id, cfg.eos_token_id
        prefix = [sot]
        if language and language in self._lang_ids:
            prefix += [self._lang_ids[language], self._transcribe_id, self._notimestamps_id]
        cand_ids = [self._lang_ids[c] for c in (candidates or []) if c in self._lang_ids]

        heads, dim, layers = cfg.decoder_attention_heads, cfg.d_model, cfg.decoder_layers
        k_self = np.zeros((heads, 1, dim // heads, MEAN_DECODE_LEN - 1), dtype=np.float32)
        v_self = np.zeros((heads, 1, MEAN_DECODE_LEN - 1, dim // heads), dtype=np.float32)
        kv_self = tuple((k_self, v_self) for _ in range(layers))
        mask = np.full((1, 1, 1, MEAN_DECODE_LEN), MASK_NEG, dtype=np.float32)
        position = np.array([0], dtype=np.int32)
        out = list(prefix)

        for n in range(MEAN_DECODE_LEN - 1):
            input_ids = np.array([[out[n]]], dtype=np.int32)
            mask[:, :, :, MEAN_DECODE_LEN - n - 1] = 0.0
            flat_self = tuple(x for pair in kv_self for x in pair)
            result = _run(self.decoder, input_ids, mask, *flat_self, *cross, position)
            logits = result[0].reshape(-1)
            kv_self = tuple(result[i:i + 2] for i in range(1, len(result), 2))
            position += 1

            if n < len(out) - 1:
                continue  # still feeding the forced prefix
            if n == 0 and len(out) == 1 and cand_ids:
                # Choose the language among the candidates, then force transcription.
                best = max(cand_ids, key=lambda i: logits[i])
                out += [best, self._transcribe_id, self._notimestamps_id]
                continue
            next_id = int(np.argmax(logits))
            out.append(next_id)
            if next_id == eot:
                break
        return out
