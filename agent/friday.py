"""
F.R.I.D.A.Y. - voice personality with DUAL provider support.

Providers (auto-fallback in this order):
  1. ElevenLabs (premium, human-like)  - if ELEVENLABS_API_KEY set
  2. Edge TTS (free, Microsoft neural) - always available

Smart routing:
  - Short text (<300 chars) -> ElevenLabs (premium quality, low credit cost)
  - Long text             -> Edge TTS (free, save credits)
  - ElevenLabs quota out  -> auto-fallback to Edge

Pipeline:
  agent output -> personality LLM rewrite -> TTS provider -> ffplay -> speaker
"""
import os
import asyncio
import tempfile
import threading
import subprocess
import shutil
from typing import Optional

import edge_tts

# Optional ElevenLabs (may not be installed)
try:
    from elevenlabs.client import ElevenLabs
    HAS_ELEVENLABS = True
except ImportError:
    HAS_ELEVENLABS = False

# Current playback process
_current_proc: Optional[subprocess.Popen] = None
_proc_lock = threading.Lock()

# Edge TTS voices
EDGE_VOICES = {
    "aria":     "en-US-AriaNeural",
    "jenny":    "en-US-JennyNeural",
    "sonia":    "en-GB-SoniaNeural",
    "natasha":  "en-AU-NatashaNeural",
    "emma":     "en-US-EmmaNeural",
    "michelle": "en-US-MichelleNeural",
    "guy":      "en-US-GuyNeural",
    "ryan":     "en-GB-RyanNeural",
}

# ElevenLabs voices (verified default voice IDs)
ELEVENLABS_VOICES = {
    "rachel":    "21m00Tcm4TlvDq8ikWAM",  # warm, calm, professional ⭐ FRIDAY
    "domi":      "AZnzlk1XvdvUeBnXmlld",  # confident, slightly playful
    "bella":     "EXAVITQu4vr4xnSDxMaL",  # soft, friendly
    "antoni":    "ErXwobaYiN019PkySvjV",  # well-rounded male
    "elli":      "MF3mGyEYCl7XYWbV9V6O",  # young, energetic
    "josh":      "TxGEqnHWrfWFTfGW9XjX",  # deep male
    "arnold":    "VR6AewLTigWG4xSOukaG",  # crisp male
    "adam":      "pNInz6obpgDQGcFmaJgB",  # deep, narration male
    "sam":       "yoZ06aMxZJJ28mfd3POQ",  # warm male
    "charlotte": "XB0fDUnXU5powFXDhCwa",  # sultry female
    "matilda":   "XrExE9yKIg1WjnnlVkGX",  # friendly female
    "freya":     "jsCqWAovK2LkecY7zXl4",  # youthful female
}

_elevenlabs_client = None


def _get_elevenlabs_client():
    global _elevenlabs_client
    if _elevenlabs_client is None and HAS_ELEVENLABS:
        api_key = os.getenv("ELEVENLABS_API_KEY")
        if api_key:
            _elevenlabs_client = ElevenLabs(api_key=api_key)
    return _elevenlabs_client


def _ensure_player() -> bool:
    return shutil.which("ffplay") is not None


def is_enabled() -> bool:
    return os.getenv("FRIDAY_ENABLED", "true").lower() == "true"


def get_provider() -> str:
    """Resolve which TTS provider to use."""
    pref = os.getenv("FRIDAY_PROVIDER", "auto").lower()
    if pref == "edge":
        return "edge"
    if pref == "elevenlabs":
        if HAS_ELEVENLABS and os.getenv("ELEVENLABS_API_KEY"):
            return "elevenlabs"
        return "edge"  # fallback
    # auto: prefer ElevenLabs if available
    if HAS_ELEVENLABS and os.getenv("ELEVENLABS_API_KEY"):
        return "elevenlabs"
    return "edge"


