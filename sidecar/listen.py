#!/usr/bin/env python
"""TermScope audio sidecar (fully offline) — continuous capture + dictation.

Spawned by the Tauri app. Continuously captures system audio (WASAPI loopback)
and/or the microphone, reports a live audio level, and transcribes speech
offline. Engines: faster-whisper (default), or Moonshine / NVIDIA Parakeet via
sherpa-onnx (`--engine`, models auto-downloaded on first use). Emits JSON lines
on stdout:

  {"event":"status","ready":true,"model":"..."}
  {"event":"status","ready":false,"reason":"..."}
  {"event":"warn","source":"...","reason":"..."}
  {"event":"level","source":"...","value":0-100}        ~3x/sec, for the UI meter
  {"event":"text","text":"...","source":"system"|"microphone"}
  {"event":"dictation","text":"..."}                    a finished dictation

Commands arrive as JSON lines on stdin (`{"cmd":"dictate","on":true|false}`);
stdin EOF still means shut down. While dictation is ON, raw microphone audio is
buffered (RAM only) and mic utterance streaming pauses; on OFF the WHOLE
recording is transcribed in one pass (split at quiet points only past the
engine's decode limit) — the SpeakEasy approach: one pass over the full audio
gives coherent punctuation and can never double a word at a seam. The
utterance streaming (Endpointer) remains the pipeline for Listening — jargon
cards and History tallies — where live, incremental text is the point.

IMPORTANT: one shared PyAudio instance is used for all sources and is terminated
exactly once at shutdown. Per-worker PyAudio()/terminate() caused a native
PortAudio crash (process death, no Python traceback) when one source failed to
open while another was capturing.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import queue
import sys
import tarfile
import threading
import time
import urllib.request

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
    """float32 mono [-1,1] -> float32 mono at 16 kHz (what the engines expect)."""
    if src_rate == 16000:
        return x_f32
    n = max(1, int(len(x_f32) * 16000 / src_rate))
    idx = np.linspace(0, len(x_f32) - 1, n)
    return np.interp(idx, np.arange(len(x_f32)), x_f32).astype(np.float32)


# ---------------------------------------------------------------------------
# Transcription engines
# ---------------------------------------------------------------------------

# sherpa-onnx model catalog (same release archives SpeakEasy ships).
SHERPA_MODELS = {
    "moonshine": {
        "label": "Moonshine Base",
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-moonshine-base-en-int8.tar.bz2",
        "dir": "sherpa-onnx-moonshine-base-en-int8",
    },
    "parakeet": {
        "label": "Parakeet 0.6B v2",
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2",
        "dir": "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
    },
}


def _find_model_file(model_dir, patterns, prefer_int8=True):
    files = sorted(os.listdir(model_dir))
    matches = [f for f in files if any(p in f.lower() for p in patterns)]
    if not matches:
        raise FileNotFoundError(f"no {patterns} file in {model_dir}")
    if prefer_int8:
        for f in matches:
            if "int8" in f:
                return os.path.join(model_dir, f)
    for f in matches:
        if "int8" not in f:
            return os.path.join(model_dir, f)
    return os.path.join(model_dir, matches[0])


def _ensure_sherpa_model(engine, models_dir):
    """Download + extract the engine's model archive on first use. Progress is
    surfaced through status events so Settings can show what's happening."""
    info = SHERPA_MODELS[engine]
    dest = os.path.join(models_dir, info["dir"])
    if os.path.isdir(dest) and any(f.endswith(".onnx") for f in os.listdir(dest)):
        return dest
    os.makedirs(models_dir, exist_ok=True)
    archive = os.path.join(models_dir, info["dir"] + ".tar.bz2")
    last_pct = [-10]

    def hook(blocks, block_size, total):
        if total <= 0:
            return
        pct = int(min(99, blocks * block_size * 100 / total))
        if pct >= last_pct[0] + 5:
            last_pct[0] = pct
            emit({"event": "status", "ready": False,
                  "reason": f"downloading {info['label']} model… {pct}%"})

    emit({"event": "status", "ready": False,
          "reason": f"downloading {info['label']} model…"})
    urllib.request.urlretrieve(info["url"], archive, reporthook=hook)
    emit({"event": "status", "ready": False,
          "reason": f"unpacking {info['label']} model…"})
    with tarfile.open(archive, "r:bz2") as tar:
        try:
            tar.extractall(models_dir, filter="data")
        except TypeError:  # Python < 3.12 has no extract filters
            tar.extractall(models_dir)
    try:
        os.remove(archive)
    except OSError:
        pass
    if not os.path.isdir(dest):
        raise FileNotFoundError(f"archive did not contain {info['dir']}")
    return dest


