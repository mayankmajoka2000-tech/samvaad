"""Benchmark Samvaad on this laptop: speech recognition and translation timing.

    python tools/benchmark.py --runs 10                  # the engines Samvaad would pick (auto)
    python tools/benchmark.py --compare-cpu              # Snapdragon: NPU vs CPU
    .venv\\Scripts\\python tools\\benchmark.py ...          # on Windows

Writes a Markdown table to the console and results to benchmarks/<date>.json, so the
numbers in your presentation are measured on your own laptop.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from samvaad import config  # noqa: E402
from samvaad.engines import create_asr  # noqa: E402
from samvaad.engines.llm import create_llm  # noqa: E402

SENTENCES = [
    ("en", "hi", "Take one 500 mg tablet twice a day, after meals, for 5 days."),
    ("en", "hi", "Your appointment is on Friday, 2 October, at 10 in the morning."),
    ("hi", "en", "मुझे तीन दिन से बुखार और खांसी है।"),
    ("en", "es", "The train to Madrid leaves from platform 4 at 18:45."),
    ("en", "ta", "Please drink plenty of water and rest for two days."),
]


def load_wav(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise SystemExit(f"{path}: please use 16-bit PCM WAV")
    audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != 16000:
        n = int(len(audio) * 16000 / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
    return audio


def summarise(values: list[float]) -> dict:
    values = sorted(values)
    return {"n": len(values), "median": round(statistics.median(values), 1), "mean": round(statistics.fmean(values), 1),
            "p90": round(values[max(0, int(len(values) * 0.9) - 1)], 1), "min": round(values[0], 1)}


def bench_asr(engine, audio: np.ndarray, runs: int, language: str | None) -> dict:
    engine.warmup()
    times, text = [], ""
    for _ in range(runs):
        start = time.perf_counter()
        res = engine.transcribe(audio, language=language)
        times.append((time.perf_counter() - start) * 1000)
        text = res.text
    stats = summarise(times)
    stats["audio_s"] = round(len(audio) / 16000, 2)
    stats["real_time_factor"] = round(stats["median"] / 1000 / stats["audio_s"], 3)
    stats["text"] = text
    return stats


async def bench_llm(llm, runs: int) -> dict:
    if not await llm.health():
        return {"error": f"Translator unreachable ({llm.last_error}). Start Ollama or GenieX first."}
    times, samples = [], []
    for i in range(runs):
        src, tgt, text = SENTENCES[i % len(SENTENCES)]
        tr = await llm.translate(text, src, tgt)
        times.append(tr.ms)
        if i < len(SENTENCES):
            samples.append({"src": text, "translation": tr.text})
    await llm.close()
    return {**summarise(times), "samples": samples, "engine": f"{llm.label} · {getattr(llm, 'provider', '')}"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audio", default=str(ROOT / "samples" / "fox.wav"), help="16-bit PCM WAV file")
    parser.add_argument("--language", default="en", help="Spoken language of the audio (or 'auto')")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--compare-cpu", action="store_true", help="Also run Whisper on the CPU (needs PyTorch)")
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args()

    cfg = config.load()
    results: dict = {"date": datetime.now().isoformat(timespec="seconds"), "machine": machine_name()}
    language = None if args.language == "auto" else args.language

    if Path(args.audio).exists():
        audio = load_wav(args.audio)
        print(f"Audio: {args.audio} ({len(audio) / 16000:.1f} s)\n")
        main_engine = create_asr(cfg["asr"])
        key = "asr_npu" if main_engine.device == "NPU" else "asr_cpu"
        results[key] = bench_asr(main_engine, audio, args.runs, language)
        results[key]["engine"] = f"{main_engine.name} · {main_engine.device}"
        if args.compare_cpu and key == "asr_npu":
            cpu = create_asr({**cfg["asr"], "engine": "faster", "cpu_model_size": cfg["asr"].get("model_size", "base"),
                              "device": "cpu"})
            results["asr_cpu"] = bench_asr(cpu, audio, max(3, args.runs // 3), language)
            results["asr_cpu"]["engine"] = f"{cpu.name} · {cpu.device}"
    else:
        print(f"No audio file at {args.audio}; skipping speech. Pass --audio path\\to\\clip.wav\n")

    if not args.skip_llm:
        results["translation"] = asyncio.run(bench_llm(create_llm(cfg["llm"]), args.runs))

    print("| Stage | Median ms | Mean ms | p90 ms | Runs | Notes |")
    print("| --- | ---: | ---: | ---: | ---: | --- |")
    for key, label in (("asr_npu", "Whisper on NPU"), ("asr_cpu", "Whisper on CPU/GPU"), ("translation", "Qwen3 translation")):
        r = results.get(key)
        if not r:
            continue
        if "error" in r:
            print(f"| {label} | - | - | - | - | {r['error']} |")
            continue
        label = f"{label} ({r['engine']})" if r.get("engine") else label
        note = f"real-time factor {r['real_time_factor']} on {r['audio_s']} s" if "audio_s" in r else ""
        print(f"| {label} | {r['median']} | {r['mean']} | {r['p90']} | {r['n']} | {note} |")
    if "asr_npu" in results and "asr_cpu" in results:
        speedup = results["asr_cpu"]["median"] / results["asr_npu"]["median"]
        print(f"\nNPU is {speedup:.1f}x faster than CPU for speech recognition.")
    for key in ("asr_npu", "asr_cpu"):
        if key in results:
            print(f"\nTranscript: {results[key]['text']}")
            break

    out = ROOT / "benchmarks"
    out.mkdir(exist_ok=True)
    path = out / f"benchmark-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved {path}")


def machine_name() -> str:
    from samvaad import platform_info

    info = platform_info.describe()
    return f"{info['chip']} ({info['os']}, {info['arch']})"


if __name__ == "__main__":
    main()
