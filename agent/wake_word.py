"""
agent/wake_word.py - "Hey Meera" / "Hey Jarvis" background wake word detection

Runs a background thread that continuously monitors microphone input for wake words.
When detected, triggers a callback that starts voice recording.

Features:
  - Scans ~/.oblivion/models/ for custom ONNX models (e.g., hey_meera.onnx)
  - Pre-trained models: hey_jarvis, alexa, hey_mycroft
  - Environment variable WAKE_WORD_MODEL to select active model
  - 100% local, low-CPU (~2%)
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

_ww_available: Optional[bool] = None


def is_available() -> bool:
    """Check if openwakeword and sounddevice are installed."""
    global _ww_available
    if _ww_available is not None:
        return _ww_available
    try:
        import openwakeword
        import sounddevice
        import numpy
        _ww_available = True
    except ImportError:
        _ww_available = False
    return _ww_available


def get_custom_model_dir() -> Path:
    """Return ~/.oblivion/models/ directory where user can place custom .onnx models."""
    custom_dir = Path.home() / ".oblivion" / "models"
    custom_dir.mkdir(parents=True, exist_ok=True)
    return custom_dir


def find_custom_models() -> dict[str, Path]:
    """Scan ~/.oblivion/models/ and assets/ for custom .onnx wake word models."""
    models = {}
    search_dirs = [
        get_custom_model_dir(),
        Path.home() / "ai-agent" / "assets",
        Path(__file__).parent.parent / "assets",
    ]
    for d in search_dirs:
        if d.exists() and d.is_dir():
            for p in d.glob("*.onnx"):
                name = p.stem.lower().replace("_v0.1", "").replace("_v1", "")
                models[name] = p
    return models


def list_available_wake_words() -> list[str]:
    """Return list of all available wake word models (pre-trained + custom)."""
    if not is_available():
        return []
    names = set()
    custom = find_custom_models()
    names.update(custom.keys())

    try:
        import openwakeword
        paths = openwakeword.get_pretrained_model_paths()
        for p in paths:
            name = os.path.basename(p).replace(".onnx", "")
            if "_v" in name:
                name = name.rsplit("_v", 1)[0]
            names.add(name)
    except Exception:
        pass

    return sorted(list(names))


class WakeWordDetector:
    DEFAULT_WAKE_WORDS = ["hey_jarvis"]

    def __init__(
        self,
        on_wake: Callable[[], None],
        on_error: Optional[Callable[[str], None]] = None,
        wake_words: Optional[list[str]] = None,
        sensitivity: float = 0.5,
    ):
        self.on_wake = on_wake
        self.on_error = on_error

        selected_model = os.getenv("WAKE_WORD_MODEL", "").strip().lower()
        if not selected_model:
            custom_models = find_custom_models()
            if "hey_meera" in custom_models or "meera" in custom_models:
                selected_model = "hey_meera" if "hey_meera" in custom_models else "meera"
            else:
                selected_model = "hey_jarvis"

        self.wake_words = wake_words or [selected_model]
        self.sensitivity = sensitivity
        self.listening = False
        self._thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._model = None
        self._loaded = False

    def _lazy_load(self) -> bool:
        if self._loaded:
            return True

        try:
            import openwakeword
            from openwakeword.model import Model

            all_pretrained = openwakeword.get_pretrained_model_paths()
            custom_models = find_custom_models()
            selected_paths = []

            for word in self.wake_words:
                word_clean = word.lower().strip()
                if word_clean in custom_models:
                    selected_paths.append(str(custom_models[word_clean]))
                else:
                    match = next(
                        (p for p in all_pretrained if word_clean in os.path.basename(p).lower()),
                        None,
                    )
                    if match:
                        selected_paths.append(match)

            if not selected_paths:
                if all_pretrained:
                    selected_paths = [all_pretrained[0]]

            if not selected_paths:
                self._notify_error(f"No wake word models found for '{self.wake_words}'")
                return False

            self._model = Model(wakeword_model_paths=selected_paths)
            self._loaded = True
            return True

        except Exception as e:
            self._notify_error(f"Failed to load wake word model: {e}")
            return False

    def _notify_error(self, msg: str) -> None:
        if self.on_error:
            try:
                self.on_error(msg)
            except Exception:
                pass

    def start(self) -> bool:
        if self.listening:
            return True

        if not is_available():
            self._notify_error("openwakeword not installed. Run: uv pip install openwakeword")
            return False

        if not self._lazy_load():
            return False

        self._stop_flag.clear()
        self._thread = threading.Thread(
            target=self._listen_loop,
            name="wake-word-listener",
            daemon=True,
        )
        self.listening = True
        self._thread.start()
        return True

    def stop(self) -> None:
        if not self.listening:
            return
        self._stop_flag.set()
        self.listening = False
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def _listen_loop(self) -> None:
        import sounddevice as sd
        import numpy as np

        SAMPLE_RATE = 16000
        CHUNK_SIZE = 1280

        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=CHUNK_SIZE,
            )
            stream.start()

            last_trigger_time = 0.0
            COOLDOWN = 2.0

            while not self._stop_flag.is_set():
                try:
                    audio_chunk, overflowed = stream.read(CHUNK_SIZE)
                    if overflowed:
                        continue

                    audio_np = audio_chunk.flatten()
                    prediction = self._model.predict(audio_np)

                    for word, score in prediction.items():
                        if score > self.sensitivity:
                            now = time.time()
                            if now - last_trigger_time < COOLDOWN:
                                break
                            last_trigger_time = now

                            try:
                                self.on_wake()
                            except Exception as e:
                                self._notify_error(f"on_wake callback failed: {e}")
                            break

                except Exception as e:
                    if not self._stop_flag.is_set():
                        self._notify_error(f"listen loop error: {e}")
                        time.sleep(0.5)

            stream.stop()
            stream.close()

        except Exception as e:
            self._notify_error(f"fatal error: {e}")
            self.listening = False


_global_detector: Optional[WakeWordDetector] = None


def enable_wake_word(
    on_wake: Callable[[], None],
    on_error: Optional[Callable[[str], None]] = None,
) -> bool:
    global _global_detector
    if _global_detector and _global_detector.listening:
        return True

    sensitivity = float(os.getenv("WAKE_WORD_SENSITIVITY", "0.5"))
    _global_detector = WakeWordDetector(
        on_wake=on_wake,
        on_error=on_error,
        sensitivity=sensitivity,
    )
    return _global_detector.start()


def disable_wake_word() -> None:
    global _global_detector
    if _global_detector:
        _global_detector.stop()
        _global_detector = None


def is_wake_word_enabled() -> bool:
    return _global_detector is not None and _global_detector.listening


def get_status() -> dict:
    if not is_available():
        return {
            "available": False,
            "reason": "openwakeword not installed",
            "install_cmd": "uv pip install openwakeword",
        }

    active_model = os.getenv("WAKE_WORD_MODEL", "").strip() or (
        _global_detector.wake_words[0] if _global_detector else "hey_jarvis"
    )

    return {
        "available": True,
        "listening": is_wake_word_enabled(),
        "sensitivity": float(os.getenv("WAKE_WORD_SENSITIVITY", "0.5")),
        "active_model": active_model,
        "wake_words": (
            _global_detector.wake_words if _global_detector
            else [active_model]
        ),
        "available_models": list_available_wake_words(),
        "custom_models_dir": str(get_custom_model_dir()),
    }