class WhisperEngine:
    """faster-whisper (the original engine). Decodes ~30s max per pass, so
    long dictations are split at quiet points (`needs_split`)."""

    needs_split = True

    def __init__(self, model_size, models_dir):
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model_size, device="cpu", compute_type="int8",
                                   download_root=(models_dir or None))
        self.name = f"whisper-{model_size}"

    def transcribe(self, audio_16k):
        segments, _ = self._model.transcribe(audio_16k, language="en", beam_size=1,
                                             vad_filter=True,
                                             condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()


class SherpaEngine:
    """Moonshine / Parakeet via sherpa-onnx. Transducer-family models: faster
    than Whisper on CPU and far less prone to hallucinated punctuation."""

    needs_split = False

    def __init__(self, engine, models_dir):
        import sherpa_onnx

        model_dir = _ensure_sherpa_model(engine, models_dir)
        tokens = _find_model_file(model_dir, ["tokens"], prefer_int8=False)
        if engine == "moonshine":
            self._rec = sherpa_onnx.OfflineRecognizer.from_moonshine(
                preprocessor=_find_model_file(model_dir, ["preprocess"]),
                encoder=_find_model_file(model_dir, ["encode"]),
                uncached_decoder=_find_model_file(model_dir, ["uncached_decode"]),
                cached_decoder=_find_model_file(model_dir, ["cached_decode"]),
                tokens=tokens,
                num_threads=4,
            )
        else:  # parakeet
            self._rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=_find_model_file(model_dir, ["encoder"]),
                decoder=_find_model_file(model_dir, ["decoder"]),
                joiner=_find_model_file(model_dir, ["joiner"]),
                tokens=tokens,
                num_threads=4,
                model_type="nemo_transducer",
            )
        self.name = SHERPA_MODELS[engine]["label"]

    def transcribe(self, audio_16k):
        s = self._rec.create_stream()
        s.accept_waveform(16000, audio_16k)
        self._rec.decode_stream(s)
        return (s.result.text or "").strip()


def make_engine(engine, model_size, models_dir):
    """Build the requested engine; sherpa problems fall back to whisper with a
    visible warning rather than dying silently."""
    if engine in SHERPA_MODELS:
        try:
            return SherpaEngine(engine, models_dir)
        except ImportError:
            emit({"event": "warn", "source": "engine",
                  "reason": f"{engine} needs sherpa-onnx (pip install sherpa-onnx); using whisper"})
        except Exception as exc:
            emit({"event": "warn", "source": "engine",
                  "reason": f"{engine} unavailable ({exc}); using whisper"})
    return WhisperEngine(model_size, models_dir)


WHISPER_MAX_SECONDS = 28  # whisper decodes ~30s max per pass


def split_at_quiet(samples, rate, max_seconds, np):
    """Split long audio at the quietest 200ms of each boundary window so a
    limited decoder never silently truncates. A split, never an overlap."""
    limit = int(max_seconds * rate)
    if len(samples) <= limit:
        return [samples]
    parts = []
    start = 0
    while len(samples) - start > limit:
        lo = start + int((max_seconds - 8) * rate)
        hi = start + limit
        win = int(0.2 * rate)
        seg = np.abs(samples[lo:hi])
        csum = np.concatenate([[0.0], np.cumsum(seg, dtype=np.float64)])
        sums = csum[win:] - csum[:-win]
        cut = lo + int(np.argmin(sums)) + win // 2
        parts.append(samples[start:cut])
        start = cut
    parts.append(samples[start:])
    return parts


# ---------------------------------------------------------------------------
# Dictation recording
# ---------------------------------------------------------------------------

DICTATION_MAX_SECONDS = 300  # hard RAM cap on one recording (~19 MB at 16k)


