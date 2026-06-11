"""
Voice input for Oblivion.
Records mic audio with VAD and transcribes via Whisper.
"""
import os
import io
import time
import threading
import wave
from pathlib import Path
from typing import Optional, Callable

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
MAX_RECORD_SECONDS = 60
SILENCE_THRESHOLD = 1200  # higher = tolerates more background noise
SILENCE_DURATION = 1.2  # stop quicker once you stop talking
MIN_RECORD_SECONDS = 0.8

MODEL_DIR = Path.home() / ".ai-agent" / "whisper"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

_whisper_model: Optional[WhisperModel] = None  # cleared via clear_model()


def get_whisper_model(model_size: str = None) -> WhisperModel:
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    size = model_size or os.getenv("VOICE_MODEL", "medium")

    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        device = "cpu"

    compute_type = "int8" if device == "cpu" else "float16"

    print(f"Loading Whisper '{size}' on {device} (one-time download if first run)...")
    _whisper_model = WhisperModel(
        size,
        device=device,
        compute_type=compute_type,
        download_root=str(MODEL_DIR),
    )
    print(f"OK: Whisper '{size}' loaded ({device}/{compute_type})")
    return _whisper_model


def clear_model():
    """Force reload of Whisper model (after changing size)."""
    global _whisper_model
    _whisper_model = None


def list_input_devices() -> list[dict]:
    devices = sd.query_devices()
    inputs = []
    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0:
            inputs.append({
                "index": i,
                "name": d["name"],
                "channels": d["max_input_channels"],
                "default": i == sd.default.device[0] if sd.default.device else False,
            })
    return inputs


def get_default_input_device() -> int:
    try:
        return sd.default.device[0]
    except Exception:
        return 0


class VoiceRecorder:
    def __init__(
        self,
        on_level: Optional[Callable[[float], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        device: Optional[int] = None,
    ):
        self.on_level = on_level or (lambda l: None)
        self.on_status = on_status or (lambda s: None)
        self.device = device if device is not None else get_default_input_device()
        self._stop_flag = threading.Event()
        self._audio_buffer: list = []
        self._silence_start: Optional[float] = None
        self._record_start: Optional[float] = None

    def stop(self):
        self._stop_flag.set()

    def record(self) -> np.ndarray:
        self._stop_flag.clear()
        self._audio_buffer.clear()
        self._silence_start = None
        self._record_start = time.time()
        self.on_status("recording")

        def callback(indata, frames, time_info, status):
            chunk = indata.copy().flatten()
            self._audio_buffer.append(chunk)

            rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
            self.on_level(rms)

            elapsed = time.time() - self._record_start

            if elapsed >= MIN_RECORD_SECONDS:
                if rms < SILENCE_THRESHOLD:
                    if self._silence_start is None:
                        self._silence_start = time.time()
                    elif time.time() - self._silence_start >= SILENCE_DURATION:
                        self._stop_flag.set()
                        raise sd.CallbackStop()
                else:
                    self._silence_start = None

            if elapsed >= MAX_RECORD_SECONDS:
                self._stop_flag.set()
                raise sd.CallbackStop()

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                callback=callback,
                device=self.device,
                blocksize=int(SAMPLE_RATE * 0.05),
            ):
                while not self._stop_flag.is_set():
                    if time.time() - self._record_start >= MAX_RECORD_SECONDS:
                        break
                    time.sleep(0.05)
        except Exception as e:
            self.on_status(f"error: {e}")
            return np.array([], dtype=np.int16)

        self.on_status("stopped")

        if not self._audio_buffer:
            return np.array([], dtype=np.int16)

        return np.concatenate(self._audio_buffer)

    def record_until_stopped(self) -> np.ndarray:
        """
        Press-to-talk mode: records continuously until .stop() is called.
        Does NOT use silence detection - good for noisy rooms.
        """
        self._stop_flag.clear()
        self._audio_buffer.clear()
        self._record_start = time.time()
        self.on_status("recording")

        def callback(indata, frames, time_info, status):
            chunk = indata.copy().flatten()
            self._audio_buffer.append(chunk)
            rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
            self.on_level(rms)
            # Hard cap at MAX_RECORD_SECONDS
            if time.time() - self._record_start >= MAX_RECORD_SECONDS:
                self._stop_flag.set()
                raise sd.CallbackStop()

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                callback=callback,
                device=self.device,
                blocksize=int(SAMPLE_RATE * 0.05),
            ):
                while not self._stop_flag.is_set():
                    time.sleep(0.05)
        except Exception as e:
            self.on_status(f"error: {e}")
            return np.array([], dtype=np.int16)

        self.on_status("stopped")
        if not self._audio_buffer:
            return np.array([], dtype=np.int16)
        return np.concatenate(self._audio_buffer)


