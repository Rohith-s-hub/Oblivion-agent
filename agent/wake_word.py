"""
agent/wake_word.py - Background wake word detection

Continuously listens for "hey Jarvis" (or custom wake words).
When detected, triggers a callback that starts voice recording.

Uses OpenWakeWord:
  - Runs 100% locally (no cloud)
  - ~2% CPU while listening
  - Pre-trained models: hey_jarvis, alexa, hey_mycroft
  - Phase 2: train custom "hey Meera" model

Usage:
    detector = WakeWordDetector(
        on_wake=lambda: print("Wake!"),
    )
    detector.start()
    # ... runs in background ...
    detector.stop()
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

# Lazy imports so oblivion doesn't crash if openwakeword not installed
_ww_available: Optional[bool] = None


def is_available() -> bool:
    """Check if openwakeword is installed."""
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


def list_available_wake_words() -> list[str]:
    """Return list of pre-trained wake word models available."""
    if not is_available():
        return []
    try:
        import openwakeword
        paths = openwakeword.get_pretrained_model_paths()
        # Extract names: "hey_jarvis_v0.1.onnx" -> "hey_jarvis"
        names = []
        for p in paths:
            name = os.path.basename(p).replace(".onnx", "")
            # Strip version suffix (_v0.1)
            if "_v" in name:
                name = name.rsplit("_v", 1)[0]
            names.append(name)
        return names
    except Exception:
        return []


class WakeWordDetector:
    """
    Background thread that listens for wake words.
    Fires on_wake callback when detected.
    """

    # Default wake words to listen for
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
        self.wake_words = wake_words or self.DEFAULT_WAKE_WORDS
        self.sensitivity = sensitivity  # 0.0 (loose) to 1.0 (strict)
        self.listening = False
        self._thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._model = None
        self._loaded = False

    def _lazy_load(self) -> bool:
        """Load openwakeword model on first use."""
        if self._loaded:
            return True

        try:
            import openwakeword
            from openwakeword.model import Model

            # Find full paths for requested wake words
            all_paths = openwakeword.get_pretrained_model_paths()
            selected_paths = []
            for word in self.wake_words:
                match = next(
                    (p for p in all_paths if word in os.path.basename(p)),
                    None,
                )
                if match:
                    selected_paths.append(match)

            if not selected_paths:
                self._notify_error(
                    f"No matching wake word models. Available: {list_available_wake_words()}"
                )
                return False

            # Load model
            self._model = Model(wakeword_model_paths=selected_paths)
            self._loaded = True
            return True

        except Exception as e:
            self._notify_error(f"Failed to load wake word model: {e}")
            return False

    def _notify_error(self, msg: str) -> None:
        """Notify caller of an error."""
        if self.on_error:
            try:
                self.on_error(msg)
            except Exception:
                pass

    def start(self) -> bool:
        """Start listening in background thread."""
        if self.listening:
            return True

        if not is_available():
            self._notify_error(
                "openwakeword not installed. Run: uv pip install openwakeword"
            )
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
        """Stop the listener."""
        if not self.listening:
            return
        self._stop_flag.set()
        self.listening = False
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def _listen_loop(self) -> None:
        """Main listening loop - runs in background thread."""
        import sounddevice as sd
        import numpy as np

        SAMPLE_RATE = 16000
        CHUNK_SIZE = 1280  # 80ms chunks (openwakeword requirement)

        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=CHUNK_SIZE,
            )
            stream.start()

            # Debounce - prevent multiple triggers within 2 seconds
            last_trigger_time = 0.0
            COOLDOWN = 2.0

            while not self._stop_flag.is_set():
                try:
                    audio_chunk, overflowed = stream.read(CHUNK_SIZE)
                    if overflowed:
                        continue

                    audio_np = audio_chunk.flatten()
                    prediction = self._model.predict(audio_np)

                    # Check if any wake word triggered
                    for word, score in prediction.items():
                        if score > self.sensitivity:
                            now = time.time()
                            if now - last_trigger_time < COOLDOWN:
                                break  # still in cooldown
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


# ═══ GLOBAL SINGLETON API ═══════════════════════════════════════════════════

_global_detector: Optional[WakeWordDetector] = None


def enable_wake_word(
    on_wake: Callable[[], None],
    on_error: Optional[Callable[[str], None]] = None,
) -> bool:
    """Enable global wake word detection. Returns True if started."""
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
    """Disable global wake word detection."""
    global _global_detector
    if _global_detector:
        _global_detector.stop()
        _global_detector = None


def is_wake_word_enabled() -> bool:
    """True if wake word is currently listening."""
    return _global_detector is not None and _global_detector.listening


def get_status() -> dict:
    """Return status dict for /wake status command."""
    if not is_available():
        return {
            "available": False,
            "reason": "openwakeword not installed",
            "install_cmd": "uv pip install openwakeword",
        }

    return {
        "available": True,
        "listening": is_wake_word_enabled(),
        "sensitivity": float(os.getenv("WAKE_WORD_SENSITIVITY", "0.5")),
        "wake_words": (
            _global_detector.wake_words if _global_detector
            else WakeWordDetector.DEFAULT_WAKE_WORDS
        ),
        "available_models": list_available_wake_words(),
    }
