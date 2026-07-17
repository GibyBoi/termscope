#!/usr/bin/env python
"""TermScope audio sidecar (faster-whisper, fully offline) — continuous capture.

Spawned by the Tauri app. Continuously captures system audio (WASAPI loopback)
and/or the microphone, reports a live audio level, and transcribes speech offline
with faster-whisper. Emits JSON lines on stdout:

  {"event":"status","ready":true,"model":"whisper-<size>"}
  {"event":"status","ready":false,"reason":"..."}
  {"event":"warn","source":"...","reason":"..."}
  {"event":"level","source":"...","value":0-100}        ~3x/sec, for the UI meter
  {"event":"text","text":"...","source":"system"|"microphone"}

Stops when the parent closes our stdin or the process is killed.

IMPORTANT: one shared PyAudio instance is used for all sources and is terminated
exactly once at shutdown. Per-worker PyAudio()/terminate() caused a native
PortAudio crash (process death, no Python traceback) when one source failed to
open while another was capturing.
"""
from __future__ import annotations

import argparse
import json
import math
import queue
import sys
import threading
import time

MODEL_SIZE = "base.en"      # tiny.en | base.en | small.en | medium.en
SILENCE_FLOOR = 60          # int16 peak below which audio counts as silence
LEVEL_INTERVAL = 0.35       # how often the heartbeat emits the level meter value

# Utterance endpointing (see Endpointer). Speech is cut at natural pauses and
# transcribed as WHOLE utterances — never as fixed windows with overlap. The
# old 3s-window + 0.4s-overlap design transcribed the overlap twice (doubled
# words at every boundary: "if if", "putting putting") and let Whisper
# punctuate each 3s slice as its own sentence (stray mid-sentence periods).
SILENCE_HANG = 0.6          # trailing quiet (s) that ends an utterance
PRE_ROLL = 0.25             # quiet lead-in (s) kept so onsets aren't clipped
MIN_UTTERANCE = 0.3         # utterances shorter than this (s) are noise; dropped
MAX_UTTERANCE = 12.0        # force a cut after this much buffered audio (s)
FORCED_CUT_SEARCH = 2.0     # forced cuts pick the quietest spot in this tail (s)
FORCED_CUT_SPAN = 0.1       # width (s) of the quietest-spot search window


def emit(obj: dict) -> None:
    try:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def _resample_16k(x_f32, src_rate, np):
    """float32 mono [-1,1] -> float32 mono at 16 kHz (what Whisper expects)."""
    if src_rate == 16000:
        return x_f32
    n = max(1, int(len(x_f32) * 16000 / src_rate))
    idx = np.linspace(0, len(x_f32) - 1, n)
    return np.interp(idx, np.arange(len(x_f32)), x_f32).astype(np.float32)


