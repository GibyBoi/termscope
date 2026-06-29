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
WINDOW_SECONDS = 3.0        # audio transcribed per pass
OVERLAP_SECONDS = 0.4       # carried between windows so words aren't clipped
SILENCE_FLOOR = 60          # int16 peak below which a window is skipped
LEVEL_INTERVAL = 0.35       # how often the heartbeat emits the level meter value


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

        win = int(rate * WINDOW_SECONDS)
        carry = int(rate * OVERLAP_SECONDS)
        floor = SILENCE_FLOOR / 32768.0
        buf = np.zeros(0, dtype=np.float32)
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
            buf = np.concatenate([buf, arr])
            if arr.size:
                self.peak = max(self.peak, int(float(np.abs(arr).max()) * 32768))
            if len(buf) >= win:
                window = buf
                buf = buf[-carry:].copy() if carry > 0 else np.zeros(0, dtype=np.float32)
                if float(np.abs(window).max()) >= floor:
                    try:
                        self._jobs.put_nowait((_resample_16k(window, rate, np), self.source))
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

    while not stop.is_set():
        try:
            audio, source = jobs.get(timeout=0.3)
        except queue.Empty:
            continue
        try:
            segments, _ = model.transcribe(audio, language="en", beam_size=1,
                                           vad_filter=True, condition_on_previous_text=False)
            text = " ".join(s.text.strip() for s in segments).strip()
        except Exception:
            text = ""
        if text:
            emit({"event": "text", "text": text, "source": source})

    try:
        pa.terminate()  # exactly once, after everything has stopped
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