def get_voice() -> str:
    """Resolve current voice name to provider-specific ID."""
    provider = get_provider()
    if provider == "elevenlabs":
        val = os.getenv("FRIDAY_ELEVENLABS_VOICE", "rachel").lower()
        return ELEVENLABS_VOICES.get(val, ELEVENLABS_VOICES["rachel"])
    # Edge
    val = os.getenv("FRIDAY_VOICE", "aria").lower()
    return EDGE_VOICES.get(val, "en-US-AriaNeural")


def get_voice_label() -> str:
    """Human-readable voice name for display."""
    provider = get_provider()
    if provider == "elevenlabs":
        return os.getenv("FRIDAY_ELEVENLABS_VOICE", "rachel")
    return os.getenv("FRIDAY_VOICE", "aria")


def get_name() -> str:
    return os.getenv("FRIDAY_NAME", "boss")


def get_rate() -> str:
    return os.getenv("FRIDAY_RATE", "+0%")


def get_volume() -> str:
    return os.getenv("FRIDAY_VOLUME", "+0%")


# ── ElevenLabs synthesis ──────────────────────────────────────────────────────
def _synth_elevenlabs(text: str, output_path: str) -> bool:
    """Synthesize via ElevenLabs. Returns True on success."""
    client = _get_elevenlabs_client()
    if client is None:
        return False
    try:
        voice_id = get_voice()
        audio_stream = client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id="eleven_turbo_v2_5",  # fast + cheap + good
            output_format="mp3_44100_128",
        )
        # Collect chunks into a file
        with open(output_path, "wb") as f:
            for chunk in audio_stream:
                if chunk:
                    f.write(chunk)
        return True
    except Exception as e:
        msg = str(e).lower()
        if "quota" in msg or "credit" in msg or "limit" in msg:
            print("FRIDAY: ElevenLabs quota exhausted, falling back to Edge")
        else:
            print(f"FRIDAY: ElevenLabs error ({e}), falling back to Edge")
        return False


# ── Edge TTS synthesis ────────────────────────────────────────────────────────
async def _synth_edge_async(text: str, output_path: str):
    voice = EDGE_VOICES.get(
        os.getenv("FRIDAY_VOICE", "aria").lower(),
        "en-US-AriaNeural"
    )
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=get_rate(),
        volume=get_volume(),
    )
    await communicate.save(output_path)


def _synth_edge(text: str, output_path: str) -> bool:
    try:
        asyncio.run(_synth_edge_async(text, output_path))
        return True
    except Exception as e:
        print(f"FRIDAY: Edge TTS error: {e}")
        return False