class Endpointer:
    """Cuts a continuous mono float32 stream into whole utterances at pauses.

    Pure state machine (numpy in, list of utterances out) so it is testable
    without any audio device. `feed(chunk)` returns zero or more
    `(samples, forced)` tuples:

    - An utterance ends when speech has been heard and `SILENCE_HANG` seconds
      of quiet follow; the utterance keeps `PRE_ROLL` of lead-in/out quiet so
      Whisper sees word onsets, and `forced` is False.
    - If speech runs past `MAX_UTTERANCE` with no pause, the buffer is cut at
      the QUIETEST `FORCED_CUT_SPAN` stretch of its recent tail and the
      remainder carries over — a split, never an overlap, so no audio is ever
      transcribed twice; `forced` is True (the consumer may de-dup one
      boundary word for a word clipped mid-cut).
    - While idle (no speech yet), only `PRE_ROLL` of audio is retained.
    """

    def __init__(self, rate, np):
        self._rate = rate
        self._np = np
        self._buf = np.zeros(0, dtype=np.float32)
        self._has_speech = False
        self._quiet = 0  # trailing quiet samples
        self._speech = 0  # samples of actual speech heard (loud chunks)
        self._floor = SILENCE_FLOOR / 32768.0

    def feed(self, arr):
        np = self._np
        rate = self._rate
        out = []
        self._buf = np.concatenate([self._buf, arr])
        if arr.size:
            if float(np.abs(arr).max()) >= self._floor:
                self._has_speech = True
                self._speech += arr.size
                self._quiet = 0
            else:
                self._quiet += arr.size

        if not self._has_speech:
            # Idle: keep only a short pre-roll so the eventual onset is intact.
            keep = int(rate * PRE_ROLL)
            if len(self._buf) > keep:
                self._buf = self._buf[-keep:]
            return out

        hang = int(rate * SILENCE_HANG)
        if self._quiet >= hang:
            # Natural pause: emit up to a little past the end of speech. The
            # minimum is judged on SPEECH heard, not buffer length — padding
            # must not qualify a sub-minimum blip.
            end = len(self._buf) - self._quiet + int(rate * PRE_ROLL)
            utt = self._buf[: max(0, end)]
            if self._speech >= int(rate * MIN_UTTERANCE):
                out.append((utt, False))
            self._buf = np.zeros(0, dtype=np.float32)
            self._has_speech = False
            self._quiet = 0
            self._speech = 0
            return out

        if len(self._buf) >= int(rate * MAX_UTTERANCE):
            # No pause in a long stretch: split at the quietest recent spot.
            span = int(rate * FORCED_CUT_SPAN)
            search = min(int(rate * FORCED_CUT_SEARCH), len(self._buf) - span)
            tail = self._buf[-search - span : ]
            energy = np.abs(tail)
            # Sliding-sum of |x| over `span` samples; the minimum is the cut.
            csum = np.concatenate([[0.0], np.cumsum(energy, dtype=np.float64)])
            sums = csum[span:] - csum[:-span]
            k = int(np.argmin(sums))
            cut = len(self._buf) - (search + span) + k + span // 2
            utt, rest = self._buf[:cut], self._buf[cut:]
            if len(utt) >= int(rate * MIN_UTTERANCE):
                out.append((utt, True))
            self._buf = rest.copy()
            # Speech state continues into the carried remainder.
        return out


class SourceWorker(threading.Thread):
    """Continuously captures one source: tracks peak level + queues windows.

    Uses the SHARED PyAudio instance `p`; it never creates or terminates one.
    """

    def __init__(self, source, pa_module, p, numpy, jobs, stop):
        super().__init__(daemon=True)
        self.source = source
        self._pa = pa_module   # module, for constants (paInt16, paWASAPI)
        self._p = p            # shared PyAudio instance, for methods
        self._np = numpy
        self._jobs = jobs
        self._stop = stop
        self.peak = 0          # most recent capture peak, read by the heartbeat

    def _resolve_device(self):
        p = self._p
        try:
            w = p.get_host_api_info_by_type(self._pa.paWASAPI)
        except OSError:
            return None
        try:
            if self.source == "system":
                spk = p.get_device_info_by_index(w["defaultOutputDevice"])
                if not spk.get("isLoopbackDevice"):
                    for lb in p.get_loopback_device_info_generator():
                        if spk["name"] in lb["name"]:
                            return lb
                    return None
                return spk
            return p.get_device_info_by_index(w["defaultInputDevice"])
        except OSError:
            return None

    def _open(self, dev):
        """Try a matrix of (format, rate, channels); return (stream, rate, ch,
        is_float) or None. Intel SST mic arrays often need float32 and/or an
        unusual channel count, so we cast a wide net and log what failed."""
        base = int(dev["defaultSampleRate"])
        reported = max(1, int(dev.get("maxInputChannels", 1)) or 1)
        rates = [base] + [r for r in (48000, 44100, 16000) if r != base]
        chan_opts = list(dict.fromkeys([reported, 2, 1, 4]))
        errs = []
        for fmt, is_float in ((self._pa.paInt16, False), (self._pa.paFloat32, True)):
            for rate in rates:
                for chans in chan_opts:
                    try:
                        st = self._p.open(format=fmt, channels=chans, rate=rate, input=True,
                                          input_device_index=dev["index"], frames_per_buffer=4000)
                        return st, rate, chans, is_float
                    except OSError as e:
                        errs.append(f"{'f32' if is_float else 'i16'}/{rate}/{chans}({e})")
        emit({"event": "warn", "source": self.source,
              "reason": "open failed — " + "; ".join(errs[-5:])})
        return None

    def run(self):
        np = self._np
        dev = self._resolve_device()
        if dev is None:
            emit({"event": "warn", "source": self.source, "reason": "no device found"})
            return
        opened = self._open(dev)
        if opened is None:
            return  # _open already emitted a detailed warn
        st, rate, ch, is_float = opened

        endpointer = Endpointer(rate, np)
        while not self._stop.is_set():
            try:
                data = st.read(4000, exception_on_overflow=False)
            except OSError:
                break
            if is_float:
                arr = np.frombuffer(data, dtype=np.float32)
            else:
                arr = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            if ch > 1:
                arr = arr.reshape(-1, ch).mean(axis=1)
            if arr.size:
                self.peak = max(self.peak, int(float(np.abs(arr).max()) * 32768))
            for utt, forced in endpointer.feed(arr):
                try:
                    self._jobs.put_nowait((_resample_16k(utt, rate, np), self.source, forced))
                except queue.Full:
                    pass
        try:
            st.stop_stream()
            st.close()
        except Exception:
            pass


