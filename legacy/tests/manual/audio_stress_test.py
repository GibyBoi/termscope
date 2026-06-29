#!/usr/bin/env python
"""Audio stress test: drive the real AudioListener + Matcher against live system audio.

Plays nothing itself — you start the video; this captures the speaker loopback,
transcribes it with Vosk (the same code path the app uses) and logs every
finalized utterance plus any jargon the matcher finds.

    python audio_stress_test.py [seconds]   # default 75s

Writes a JSONL transcript and prints a summary. System audio only (mic disabled)
so every match is attributable to the video.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from termscope import paths
from termscope.config import Config
from termscope.dictionary import load_entries
from termscope.matcher import Matcher
from termscope.audio import AudioListener


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 75

    cfg = Config.load()
    cfg.listen_system_audio = True
    cfg.listen_microphone = False  # isolate the video's audio

    entries = load_entries(paths.bundled_term_files(), set(cfg.enabled_categories))
    matcher = Matcher(entries)
    print(f"[setup] {len(entries)} terms loaded ({', '.join(cfg.enabled_categories)})")

    log_path = Path(__file__).resolve().parent / "stress_test_log.jsonl"
    log = log_path.open("w", encoding="utf-8")

    state = {
        "utterances": 0,
        "chars": 0,
        "matches": 0,
        "terms": {},  # term -> count
        "start": time.monotonic(),
    }

    def on_text(text: str, source: str) -> None:
        t = round(time.monotonic() - state["start"], 1)
        state["utterances"] += 1
        state["chars"] += len(text)
        found = [m.entry.term for m in matcher.find(text, set())]
        for term in found:
            state["matches"] += 1
            state["terms"][term] = state["terms"].get(term, 0) + 1
        tag = ("  >> MATCH: " + ", ".join(found)) if found else ""
        print(f"[{t:6.1f}s] {text}{tag}", flush=True)
        log.write(json.dumps({"t": t, "source": source, "text": text, "matched": found}) + "\n")
        log.flush()

    listener = AudioListener(cfg, on_text)
    print(f"[setup] audio available: {listener.available} ({listener.status_reason()})")
    if not listener.available:
        print("[abort] audio not available; cannot run stress test.")
        return 1

    if not listener.start():
        print("[abort] failed to start capture (device busy or no loopback device).")
        return 1

    print(f"[run] capturing system audio for {duration}s — make sure the video is playing...\n")
    try:
        time.sleep(duration)
    except KeyboardInterrupt:
        print("\n[run] interrupted early.")
    finally:
        listener.stop()
        log.close()

    elapsed = round(time.monotonic() - state["start"], 1)
    print("\n" + "=" * 58)
    print("  AUDIO STRESS TEST SUMMARY")
    print("=" * 58)
    print(f"  Duration captured : {elapsed}s")
    print(f"  Utterances        : {state['utterances']}")
    print(f"  Chars transcribed : {state['chars']}")
    print(f"  Total term hits   : {state['matches']}")
    print(f"  Unique terms      : {len(state['terms'])}")
    if state["terms"]:
        print("  Terms surfaced:")
        for term, n in sorted(state["terms"].items(), key=lambda kv: -kv[1]):
            print(f"    {n:3d}x  {term}")
    else:
        print("  (no tracked jargon matched in the transcript)")
    print(f"\n  Full transcript: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