def transcribe(audio: np.ndarray, language: str = "en") -> str:
    """
    Transcribe audio via Whisper.
    Uses an initial prompt to bias toward coding terms and common Indian names.
    """
    if len(audio) == 0:
        return ""

    audio_float = audio.astype(np.float32) / 32768.0
    model = get_whisper_model()

    # Initial prompt biases Whisper toward expected vocabulary
    # This dramatically improves accuracy for names, technical terms, and accents
    initial_prompt = (
        "User is a software developer named Rohit from Sivakasi, India. "
        "They use coding terms: Python, JavaScript, Frappe, doctype, agent, "
        "Oblivion, ReAct, LLM, function, class, file, folder, directory, "
        "create, edit, delete, read, search, refactor, run, list."
    )

    segments, info = model.transcribe(
        audio_float,
        language=language,
        beam_size=5,
        best_of=5,
        temperature=0.0,                  # deterministic
        condition_on_previous_text=False, # don't hallucinate continuations
        initial_prompt=initial_prompt,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=400,
            speech_pad_ms=200,
        ),
        no_speech_threshold=0.6,          # higher = stricter (less hallucination)
    )

    text = " ".join(seg.text.strip() for seg in segments).strip()
    return text


def record_and_transcribe(
    on_level: Optional[Callable[[float], None]] = None,
    on_status: Optional[Callable[[str], None]] = None,
    device: Optional[int] = None,
    language: str = "en",
    push_to_talk: bool = False,
    stop_event: Optional[threading.Event] = None,
) -> str:
    """
    Record and transcribe in one call.

    push_to_talk=False  -> Auto-stop on silence (good for quiet rooms)
    push_to_talk=True   -> Records until stop_event is set (good for noisy rooms)
    """
    recorder = VoiceRecorder(on_level=on_level, on_status=on_status, device=device)

    if push_to_talk:
        # External stop control
        def watch_stop():
            if stop_event is not None:
                stop_event.wait()
                recorder.stop()
        if stop_event is not None:
            threading.Thread(target=watch_stop, daemon=True).start()
        audio = recorder.record_until_stopped()
    else:
        audio = recorder.record()

    if on_status:
        on_status("transcribing")
    text = transcribe(audio, language=language)
    if on_status:
        on_status("done")
    return text


if __name__ == "__main__":
    import sys
    print("Available input devices:")
    for d in list_input_devices():
        marker = " *" if d["default"] else "  "
        print(f"{marker} [{d['index']}] {d['name']} ({d['channels']} ch)")

    print("\nLoading Whisper model...")
    get_whisper_model()

    print("\n" + "=" * 60)
    print("PRESS-TO-TALK MODE (good for noisy rooms)")
    print("=" * 60)
    print("1. Press Enter to START recording")
    print("2. Speak your message")
    print("3. Press Enter again to STOP")
    print("=" * 60)
    input("\nReady? Press Enter to start...")

    print("\n[REC] Recording... press Enter to STOP")

    def show_level(rms):
        bars = int(min(rms / 1500, 20))
        print(f"\r  [{'#' * bars}{' ' * (20 - bars)}] {rms:6.0f}    ", end="", flush=True)

    stop_event = threading.Event()

    def wait_for_enter():
        input()
        stop_event.set()

    threading.Thread(target=wait_for_enter, daemon=True).start()

    text = record_and_transcribe(
        on_level=show_level,
        on_status=lambda s: print(f"\n=> {s}"),
        push_to_talk=True,
        stop_event=stop_event,
    )
    print(f"\nTranscription: {text!r}")