def _watch_stdin(stop):
    try:
        for _ in sys.stdin:
            pass
    except Exception:
        pass
    stop.set()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=MODEL_SIZE)
    ap.add_argument("--models-dir", default="")
    ap.add_argument("--sources", default="system,microphone")
    args = ap.parse_args()

    try:
        import numpy
        import pyaudiowpatch as pyaudio
        from faster_whisper import WhisperModel
    except ImportError as exc:
        emit({"event": "status", "ready": False, "reason": f"audio deps missing: {exc}"})
        return 1

    try:
        model = WhisperModel(args.model, device="cpu", compute_type="int8",
                             download_root=(args.models_dir or None))
    except Exception as exc:
        emit({"event": "status", "ready": False, "reason": f"whisper load failed: {exc}"})
        return 1

    emit({"event": "status", "ready": True, "model": f"whisper-{args.model}"})

    stop = threading.Event()
    threading.Thread(target=_watch_stdin, args=(stop,), daemon=True).start()
    jobs: "queue.Queue" = queue.Queue(maxsize=8)

    pa = pyaudio.PyAudio()  # ONE shared instance for all sources
    workers = []
    for src in [s.strip() for s in args.sources.split(",") if s.strip()]:
        w = SourceWorker(src, pyaudio, pa, numpy, jobs, stop)
        w.start()
        workers.append(w)

    # Heartbeat: always report a level for every source (even during silence or
    # if a source failed to open), so the UI meter is always alive.
    def heartbeat():
        while not stop.is_set():
            time.sleep(LEVEL_INTERVAL)
            for w in workers:
                pk = w.peak
                w.peak = 0
                val = int(min(100, round(math.sqrt(max(0, pk) / 32768.0) * 100)))
                emit({"event": "level", "source": w.source, "value": val})
    threading.Thread(target=heartbeat, daemon=True).start()

    # Across a FORCED cut (a word may be clipped mid-split and heard on both
    # sides) the first word of the next utterance is dropped when it repeats
    # the last word of the previous one. Natural-pause boundaries are left
    # alone — "No. No." across a real pause is legitimate speech.
    strip_tok = lambda w: "".join(c for c in w.lower() if c.isalnum())
    last_word: dict = {}   # source -> last emitted token (normalized)
    after_forced: dict = {}  # source -> was the previous utterance force-cut?

    while not stop.is_set():
        try:
            audio, source, forced = jobs.get(timeout=0.3)
        except queue.Empty:
            continue
        try:
            segments, _ = model.transcribe(audio, language="en", beam_size=1,
                                           vad_filter=True, condition_on_previous_text=False)
            text = " ".join(s.text.strip() for s in segments).strip()
        except Exception:
            text = ""
        if text:
            words = text.split()
            if (
                after_forced.get(source)
                and words
                and strip_tok(words[0])
                and strip_tok(words[0]) == last_word.get(source)
            ):
                words = words[1:]
            text = " ".join(words)
        if text:
            last_word[source] = strip_tok(text.split()[-1])
            emit({"event": "text", "text": text, "source": source})
        after_forced[source] = forced

    try:
        pa.terminate()  # exactly once, after everything has stopped
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
