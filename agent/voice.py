
"""
Voice input for Oblivion.
Simple blocking recorder + Whisper STT (no callback stream = no fds_to_keep).
"""
import os
import time
import threading
from pathlib import Path
from typing import Optional, Callable

try:
    import numpy as np
    import sounddevice as sd
    from faster_whisper import WhisperModel
    VOICE_AVAILABLE = True
    _VOICE_IMPORT_ERROR = None
except ImportError as _e:
    VOICE_AVAILABLE = False
    _VOICE_IMPORT_ERROR = str(_e)
    np = None  # type: ignore
    sd = None  # type: ignore
    WhisperModel = None  # type: ignore

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
MAX_RECORD_SECONDS = int(os.getenv("VOICE_MAX_RECORD", "8"))
SILENCE_THRESHOLD = int(os.getenv("VOICE_SILENCE_THRESHOLD", "500"))
SILENCE_DURATION = float(os.getenv("VOICE_SILENCE_DURATION", "0.7"))
MIN_RECORD_SECONDS = float(os.getenv("VOICE_MIN_RECORD", "0.35"))

from agent.paths import whisper_dir
MODEL_DIR = whisper_dir()

_whisper_model = None
_mic_lock = threading.Lock()


def get_whisper_model(model_size: str = None):
    if not VOICE_AVAILABLE:
        raise RuntimeError(
            "Voice support not installed. Install with:\n"
            '  pip install "oblivion-agent[voice]"\n'
            f"(missing: {_VOICE_IMPORT_ERROR})"
        )
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    size = model_size or os.getenv("VOICE_MODEL", "tiny.en")
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        device = "cpu"
    compute_type = "int8" if device == "cpu" else "float16"

    import contextlib
    with open(os.devnull, "w") as devnull, contextlib.redirect_stderr(devnull):
        _whisper_model = WhisperModel(
            size,
            device=device,
            compute_type=compute_type,
            download_root=str(MODEL_DIR),
        )
    return _whisper_model


def clear_model():
    global _whisper_model
    _whisper_model = None


def list_input_devices() -> list:
    if not VOICE_AVAILABLE:
        return []
    devices = sd.query_devices()
    out = []
    default_idx = -1
    try:
        default_idx = sd.default.device[0]
    except Exception:
        pass
    for i, d in enumerate(devices):
        if d.get("max_input_channels", 0) > 0:
            out.append({
                "index": i,
                "name": d.get("name", ""),
                "default": i == default_idx,
            })
    return out


def get_default_input_device() -> int:
    try:
        return int(sd.default.device[0])
    except Exception:
        return 0


def _release_portaudio():
    if not VOICE_AVAILABLE:
        return
    try:
        sd.stop()
    except Exception:
        pass
    time.sleep(0.2)


class VoiceRecorder:
    """Blocking chunk recorder — avoids PortAudio callback FD issues."""

    def __init__(
        self,
        on_level: Optional[Callable[[float], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        device: Optional[int] = None,
    ):
        self.on_level = on_level or (lambda r: None)
        self.on_status = on_status or (lambda s: None)
        self.device = device if device is not None else get_default_input_device()
        self._stop_flag = threading.Event()
        self._audio_buffer = []

    def stop(self):
        self._stop_flag.set()

    def record(self):
        if not VOICE_AVAILABLE:
            raise RuntimeError("Voice not installed")

        self._stop_flag.clear()
        self._audio_buffer = []
        self.on_status("recording")

        chunk_s = 0.1
        chunk_frames = int(SAMPLE_RATE * chunk_s)
        max_chunks = int(MAX_RECORD_SECONDS / chunk_s)
        min_chunks = int(MIN_RECORD_SECONDS / chunk_s)
        silence_needed = max(1, int(SILENCE_DURATION / chunk_s))

        got_lock = _mic_lock.acquire(timeout=3.0)
        if not got_lock:
            self.on_status("error: mic lock timeout")
            return np.array([], dtype=np.int16)

        try:
            _release_portaudio()
            silence_run = 0
            has_spoken = False
            noise_floor = 200.0

            for i in range(max_chunks):
                if self._stop_flag.is_set():
                    break
                try:
                    block = sd.rec(
                        chunk_frames,
                        samplerate=SAMPLE_RATE,
                        channels=CHANNELS,
                        dtype=DTYPE,
                        device=self.device,
                        blocking=True,
                    )
                except Exception:
                    _release_portaudio()
                    time.sleep(0.35)
                    try:
                        block = sd.rec(
                            chunk_frames,
                            samplerate=SAMPLE_RATE,
                            channels=CHANNELS,
                            dtype=DTYPE,
                            device=self.device,
                            blocking=True,
                        )
                    except Exception as e2:
                        self.on_status(f"error: {e2}")
                        return np.array([], dtype=np.int16)

                chunk = np.asarray(block).reshape(-1).astype(np.int16)
                self._audio_buffer.append(chunk)

                rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2))) + 1e-6
                self.on_level(rms)

                if i < 3:
                    noise_floor = min(noise_floor, rms)
                gate = max(SILENCE_THRESHOLD, noise_floor * 2.0)

                if rms > gate:
                    has_spoken = True
                    silence_run = 0
                else:
                    silence_run += 1

                if i >= min_chunks and has_spoken and silence_run >= silence_needed:
                    break

            self.on_status("stopped")
            if not self._audio_buffer:
                return np.array([], dtype=np.int16)
            return np.concatenate(self._audio_buffer)
        finally:
            try:
                sd.stop()
            except Exception:
                pass
            _mic_lock.release()

    def record_until_stopped(self):
        return self.record()


def transcribe(audio, language: str = "en") -> str:
    if not VOICE_AVAILABLE:
        return ""
    if audio is None or len(audio) == 0:
        return ""

    audio_float = audio.astype(np.float32) / 32768.0
    model = get_whisper_model()
    initial_prompt = "Meera, Oblivion, Rohit. Python, JavaScript, file, folder, code."

    segments, info = model.transcribe(
        audio_float,
        beam_size=int(os.getenv("VOICE_BEAM_SIZE", "1")),
        best_of=1,
        language=language or "en",
        initial_prompt=initial_prompt,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=250),
        condition_on_previous_text=False,
        without_timestamps=True,
    )
    return " ".join(seg.text.strip() for seg in segments).strip()


def record_and_transcribe(
    on_level=None,
    on_status=None,
    device=None,
    language: str = "en",
    push_to_talk: bool = False,
) -> str:
    recorder = VoiceRecorder(on_level=on_level, on_status=on_status, device=device)
    audio = recorder.record()
    if on_status:
        on_status("transcribing")
    text = transcribe(audio, language=language)
    if on_status:
        on_status("done")
    return text
