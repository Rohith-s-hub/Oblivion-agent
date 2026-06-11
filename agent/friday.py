"""
F.R.I.D.A.Y. - voice personality layer for Oblivion.

Pipeline:
  agent output -> personality LLM rewrite -> Edge TTS -> ffplay -> speaker
"""
import os
import asyncio
import tempfile
import threading
import subprocess
import shutil
from typing import Optional

import edge_tts

# Current playback process (so we can stop it)
_current_proc: Optional[subprocess.Popen] = None
_proc_lock = threading.Lock()

# Voice personas
VOICES = {
    "aria":     "en-US-AriaNeural",
    "jenny":    "en-US-JennyNeural",
    "sonia":    "en-GB-SoniaNeural",
    "natasha":  "en-AU-NatashaNeural",
    "emma":     "en-US-EmmaNeural",
    "michelle": "en-US-MichelleNeural",
    "guy":      "en-US-GuyNeural",
    "ryan":     "en-GB-RyanNeural",
}

ACKNOWLEDGMENTS = [
    "On it, {name}.",
    "One moment, {name}.",
    "Working on it, {name}.",
    "Right away, {name}.",
    "Coming up, {name}.",
]

COMPLETIONS = [
    "Done, {name}.",
    "All set, {name}.",
    "Finished, {name}.",
    "Ready, {name}.",
]


def _ensure_player() -> bool:
    return shutil.which("ffplay") is not None


def is_enabled() -> bool:
    return os.getenv("FRIDAY_ENABLED", "true").lower() == "true"


def get_voice() -> str:
    val = os.getenv("FRIDAY_VOICE", "en-US-AriaNeural")
    if val.lower() in VOICES:
        return VOICES[val.lower()]
    return val


def get_name() -> str:
    return os.getenv("FRIDAY_NAME", "boss")


def get_rate() -> str:
    return os.getenv("FRIDAY_RATE", "+0%")


def get_volume() -> str:
    return os.getenv("FRIDAY_VOLUME", "+0%")


async def _synth_to_file(text: str, output_path: str):
    """Synthesize text to mp3 via Edge TTS."""
    communicate = edge_tts.Communicate(
        text=text,
        voice=get_voice(),
        rate=get_rate(),
        volume=get_volume(),
    )
    await communicate.save(output_path)


def speak(text: str, blocking: bool = False) -> Optional[threading.Thread]:
    """Speak text via Edge TTS + ffplay."""
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

            asyncio.run(_synth_to_file(text, tmp_path))

            with _proc_lock:
                _current_proc = subprocess.Popen(
                    [
                        "ffplay",
                        "-nodisp",
                        "-autoexit",
                        "-loglevel", "quiet",
                        tmp_path,
                    ],
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
    """Stop any currently-playing speech."""
    global _current_proc
    with _proc_lock:
        if _current_proc is not None:
            try:
                _current_proc.terminate()
            except Exception:
                pass
            _current_proc = None


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
    """Rewrite output FRIDAY-style for speech."""
    if not text or not text.strip():
        return ""

    name = get_name()
    text = text.strip()

    # Short + simple = speak verbatim
    if len(text) < 200 and "```" not in text and "\n\n" not in text:
        return text

    use_llm = os.getenv("FRIDAY_USE_LLM_REWRITE", "true").lower() == "true"
    if not use_llm or llm_client is None:
        first_line = text.split("\n")[0][:150]
        return f"Here's what I found, {name}: {first_line}"

    try:
        prompt = PERSONALITY_PROMPT.format(name=name, output=text[:2000])

        # Use Groq if available (fast)
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


def acknowledge() -> str:
    import random
    return random.choice(ACKNOWLEDGMENTS).format(name=get_name())


def completion() -> str:
    import random
    return random.choice(COMPLETIONS).format(name=get_name())


# ── Self-test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Voice: {get_voice()}")
    print(f"Name: {get_name()}")
    print(f"ffplay available: {_ensure_player()}")
    print()
    print("Speaking test phrase...")
    speak(
        f"Good evening, {get_name()}. F.R.I.D.A.Y. online. All systems are ready when you are.",
        blocking=True,
    )
    print("Done!")
