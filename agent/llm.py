import os
import json
import time
from typing import Callable, Optional
from dotenv import load_dotenv
import litellm
from rich.console import Console

console = Console()

os.environ["OLLAMA_API_BASE"] = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
litellm.set_verbose = False
litellm.drop_params = True


# ── Fallback config ─────────────────────────────────────────────────────────
# Order: primary (whatever DEFAULT_MODEL is) → these in sequence
FALLBACK_CHAIN = [
    # PRIMARY: Groq - fastest + genuinely good at code
    "groq/openai/gpt-oss-120b",              # 1. Best free coder per real-world use
    "groq/llama-3.3-70b-versatile",          # 2. Fast generalist backup
    # SECONDARY: Big context cloud, reliable when Groq quota hits
    "gemini/gemini-2.5-flash",               # 3. 1M ctx
    # CODING-SPECIALIZED
    "openrouter/cohere/north-mini-code:free", # 4. Coding-tuned specifically
    # LOCAL: 262K ctx, tools+thinking capable, always works offline
    "ollama/qwen3.5:4b",                     # 5. Local Qwen 3.5 (promoted from dead last)
    # OpenRouter free tier fallbacks
    "openrouter/openai/gpt-oss-20b:free",    # 6. Smaller GPT-OSS
    "openrouter/google/gemma-4-31b-it:free", # 7. General purpose (dedup, no Ollama duplicate)
    # LAST RESORT: unreliable free tiers when everything else fails
    "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",  # 8. Rate-limited but frontier
    "cerebras/llama-3.3-70b",                # 9. Deepest backup
]

# How long to keep a model "exhausted" before retrying (seconds)
EXHAUSTION_COOLDOWN = 300  # 5 minutes

# Errors that trigger fallback (case-insensitive substring match)
RETRYABLE_ERROR_HINTS = [
    "503", "unavailable", "overloaded", "high demand",
    "429", "rate limit", "quota", "exhausted", "too many requests",
    "timeout", "timed out",
    "connection", "connect", "network",
    "internal server error", "500", "502", "504",
    # Auth errors — likely stale/wrong key for THIS model; try next
    "401", "unauthenticated", "invalid api key", "invalid_api_key",
    "permission denied", "access_token_type_unsupported",
]


def _is_retryable(err: Exception) -> bool:
    """Should we try the next model in the chain?"""
    msg = str(err).lower()
    return any(hint in msg for hint in RETRYABLE_ERROR_HINTS)


def _short_error(err: Exception) -> str:
    """One-line human-readable error for UI display. Never shows stack traces."""
    msg = str(err)
    msg_lower = msg.lower()
    if "not found" in msg_lower or "notfound" in msg_lower or "does not exist" in msg_lower:
        return "model not available"
    if "503" in msg or "overloaded" in msg_lower or "high demand" in msg_lower or "unavailable" in msg_lower:
        return "service overloaded (503)"
    if "429" in msg or "rate limit" in msg_lower or "quota" in msg_lower or "exhausted" in msg_lower:
        return "rate limited / quota exceeded"
    if "timeout" in msg_lower or "timed out" in msg_lower:
        return "timeout"
    if "connect" in msg_lower or "network" in msg_lower:
        return "network error"
    if "401" in msg or "api key" in msg_lower or "authentication" in msg_lower or "unauthenticated" in msg_lower:
        return "invalid or missing API key"
    if "500" in msg or "502" in msg or "504" in msg or "internal server" in msg_lower:
        return "provider server error"
    # Truncate and strip any JSON/dict garbage
    clean = msg.split("{")[0].split("\n")[0].strip()
    if len(clean) > 60:
        clean = clean[:60] + "..."
    return clean or "unknown error"


