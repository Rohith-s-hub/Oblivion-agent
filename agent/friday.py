"""
agent/friday.py - M.E.E.R.A. Speech Synthesis & Smart Voice Persona Engine

Handles text-to-speech synthesis using:
  - Microsoft Edge Neural TTS (free, high quality, default)
  - ElevenLabs (optional, premium human-like voice)

Features:
  - Instant Speech Classifier (_smart_local_summary): <1ms local processing
  - Smart Categorized Reading:
      * Full text read for: Definitions, Explanations, Q&A, Chat dialogue
      * Conversational summaries for: Plans, Code blocks, File lists, Tables
  - Hands-free speech-done callback hook for auto-listening
  - Non-blocking async audio playback via ffplay
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from agent.paths import load_config_env

load_config_env()

# Process lock & player state
_proc_lock = threading.Lock()
_current_proc: Optional[subprocess.Popen] = None
_on_speech_done_callback: Optional[Callable[[str], None]] = None

# Voice persona mapping for Edge TTS
VOICE_PERSONAS = {
    "aria":     ("en-US-AriaNeural",     "Aria (US, warm professional)"),
    "jenny":    ("en-US-JennyNeural",    "Jenny (US, friendly conversational)"),
    "sonia":    ("en-GB-SoniaNeural",    "Sonia (UK, refined)"),
    "natasha":  ("en-AU-NatashaNeural",  "Natasha (AU, energetic)"),
    "emma":     ("en-US-EmmaNeural",     "Emma (US, storyteller)"),
    "michelle": ("en-US-MichelleNeural", "Michelle (US, mature)"),
    "guy":      ("en-US-GuyNeural",      "Guy (US, male)"),
    "ryan":     ("en-GB-RyanNeural",     "Ryan (UK, male)"),
}


# ── Configuration Helpers ───────────────────────────────────────────────────

def is_enabled() -> bool:
    """Return True if M.E.E.R.A. voice output is enabled."""
    return os.getenv("FRIDAY_ENABLED", "true").lower() == "true"


def get_provider() -> str:
    """Return configured provider: 'auto', 'edge', or 'elevenlabs'."""
    return os.getenv("FRIDAY_PROVIDER", "auto").lower()


def get_voice() -> str:
    """Return Edge TTS voice identifier."""
    persona = os.getenv("FRIDAY_VOICE", "aria").lower()
    if persona in VOICE_PERSONAS:
        return VOICE_PERSONAS[persona][0]
    return persona  # allow raw voice string e.g. "en-US-AriaNeural"


def get_voice_label() -> str:
    """Return human-readable voice description."""
    persona = os.getenv("FRIDAY_VOICE", "aria").lower()
    if persona in VOICE_PERSONAS:
        return VOICE_PERSONAS[persona][1]
    return persona


def get_name() -> str:
    """Return preferred user title (default 'boss')."""
    return os.getenv("FRIDAY_NAME", "boss")


def get_rate() -> str:
    """Return speech rate string (e.g. '+0%', '+20%')."""
    r = os.getenv("FRIDAY_RATE", "+0%").strip()
    return r if r.startswith(("+", "-")) else f"+{r}"


def get_volume() -> str:
    """Return volume adjustment string (e.g. '+0%')."""
    v = os.getenv("FRIDAY_VOLUME", "+0%").strip()
    return v if v.startswith(("+", "-")) else f"+{v}"


def set_on_speech_done_callback(cb: Optional[Callable[[str], None]]) -> None:
    """Set callback to fire when speech playback completes."""
    global _on_speech_done_callback
    _on_speech_done_callback = cb


# ── Audio Player Check ───────────────────────────────────────────────────────

def _ensure_player() -> bool:
    """Check if ffplay is available for audio playback."""
    return shutil.which("ffplay") is not None


# ── Synthesis Engine: ElevenLabs ─────────────────────────────────────────────

def _get_elevenlabs_client():
    try:
        from elevenlabs.client import ElevenLabs
        api_key = os.getenv("ELEVENLABS_API_KEY")
        if not api_key:
            return None
        return ElevenLabs(api_key=api_key)
    except ImportError:
        return None


def _synth_elevenlabs(text: str, output_path: str) -> bool:
    """Synthesize text to audio via ElevenLabs API."""
    client = _get_elevenlabs_client()
    if not client:
        return False
    try:
        voice_id = os.getenv("FRIDAY_ELEVENLABS_VOICE", "rachel")
        audio_stream = client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id="eleven_turbo_v2_5",
            output_format="mp3_44100_128",
        )
        with open(output_path, "wb") as f:
            for chunk in audio_stream:
                if chunk:
                    f.write(chunk)
        return True
    except Exception as e:
        print(f"MEERA: ElevenLabs synthesis failed ({e}), falling back to Edge TTS")
        return False


# ── Synthesis Engine: Edge TTS ───────────────────────────────────────────────

async def _synth_edge_async(text: str, output_path: str):
    import edge_tts
    voice = get_voice()
    rate = get_rate()
    volume = get_volume()
    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
    await communicate.save(output_path)


def _synth_edge(text: str, output_path: str) -> bool:
    """Synthesize text to audio via Microsoft Edge Neural TTS."""
    try:
        asyncio.run(_synth_edge_async(text, output_path))
        return True
    except Exception as e:
        print(f"MEERA: Edge TTS error: {e}")
        return False


# ── Text Cleaning & Normalization ────────────────────────────────────────────

def clean_for_speech(text: str) -> str:
    """Clean raw text for natural TTS output."""
    if not text:
        return ""
    # Remove code blocks
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Remove inline code ticks
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove URLs
    text = re.sub(r"https?://\S+", "", text)
    # Remove markdown headers
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    # Remove list bullets
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    # Remove emojis & non-standard symbols
    text = re.sub(r"[^\w\s.,!?'\"\-]", "", text)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── Smart Speech Classifier (Fast Local Summary) ─────────────────────────────

def _smart_local_summary(text: str, name: str) -> str:
    """
    Intelligent Speech Classifier (<1ms local execution):
    - Reads FULL text for: Definitions, Explanations, Conversational Dialogue, Q&A.
    - SUMMARIZES for: Plans, Code Blocks, File Lists, Tables, Command Results.
    """
    raw = text.strip()

    # ── CATEGORY 1: Structured / Procedural Data (MUST SUMMARIZE) ──

    # Plans & Proposals
    if "PLAN:" in raw or "Approve this plan?" in raw:
        return f"I've mapped out the project plan on your screen, {name}. Take a look."

    # File lists or creation summaries
    if re.search(r"(?:✓ Created:|Written \d+ chars|Files created:)", raw, re.IGNORECASE):
        return f"The requested files have been created and are ready on your screen, {name}."

    # Code-heavy responses (has ``` blocks)
    if "```" in raw:
        before = raw.split("```")[0].strip()
        before = re.sub(r"[*#`\[\]()]", "", before).strip()
        if 15 <= len(before) <= 120:
            return f"{before}. The code is on your screen, {name}."
        return f"I've generated the code on your screen, {name}."

    # Multi-line lists / directory outputs
    lines = [l.strip() for l in raw.split("\n") if l.strip()]
    if len(lines) >= 5 and sum(len(l) for l in lines) / len(lines) < 60:
        return f"I've listed the items on your screen, {name}."

    # ── CATEGORY 2: Explanations, Definitions & Chat (READ IN FULL) ──

    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", raw)
    clean = re.sub(r"`([^`]+)`", r"\1", clean)
    clean = re.sub(r"^#+ ", "", clean, flags=re.MULTILINE)
    clean = re.sub(r"^\s*[-*+]\s+", "", clean, flags=re.MULTILINE)
    clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
    clean = re.sub(r"\n{2,}", " ", clean).strip()

    # Read full explanation up to 3 sentences or 400 characters
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    if len(sentences) <= 3 and len(clean) <= 400:
        return clean

    # For longer explanations, read the first 2-3 key sentences
    return " ".join(sentences[:3])[:380] + f", {name}."


def summarize_for_speech(text: str, llm_client=None) -> str:
    """Convert technical agent output into a natural spoken summary (<1ms)."""
    if not text or not text.strip():
        return ""

    name = get_name()
    raw = text.strip()

    # Short clean text -> speak as-is
    if len(raw) < 100 and "```" not in raw and "\n\n" not in raw:
        return raw

    use_llm = os.getenv("FRIDAY_USE_LLM_REWRITE", "false").lower() == "true"
    if not use_llm or llm_client is None:
        return _smart_local_summary(raw, name)

    # Optional slow LLM rewrite path if explicitly enabled
    try:
        prompt = (
            f"You are Meera, a virtual AI assistant. Summarize this technical response "
            f"in ONE natural sentence for {name}. Do not read code blocks or lists.\n\n"
            f"TEXT:\n{raw[:1000]}"
        )
        response = llm_client.chat(
            messages=[{"role": "user", "content": prompt}],
            stream=False,
        )
        return response.strip().strip('"').strip("'")
    except Exception:
        return _smart_local_summary(raw, name)


# ── Main Unified speak() Function ───────────────────────────────────────────

def speak(text: str, blocking: bool = False, auto_summarize: bool = True) -> Optional[threading.Thread]:
    """
    Speak text out loud — auto-picks best provider (Edge TTS or ElevenLabs).
    Runs non-blocking in a background daemon thread unless blocking=True.
    """
    if not text or not text.strip():
        return None
    if not is_enabled():
        return None

    # Pre-summarize text if requested
    final_text = summarize_for_speech(text) if auto_summarize else clean_for_speech(text)
    if not final_text or not final_text.strip():
        return None

    def _do_speak():
        global _current_proc
        stop_speaking()  # Kill any currently playing audio so voices never overlap
        if not _ensure_player():
            print("MEERA: ffplay not found. Install: sudo apt install ffmpeg")
            return

        tmp_path = None
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.close()
            tmp_path = tmp.name

            # Synthesize audio
            provider = get_provider()
            success = False

            if provider == "elevenlabs":
                success = _synth_elevenlabs(final_text, tmp_path)
                if not success:
                    success = _synth_edge(final_text, tmp_path)
            else:
                success = _synth_edge(final_text, tmp_path)

            if not success:
                return

            # Play audio via ffplay
            with _proc_lock:
                _current_proc = subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", tmp_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            try:
                _current_proc.wait()
            finally:
                with _proc_lock:
                    _current_proc = None

                # Trigger speech-completion callback (e.g. auto-mic for questions)
                if _on_speech_done_callback:
                    try:
                        _on_speech_done_callback(final_text)
                    except Exception:
                        pass

        except Exception as e:
            print(f"MEERA speak error: {e}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    if blocking:
        _do_speak()
        return None

    t = threading.Thread(target=_do_speak, name="meera-speech", daemon=True)
    t.start()
    return t


def stop_speaking():
    """Immediately terminate any currently playing TTS speech."""
    global _current_proc
    with _proc_lock:
        if _current_proc is not None:
            try:
                _current_proc.terminate()
            except Exception:
                pass
            _current_proc = None


def get_elevenlabs_quota() -> Optional[dict]:
    """Fetch ElevenLabs quota information if API key is present."""
    client = _get_elevenlabs_client()
    if not client:
        return None
    try:
        user = client.user.get()
        subscription = user.subscription
        return {
            "character_count": subscription.character_count,
            "character_limit": subscription.character_limit,
            "remaining": subscription.character_limit - subscription.character_count,
            "status": subscription.status,
        }
    except Exception:
        return None