class DictationRecorder:
    """Buffers raw microphone audio (RAM only) while dictation is on. On stop
    the recording keeps rolling for a short TAIL (so releasing the hotkey
    mid-word never clips the ending), then the whole recording is queued for a
    single transcription pass."""

    def __init__(self, np, jobs):
        self._np = np
        self._jobs = jobs
        self._lock = threading.Lock()
        self._chunks = []
        self._rate = 16000
        self._timer = None
        self.on = False

    def feed(self, arr, rate):
        with self._lock:
            if not self.on:
                return
            self._rate = rate
            if sum(len(c) for c in self._chunks) < rate * DICTATION_MAX_SECONDS:
                self._chunks.append(arr.copy())

    def set(self, on, tail=0.0):
        with self._lock:
            if on and not self.on:
                if self._timer is not None:  # can't happen via the app's state
                    self._timer.cancel()     # machine, but never merge takes
                    self._timer = None
                self._chunks = []
                self.on = True
                return
            if not on and self.on and self._timer is None:
                if tail > 0:
                    # Keep capturing through the tail, then finalize.
                    self._timer = threading.Timer(tail, self._finalize)
                    self._timer.daemon = True
                    self._timer.start()
                    return
            else:
                return
        self._finalize()

    def _finalize(self):
        np = self._np
        with self._lock:
            if not self.on:
                return
            self.on = False
            self._timer = None
            chunks, rate = self._chunks, self._rate
            self._chunks = []
        audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
        try:
            # Always queued, even empty — the app is waiting on a completion.
            self._jobs.put((_resample_16k(audio, rate, np), "microphone", False, True))
        except Exception:
            pass


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

    def __init__(self, source, pa_module, p, numpy, jobs, stop, recorder=None):
        super().__init__(daemon=True)
        self.source = source
        self._pa = pa_module   # module, for constants (paInt16, paWASAPI)
        self._p = p            # shared PyAudio instance, for methods
        self._np = numpy
        self._jobs = jobs
        self._stop = stop
        self._recorder = recorder  # DictationRecorder, mic worker only
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
        # The stream is genuinely open now (this is also the moment Windows
        # lights its own mic-in-use indicator) — tell the app, so the pill can
        # stop showing "starting" the instant audio is real.
        emit({"event": "capturing", "source": self.source})

        endpointer = Endpointer(rate, np)
        was_dictating = False
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

            # Dictation (mic only): buffer raw audio for the one-pass
            # transcription and pause utterance streaming so nothing is
            # transcribed twice. The endpointer restarts fresh afterwards.
            dictating = bool(self._recorder and self._recorder.on)
            if dictating:
                self._recorder.feed(arr, rate)
                was_dictating = True
                continue
            if was_dictating:
                was_dictating = False
                endpointer = Endpointer(rate, np)
            for utt, forced in endpointer.feed(arr):
                try:
                    self._jobs.put_nowait((_resample_16k(utt, rate, np), self.source, forced, False))
                except queue.Full:
                    pass
        try:
            st.stop_stream()
            st.close()
        except Exception:
            pass


def _watch_stdin(stop, recorder):
    """stdin carries commands as JSON lines; EOF still means shut down."""
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                cmd = json.loads(line)
            except Exception:
                continue
            if cmd.get("cmd") == "dictate" and recorder is not None:
                try:
                    tail = max(0.0, min(5.0, float(cmd.get("tail", 0.0))))
                except (TypeError, ValueError):
                    tail = 0.0
                recorder.set(bool(cmd.get("on")), tail)
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
    ap.add_argument("--engine", default="whisper",
                    choices=["whisper", "moonshine", "parakeet"])
    args = ap.parse_args()

    try:
        import numpy
        import pyaudiowpatch as pyaudio
    except ImportError as exc:
        emit({"event": "status", "ready": False, "reason": f"audio deps missing: {exc}"})
        return 1

    try:
        engine = make_engine(args.engine, args.model, args.models_dir)
    except Exception as exc:
        emit({"event": "status", "ready": False, "reason": f"engine load failed: {exc}"})
        return 1

    emit({"event": "status", "ready": True, "model": engine.name})

    stop = threading.Event()
    # The queue is unbounded-ish for dictation completions (put), bounded for
    # streaming (put_nowait + drop) — a dictation result must never be lost.
    jobs: "queue.Queue" = queue.Queue(maxsize=8)
    recorder = DictationRecorder(numpy, jobs)
    threading.Thread(target=_watch_stdin, args=(stop, recorder), daemon=True).start()

    pa = pyaudio.PyAudio()  # ONE shared instance for all sources
    workers = []
    for src in [s.strip() for s in args.sources.split(",") if s.strip()]:
        w = SourceWorker(src, pyaudio, pa, numpy, jobs, stop,
                         recorder=(recorder if src == "microphone" else None))
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
            audio, source, forced, is_dictation = jobs.get(timeout=0.3)
        except queue.Empty:
            continue
        if is_dictation:
            # A finished dictation: one pass over the whole recording (split at
            # quiet points only when the engine's decoder demands it). Always
            # answered, even empty — the app is waiting on this completion.
            text = ""
            try:
                if audio.size:
                    parts = (split_at_quiet(audio, 16000, WHISPER_MAX_SECONDS, numpy)
                             if engine.needs_split else [audio])
                    text = " ".join(t for t in (engine.transcribe(p) for p in parts) if t).strip()
            except Exception as exc:
                emit({"event": "warn", "source": "dictation", "reason": str(exc)})
            emit({"event": "dictation", "text": text})
            continue
        try:
            text = engine.transcribe(audio)
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