class LLMClient:
    # Class-level exhaustion tracking (per-session, in-memory only)
    # {model_id: timestamp_when_marked_exhausted}
    _exhausted: dict = {}

    # UI hook — set by TUI to display fallback notifications
    # signature: callback(message: str) -> None
    on_fallback_notify: Optional[Callable[[str], None]] = None

    def __init__(self):
        self.max_tokens = int(os.getenv("MAX_TOKENS", "4096"))
        self.temperature = float(os.getenv("TEMPERATURE", "0.1"))
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    @property
    def model(self) -> str:
        """Read model fresh each call - allows mid-session switching."""
        return os.getenv("DEFAULT_MODEL", "ollama/qwen3-coder:480b-cloud")

    # ── Exhaustion tracking ─────────────────────────────────────────────────
    @classmethod
    def _mark_exhausted(cls, model: str) -> None:
        cls._exhausted[model] = time.time()

    @classmethod
    def _is_exhausted(cls, model: str) -> bool:
        """True if model was marked exhausted within the cooldown window."""
        ts = cls._exhausted.get(model)
        if ts is None:
            return False
        if time.time() - ts > EXHAUSTION_COOLDOWN:
            # Cooldown expired — give it another shot
            del cls._exhausted[model]
            return False
        return True

    @classmethod
    def reset_exhausted_models(cls) -> None:
        """Clear all exhaustion marks (for /model reset command)."""
        cls._exhausted.clear()

    def _notify(self, msg: str) -> None:
        """Send fallback notification to UI if hook is set."""
        try:
            if LLMClient.on_fallback_notify:
                LLMClient.on_fallback_notify(msg)
        except Exception:
            pass

    # ── Build the chain for this call ───────────────────────────────────────
    def _build_chain(self) -> list:
        """User's current /model choice first, then FALLBACK_CHAIN, dedup."""
        primary = self.model
        chain = [primary]
        for m in FALLBACK_CHAIN:
            if m not in chain:
                chain.append(m)
        return chain

    # ── Core: call one specific model (no fallback logic) ───────────────────
    def _call_model(self, model: str, messages: list, on_token=None) -> str:
        response = litellm.completion(
            model=model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            stream=False,
            timeout=90,
        )
        full = response.choices[0].message.content or ""
        if on_token and full:
            on_token(full)
        self.total_output_tokens += len(full) // 4
        self.total_input_tokens += sum(len(m.get("content", "")) for m in messages) // 4
        return full

    # ── Public: streaming chat with auto-fallback ───────────────────────────
    def chat_stream(self, messages: list, on_token=None) -> str:
        """Try primary model. If it fails with retryable error, walk fallback chain.

        Skips models marked exhausted in the last 5 minutes.
        Notifies UI via on_fallback_notify hook when a swap happens.
        """
        chain = self._build_chain()
        last_error = None
        attempted = []

        for model in chain:
            if self._is_exhausted(model):
                attempted.append(model + " (exhausted)")
                continue

            try:
                if attempted:  # we're falling back, not on primary
                    short = model.split("/")[-1][:30]
                    self._notify("falling back to " + short + "...")
                return self._call_model(model, messages, on_token)

            except Exception as e:
                last_error = e
                attempted.append(model)

                if not _is_retryable(e):
                    # Non-retryable error (e.g. bad request, auth) — stop trying
                    raise

                # Retryable — mark exhausted, try next
                self._mark_exhausted(model)
                short = model.split("/")[-1][:30]
                err_brief = _short_error(e)
                self._notify(short + " " + err_brief + " - trying next...")
                continue

        # All models exhausted
        tried = ", ".join(m.split("/")[-1][:20] for m in chain)
        raise RuntimeError(
            "All " + str(len(chain)) + " models in fallback chain failed. "
            "Tried: " + tried + ". "
            "Last error: " + _short_error(last_error) if last_error else "unknown"
        )

    # ── CLI-compatible non-streaming chat ───────────────────────────────────
    def chat(self, messages: list, stream: bool = True) -> str:
        """Sync chat - used by CLI main.py."""
        if stream:
            # Use the fallback-aware streaming path
            return self.chat_stream(messages, on_token=lambda t: print(t, end="", flush=True))

        # Non-streaming with fallback too
        chain = self._build_chain()
        last_error = None
        for model in chain:
            if self._is_exhausted(model):
                continue
            try:
                response = litellm.completion(
                    model=model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    stream=False,
                    timeout=90,
                )
                content = response.choices[0].message.content
                if hasattr(response, "usage") and response.usage:
                    self.total_input_tokens += response.usage.prompt_tokens or 0
                    self.total_output_tokens += response.usage.completion_tokens or 0
                return content
            except Exception as e:
                last_error = e
                if not _is_retryable(e):
                    raise
                self._mark_exhausted(model)
                continue

        raise RuntimeError("All models failed. Last: " + _short_error(last_error))

    # ── Stats & utilities ───────────────────────────────────────────────────
    def get_token_stats(self) -> dict:
        return {
            "input": self.total_input_tokens,
            "output": self.total_output_tokens,
            "total": self.total_input_tokens + self.total_output_tokens,
        }

    def reset_token_stats(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def get_exhausted_models(self) -> list:
        """Return list of currently exhausted models with seconds-until-retry."""
        now = time.time()
        out = []
        for model, ts in list(LLMClient._exhausted.items()):
            elapsed = now - ts
            if elapsed > EXHAUSTION_COOLDOWN:
                del LLMClient._exhausted[model]
                continue
            out.append({
                "model": model,
                "exhausted_for": int(elapsed),
                "retry_in": int(EXHAUSTION_COOLDOWN - elapsed),
            })
        return out

    def chat_json(self, messages: list) -> dict:
        json_messages = messages + [{
            "role": "system",
            "content": "Respond with ONLY valid JSON. No markdown."
        }]
        raw = self.chat(json_messages, stream=False).strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            console.print("[yellow]JSON parse failed: " + str(e) + "[/yellow]")
            return {"error": "invalid_json", "raw": raw}
