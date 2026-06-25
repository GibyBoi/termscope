"""Real-time, fully-offline speech-to-text over system audio and the microphone.

Capture uses WASAPI (via pyaudiowpatch) so we can tap the speaker loopback — what
meeting participants and videos say — alongside the microphone. Each source gets
its own Vosk streaming recognizer; finalized utterances are handed to a callback.

The whole module is optional: if vosk / pyaudiowpatch / numpy aren't installed, or
no model is present, AudioListener reports `available == False` and listening is
simply disabled. The rest of TermScope keeps working.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Callable

from . import paths
from .config import Config

TextCallback = Callable[[str, str], None]  # (text, source) -> None

_SAMPLE_FORMAT_INT16 = 8  # pyaudio.paInt16, hard-coded to avoid import at module load


def _import_audio_stack():
    """Return (pyaudio_module, vosk_module, numpy_module) or raise ImportError."""
    import numpy  # noqa: F401
    import pyaudiowpatch as pyaudio  # noqa: F401
    import vosk  # noqa: F401

    return pyaudio, vosk, numpy


def _model_rank(d: Path) -> tuple:
    """Rank a model directory so the best one sorts last.

    Prefers full models over 'small' ones (much better accuracy), then higher
    version numbers. Naive alphabetical sorting got this wrong: it ranked
    'vosk-model-small-en-us-0.15' above 'vosk-model-en-us-0.22-lgraph'.
    """
    name = d.name.lower()
    quality = 0 if "small" in name else 1
    m = re.search(r"(\d+)\.(\d+)", name)
    version = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    return (quality, version, name)


def find_model_dir(cfg: Config) -> Path | None:
    """Resolve the Vosk model directory from config or the models folder."""
    if cfg.vosk_model_path:
        p = Path(cfg.vosk_model_path)
        return p if p.exists() else None
    candidates = [d for d in paths.models_dir().iterdir() if d.is_dir()]
    # A valid Vosk model directory contains an 'am' subfolder.
    valid = [d for d in candidates if (d / "am").exists()]
    if not valid:
        return None
    # Best model last: full models beat 'small', higher versions beat lower.
    return sorted(valid, key=_model_rank)[-1]


class _SourceWorker:
    """Captures one audio source and streams it through a Vosk recognizer."""

    def __init__(self, source: str, on_text: TextCallback):
        self.source = source  # "system" or "microphone"
        self._on_text = on_text
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream = None
        self._pa = None

    def start(self, pyaudio, vosk, numpy, model) -> None:
        device = self._resolve_device(pyaudio)
        if device is None:
            print(f"[TermScope] no {self.source} device found; skipping.")
            return
        rate = int(device["defaultSampleRate"])
        channels = max(1, int(device.get("maxInputChannels", 1)) or 1)
        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=device["index"],
            frames_per_buffer=4000,
        )
        recognizer = vosk.KaldiRecognizer(model, rate)
        recognizer.SetWords(False)
        self._thread = threading.Thread(
            target=self._loop, args=(recognizer, numpy, channels), daemon=True
        )
        self._thread.start()

    def _resolve_device(self, pyaudio):
        p = pyaudio.PyAudio()
        try:
            wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            p.terminate()
            return None
        try:
            if self.source == "system":
                spk = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
                if not spk.get("isLoopbackDevice"):
                    for lb in p.get_loopback_device_info_generator():
                        if spk["name"] in lb["name"]:
                            return lb
                    return None
                return spk
            mic = p.get_device_info_by_index(wasapi["defaultInputDevice"])
            return mic
        except OSError:
            return None
        finally:
            p.terminate()

    def _loop(self, recognizer, numpy, channels) -> None:
        while not self._stop.is_set():
            try:
                data = self._stream.read(4000, exception_on_overflow=False)
            except OSError:
                break
            if channels > 1:
                samples = numpy.frombuffer(data, dtype=numpy.int16)
                samples = samples.reshape(-1, channels).mean(axis=1).astype(numpy.int16)
                data = samples.tobytes()
            if recognizer.AcceptWaveform(data):
                text = json.loads(recognizer.Result()).get("text", "").strip()
                if text:
                    self._on_text(text, self.source)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
        if self._pa is not None:
            self._pa.terminate()


class AudioListener:
    """Manages capture across the configured sources; start/stop is the toggle."""

    def __init__(self, cfg: Config, on_text: TextCallback):
        self._cfg = cfg
        self._on_text = on_text
        self._workers: list[_SourceWorker] = []
        self._listening = False
        self._lock = threading.Lock()
        self._import_error: str | None = None
        try:
            self._pyaudio, self._vosk, self._numpy = _import_audio_stack()
        except ImportError as exc:
            self._pyaudio = self._vosk = self._numpy = None
            self._import_error = str(exc)

    @property
    def deps_installed(self) -> bool:
        return self._import_error is None

    @property
    def available(self) -> bool:
        """True only if deps are installed AND a model is present."""
        return self.deps_installed and find_model_dir(self._cfg) is not None

    @property
    def is_listening(self) -> bool:
        return self._listening

    def status_reason(self) -> str:
        if not self.deps_installed:
            return f"audio deps not installed ({self._import_error})"
        if find_model_dir(self._cfg) is None:
            return "no Vosk model found (run: python -m termscope.download_model)"
        return "ready"

    def start(self) -> bool:
        with self._lock:
            if self._listening or not self.available:
                return False
            self._vosk.SetLogLevel(-1)
            model = self._vosk.Model(str(find_model_dir(self._cfg)))
            sources = []
            if self._cfg.listen_system_audio:
                sources.append("system")
            if self._cfg.listen_microphone:
                sources.append("microphone")
            for src in sources:
                worker = _SourceWorker(src, self._on_text)
                worker.start(self._pyaudio, self._vosk, self._numpy, model)
                self._workers.append(worker)
            self._listening = True
            return True

    def stop(self) -> None:
        with self._lock:
            for w in self._workers:
                w.stop()
            self._workers.clear()
            self._listening = False

    def toggle(self) -> bool:
        if self._listening:
            self.stop()
            return False
        return self.start()
