#!/usr/bin/env python
"""Record system audio once, then transcribe it with multiple Vosk models for a fair A/B.

    python model_ab_test.py [seconds]

Plays nothing — start your video first. Captures the speaker loopback to a WAV,
then runs every installed model over that identical audio and reports transcript
length and how many dictionary terms each model surfaced.
"""
import json
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from termscope import paths
from termscope.config import Config
from termscope.dictionary import load_entries
from termscope.matcher import Matcher


def resolve_loopback(pyaudio):
    p = pyaudio.PyAudio()
    try:
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        spk = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
        if not spk.get("isLoopbackDevice"):
            for lb in p.get_loopback_device_info_generator():
                if spk["name"] in lb["name"]:
                    return lb
            return None
        return spk
    finally:
        p.terminate()


def record(seconds: int, wav_path: Path) -> tuple[int, int]:
    import numpy
    import pyaudiowpatch as pyaudio

    dev = resolve_loopback(pyaudio)
    if dev is None:
        raise RuntimeError("no system loopback device found")
    rate = int(dev["defaultSampleRate"])
    channels = max(1, int(dev.get("maxInputChannels", 2)) or 2)
    print(f"[record] device={dev['name']!r} rate={rate} channels={channels}")

    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=channels, rate=rate, input=True,
                    input_device_index=dev["index"], frames_per_buffer=4000)
    frames = []
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        data = stream.read(4000, exception_on_overflow=False)
        if channels > 1:
            s = numpy.frombuffer(data, dtype=numpy.int16).reshape(-1, channels)
            data = s.mean(axis=1).astype(numpy.int16).tobytes()
        frames.append(data)
    stream.stop_stream(); stream.close(); p.terminate()

    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"".join(frames))
    print(f"[record] wrote {wav_path} ({sum(len(f) for f in frames)//1024} KB mono@{rate})")
    return rate, len(frames)


def transcribe(wav_path: Path, model_dir: Path, matcher: Matcher) -> dict:
    import vosk
    vosk.SetLogLevel(-1)
    model = vosk.Model(str(model_dir))
    with wave.open(str(wav_path), "rb") as wf:
        rate = wf.getframerate()
        rec = vosk.KaldiRecognizer(model, rate)
        rec.SetWords(False)
        texts = []
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                t = json.loads(rec.Result()).get("text", "").strip()
                if t:
                    texts.append(t)
        t = json.loads(rec.FinalResult()).get("text", "").strip()
        if t:
            texts.append(t)
    full = " ".join(texts)
    matches = matcher.find(full, set())
    terms = sorted({m.entry.term for m in matches})
    return {"utterances": len(texts), "chars": len(full), "terms": terms,
            "n_terms": len(terms), "text": full}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 75

    cfg = Config.load()
    entries = load_entries(paths.bundled_term_files(), set(cfg.enabled_categories))
    matcher = Matcher(entries)

    wav = Path(__file__).resolve().parent / "ab_capture.wav"
    print(f"[run] recording {seconds}s of system audio — make sure the video is playing...")
    record(seconds, wav)

    models = sorted([d for d in paths.models_dir().iterdir() if d.is_dir() and (d / "am").exists()])
    print(f"\n[run] transcribing with {len(models)} model(s)...\n")
    results = {}
    for md in models:
        print(f"[transcribe] {md.name} ...", flush=True)
        results[md.name] = transcribe(wav, md, matcher)

    print("\n" + "=" * 64)
    print("  MODEL A/B — same audio, different Vosk models")
    print("=" * 64)
    for name, r in results.items():
        print(f"\n  {name}")
        print(f"    utterances={r['utterances']}  chars={r['chars']}  terms={r['n_terms']}")
        print(f"    terms: {', '.join(r['terms']) or '(none)'}")
    for name, r in results.items():
        print(f"\n--- transcript [{name}] ---\n{r['text'][:1200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