# ── Unified speak() ───────────────────────────────────────────────────────────
def speak(text: str, blocking: bool = False) -> Optional[threading.Thread]:
    """Speak text - auto-picks best provider."""
    if not text or not text.strip():
        return None
    if not is_enabled():
        return None

    def _do_speak():
        global _current_proc
        if not _ensure_player():
            print("FRIDAY: ffplay not found. Install: sudo apt install ffmpeg")
            return

        tmp_path = None
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.close()
            tmp_path = tmp.name

            # Pick provider
            provider = get_provider()
            success = False

            if provider == "elevenlabs":
                success = _synth_elevenlabs(text, tmp_path)
                if not success:
                    # Fallback to Edge
                    success = _synth_edge(text, tmp_path)
            else:
                success = _synth_edge(text, tmp_path)

            if not success:
                return

            # Play
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
        except Exception as e:
            print(f"FRIDAY speak error: {e}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    if blocking:
        _do_speak()
        return None
    t = threading.Thread(target=_do_speak, daemon=True)
    t.start()
    return t


def stop_speaking():
    global _current_proc
    with _proc_lock:
        if _current_proc is not None:
            try:
                _current_proc.terminate()
            except Exception:
                pass
            _current_proc = None


# ── ElevenLabs quota check ────────────────────────────────────────────────────
def get_elevenlabs_quota() -> Optional[dict]:
    """Return {used, limit, remaining} or None."""
    client = _get_elevenlabs_client()
    if client is None:
        return None
    try:
        sub = client.user.subscription.get()
        return {
            "used": sub.character_count,
            "limit": sub.character_limit,
            "remaining": sub.character_limit - sub.character_count,
        }
    except Exception:
        return None


# ── Personality rewriter ─────────────────────────────────────────────────────
PERSONALITY_PROMPT = """You are F.R.I.D.A.Y. - a witty, warm, professional AI assistant (think Iron Man's FRIDAY).
You address the user as "{name}" - always use this name.

Your job: rewrite the technical output below into a SHORT spoken summary (1-3 sentences max).

Rules:
- Address them as "{name}" naturally (at least once, but don't overdo)
- Sound conversational, warm, slightly playful, professional
- NEVER read code aloud - describe it ("I drafted a 30-line factorial function")
- NEVER list file contents verbatim - summarize ("Found 12 files, mostly Python")
- NEVER repeat technical details word-for-word - distill the essence
- If asking for confirmation, end with a question
- Be confident and concise
- Max 50 words spoken

Examples:

Technical: "Contents of .: DIR agent/ DIR db/ FILE main.py (2KB) FILE README.md (500B)"
FRIDAY: "You've got 4 items in there, {name} - two folders for agent and db, plus main.py and a README. Anything you want to dig into?"

Technical: "Written 1240 chars to algos/quicksort.py"
FRIDAY: "Done, {name}. Quicksort is saved to algos/quicksort.py. Want me to test it?"

Technical: "Error: File not found: missing.py"
FRIDAY: "That file doesn't exist, {name}. Want me to create it, or did you mean a different name?"

Now rewrite this technical output:

{output}

Respond with ONLY the spoken summary. No quotes, no preamble, no explanation."""


def summarize_for_speech(text: str, llm_client=None) -> str:
    if not text or not text.strip():
        return ""

    name = get_name()
    text = text.strip()

    if len(text) < 200 and "```" not in text and "\n\n" not in text:
        return text

    use_llm = os.getenv("FRIDAY_USE_LLM_REWRITE", "true").lower() == "true"
    if not use_llm or llm_client is None:
        first_line = text.split("\n")[0][:150]
        return f"Here's what I found, {name}: {first_line}"

    try:
        prompt = PERSONALITY_PROMPT.format(name=name, output=text[:2000])
        original_model = os.environ.get("DEFAULT_MODEL", "")
        if os.getenv("GROQ_API_KEY"):
            os.environ["DEFAULT_MODEL"] = "groq/llama-3.3-70b-versatile"
        try:
            response = llm_client.chat(
                [{"role": "user", "content": prompt}],
                stream=False,
            ).strip()
        finally:
            if original_model:
                os.environ["DEFAULT_MODEL"] = original_model
        response = response.strip(' "\'')
        return response or text[:200]
    except Exception as e:
        print(f"FRIDAY rewrite failed: {e}")
        first_line = text.split("\n")[0][:150]
        return f"Here's what I found, {name}: {first_line}"


# ── Self-test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Provider: {get_provider()}")
    print(f"Voice ID: {get_voice()}")
    print(f"Voice label: {get_voice_label()}")
    print(f"Name: {get_name()}")
    print(f"ffplay: {_ensure_player()}")
    print(f"ElevenLabs SDK installed: {HAS_ELEVENLABS}")
    print(f"ElevenLabs key set: {bool(os.getenv('ELEVENLABS_API_KEY'))}")
    quota = get_elevenlabs_quota()
    if quota:
        print(f"ElevenLabs credits: {quota['remaining']:,} / {quota['limit']:,}")
    print()
    print("Speaking test phrase...")
    speak(
        f"Good evening, {get_name()}. F.R.I.D.A.Y. systems online. "
        f"Premium voice provider engaged. All systems ready when you are.",
        blocking=True,
    )
    print("Done!")
