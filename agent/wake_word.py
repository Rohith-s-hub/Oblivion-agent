
"""
agent/wake_word.py — lightweight "Hey Meera" wake (openwakeword only)

UI says Hey Meera. Detector uses hey_jarvis ONNX (pretrained, reliable)
unless ~/.oblivion/models/hey_meera.onnx exists.

NO continuous Whisper in the wake loop (that froze the TUI).
Whisper stays only in agent/voice.py for Ctrl+T transcription.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

_ww_available: Optional[bool] = None
_global_detector: Optional["WakeWordDetector"] = None


def is_available() -> bool:
    global _ww_available
    if _ww_available is not None:
        return _ww_available
    try:
        import openwakeword  # noqa: F401
        import sounddevice  # noqa: F401
        import numpy  # noqa: F401
        _ww_available = True
    except ImportError:
        _ww_available = False
    return _ww_available


def get_custom_model_dir() -> Path:
    d = Path.home() / ".oblivion" / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_custom_models() -> dict:
    models = {}
    for d in (get_custom_model_dir(), Path(__file__).resolve().parent.parent / "assets"):
        if d.is_dir():
            for p in d.glob("*.onnx"):
                name = p.stem.lower().replace("_v0.1", "").replace("_v1", "")
                models[name] = p
    return models


def list_available_wake_words() -> list:
    names = {"hey_meera", "hey_jarvis", "alexa", "hey_mycroft"}
    names.update(find_custom_models().keys())
    try:
        import openwakeword
        for p in openwakeword.get_pretrained_model_paths():
            n = os.path.basename(p).replace(".onnx", "")
            if "_v" in n:
                n = n.rsplit("_v", 1)[0]
            names.add(n)
    except Exception:
        pass
    return sorted(names)


class WakeWordDetector:
    def __init__(
        self,
        on_wake: Callable[[], None],
        on_error: Optional[Callable[[str], None]] = None,
        wake_words: Optional[list] = None,
        sensitivity: float = 0.5,
    ):
        self.on_wake = on_wake
        self.on_error = on_error
        # Display name
        selected = (os.getenv("WAKE_WORD_MODEL") or "hey_meera").strip().lower()
        self.wake_words = wake_words or [selected]
        self.sensitivity = float(
            os.getenv("WAKE_WORD_SENSITIVITY", str(sensitivity)) or sensitivity
        )
        self.listening = False
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._model = None
        self._stream = None

    def _err(self, msg: str) -> None:
        if self.on_error:
            try:
                self.on_error(msg)
            except Exception:
                pass

    def _load(self) -> bool:
        try:
            import openwakeword
            from openwakeword.model import Model

            pre = list(openwakeword.get_pretrained_model_paths())
            custom = find_custom_models()
            paths = []

            # Real custom hey_meera.onnx if user trained one
            for k in ("hey_meera", "meera"):
                if k in custom:
                    paths.append(str(custom[k]))

            # Reliable pretrained: hey_jarvis (what worked before)
            jarvis = next((p for p in pre if "hey_jarvis" in os.path.basename(p).lower()), None)
            if jarvis:
                paths.append(jarvis)
            elif pre:
                paths.append(pre[0])

            if not paths:
                self._err("No openwakeword models found")
                return False

            # Dedupe
            seen, uniq = set(), []
            for p in paths:
                if p not in seen:
                    seen.add(p)
                    uniq.append(p)

            # IMPORTANT: no inference_framework kw (breaks some versions)
            self._model = Model(wakeword_model_paths=uniq)
            return True
        except Exception as e:
            self._err(f"wake load failed: {e}")
            return False

    def start(self) -> bool:
        if self.listening:
            return True
        if not is_available():
            self._err("openwakeword/sounddevice not installed")
            return False
        if not self._load():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="wake-oww", daemon=True)
        self.listening = True
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        self.listening = False
        thr = self._thread
        self._thread = None
        if thr and thr.is_alive():
            thr.join(timeout=2.0)
        # Force-close PortAudio
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        self._model = None
        self._stream = None

    def _loop(self) -> None:
        import sounddevice as sd
        import numpy as np

        SR, CHUNK = 16000, 1280  # 80ms — what OWW expects
        last_fire = 0.0
        cooldown = 2.0
        thr = self.sensitivity

        try:
            stream = sd.InputStream(
                samplerate=SR,
                channels=1,
                dtype="int16",
                blocksize=CHUNK,
            )
            self._stream = stream
            stream.start()

            while not self._stop.is_set():
                try:
                    data, overflowed = stream.read(CHUNK)
                    if overflowed or self._model is None:
                        continue
                    pcm = np.asarray(data).reshape(-1)
                    pred = self._model.predict(pcm)
                    if not pred:
                        continue
                    best_w, best_s = max(pred.items(), key=lambda x: x[1])
                    if best_s >= thr:
                        now = time.time()
                        if now - last_fire >= cooldown:
                            last_fire = now
                            try:
                                self.on_wake()
                            except Exception as e:
                                self._err(f"on_wake: {e}")
                except Exception as e:
                    if not self._stop.is_set():
                        self._err(f"wake loop: {e}")
                        time.sleep(0.3)

            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        except Exception as e:
            self._err(f"wake fatal: {e}")
        finally:
            self.listening = False
            self._stream = None
            try:
                import sounddevice as sd
                sd.stop()
            except Exception:
                pass


def enable_wake_word(
    on_wake: Callable[[], None],
    on_error: Optional[Callable[[str], None]] = None,
) -> bool:
    global _global_detector
    if _global_detector and _global_detector.listening:
        return True
    # Ensure previous instance fully dead
    disable_wake_word()
    sens = float(os.getenv("WAKE_WORD_SENSITIVITY", "0.5"))
    _global_detector = WakeWordDetector(on_wake=on_wake, on_error=on_error, sensitivity=sens)
    return _global_detector.start()


def disable_wake_word() -> None:
    global _global_detector
    det = _global_detector
    _global_detector = None
    if det is not None:
        try:
            det.stop()
        except Exception:
            pass
    try:
        import sounddevice as sd
        sd.stop()
    except Exception:
        pass


def is_wake_word_enabled() -> bool:
    return _global_detector is not None and bool(getattr(_global_detector, "listening", False))


def get_status() -> dict:
    if not is_available():
        return {
            "available": False,
            "reason": "openwakeword not installed",
            "install_cmd": "uv pip install openwakeword",
        }
    active = (os.getenv("WAKE_WORD_MODEL") or "hey_meera").strip()
    return {
        "available": True,
        "listening": is_wake_word_enabled(),
        "sensitivity": float(os.getenv("WAKE_WORD_SENSITIVITY", "0.5")),
        "active_model": active,
        "engine": "openwakeword",
        "wake_words": (_global_detector.wake_words if _global_detector else [active]),
        "available_models": list_available_wake_words(),
        "custom_models_dir": str(get_custom_model_dir()),
        "hint": "Say 'Hey Jarvis' (ONNX). UI label: Hey Meera. Drop hey_meera.onnx for true Meera.",
        "oww": True,
        "whisper": False,
    }
