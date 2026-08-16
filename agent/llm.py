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
    # ═══ TIER 1: PROVEN FREE PRIMARY ═══════════════════════════════════
    # Only remaining FREE Ollama Cloud model (verified Aug 2026)
    # 32.7B params, 256K ctx, vision+tools, no rate limits
    "ollama/gemma4:31b-cloud",           # ⭐ THE WINNER

    # ═══ TIER 2: FAST FREE CLOUD APIs ══════════════════════════════════
    # Free tiers with generous per-minute limits
    "gemini/gemini-2.5-flash",           # 1M ctx, 250/day
    "groq/llama-3.3-70b-versatile",      # 30 RPM, blazing fast

    # ═══ TIER 3: OPENROUTER FREE ═══════════════════════════════════════
    # Backup free cloud when others rate-limited
    "openrouter/google/gemma-4-31b-it:free",
    "openrouter/openai/gpt-oss-20b:free",

    # ═══ TIER 4: LOCAL SAFETY NET ══════════════════════════════════════
    # Always works, no internet needed
    "ollama/qwen3.5:4b",

    # ═══ REMOVED (verified dead/paid Aug 2026) ═════════════════════════
    # - ollama/qwen3-coder:480b-cloud    RETIRED 2026-07-15
    # - ollama/qwen3.5:397b-cloud        PAID subscription required
    # - ollama/glm-5.2:cloud              PAID subscription required
    # - groq/openai/gpt-oss-120b          8K TPM too small
    # - cerebras/*                        needs paid API key
    # - nvidia/nemotron-3-ultra           too slow, unreliable
]

# How long to keep a model "exhausted" before retrying (seconds)
# Different cooldowns for different error types (based on 2025 limits)
COOLDOWN_QUOTA_DAY = 3600 * 4   # 4 hours (daily quota)
COOLDOWN_QUOTA_MIN = 60         # 1 minute (per-minute limit)
COOLDOWN_SERVICE_DOWN = 120     # 2 minutes (503, overloaded)
COOLDOWN_AUTH = 3600 * 24       # 24 hours (bad API key - rare fix needed)
COOLDOWN_DEFAULT = 300          # 5 minutes (fallback)

# Legacy name for backward compat
EXHAUSTION_COOLDOWN = COOLDOWN_DEFAULT

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
    # Model output errors — model got confused, try a different one
    "tool_use_failed", "invalid literal for int",
    "invalid json", "malformed", "bad_response",
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
        return "missing API key (skipping)"
    if "missing credentials" in msg_lower:
        return "no API key configured"
    if "tool_use_failed" in msg_lower or "invalid literal for int" in msg_lower:
        return "model output error"
    if "invalid json" in msg_lower or "malformed" in msg_lower:
        return "malformed model output"
    if "request too large" in msg_lower or "tpm" in msg_lower:
        return "prompt too large for this model tier"
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
        self.max_tokens = int(os.getenv("MAX_TOKENS", "8192"))
        self.temperature = float(os.getenv("TEMPERATURE", "0.1"))
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    @property
    def model(self) -> str:
        """Read model fresh each call - allows mid-session switching."""
        return os.getenv("DEFAULT_MODEL", "ollama/qwen3-coder:480b-cloud")

    @property
    def rate_limit_delay(self) -> float:
        """Rate limit delay for current model (seconds between calls)."""
        try:
            from agent.models import get_rate_delay
            return get_rate_delay(self.model)
        except Exception:
            return 1.5  # safe default

    # ── Exhaustion tracking ─────────────────────────────────────────────────
    @classmethod
    def _mark_exhausted(cls, model: str, error: Exception = None) -> None:
        """Mark model exhausted with smart cooldown based on error type."""
        # Determine cooldown based on error
        cooldown = COOLDOWN_DEFAULT
        if error:
            msg = str(error).lower()
            if "quota" in msg and ("day" in msg or "daily" in msg):
                cooldown = COOLDOWN_QUOTA_DAY
            elif "rate limit" in msg or "429" in msg or "per minute" in msg:
                cooldown = COOLDOWN_QUOTA_MIN
            elif "503" in msg or "overloaded" in msg or "unavailable" in msg:
                cooldown = COOLDOWN_SERVICE_DOWN
            elif "401" in msg or "api key" in msg or "authentication" in msg:
                cooldown = COOLDOWN_AUTH
        cls._exhausted[model] = (time.time(), cooldown)

    @classmethod
    def _is_exhausted(cls, model: str) -> bool:
        """True if model was marked exhausted within its cooldown window."""
        entry = cls._exhausted.get(model)
        if entry is None:
            return False
        # Handle both old (timestamp) and new (tuple) formats
        if isinstance(entry, tuple):
            ts, cooldown = entry
        else:
            ts, cooldown = entry, EXHAUSTION_COOLDOWN
        if time.time() - ts > cooldown:
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
        self.last_used_model = model  # track for status bar

        # Build extra kwargs for Ollama models (they need special options)
        extra = {}
        if model.startswith("ollama/"):
            # Ollama needs these in an "options" dict for full context/generation
            extra = {
                "num_predict": self.max_tokens,   # respect our max_tokens
                "num_ctx": 32768,                 # use large context window
            }
            # Set timeout longer for large cloud models
            timeout_val = 180 if "cloud" in model else 120
        else:
            timeout_val = 90

        if on_token:
            # TRUE streaming: token by token, not dump-at-end
            response = litellm.completion(
                model=model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stream=True,
                timeout=timeout_val,
                **extra,
            )
            full = ""
            for chunk in response:
                delta = ""
                try:
                    delta = chunk.choices[0].delta.content or ""
                except Exception:
                    pass
                if delta:
                    full += delta
                    try:
                        on_token(delta)
                    except Exception:
                        pass
            # Token stats after streaming
            self.total_output_tokens += len(full) // 4
            self.total_input_tokens += sum(len(m.get("content", "")) for m in messages) // 4
            return full
        else:
            # Non-streaming: use real token counts from API
            response = litellm.completion(
                model=model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stream=False,
                timeout=timeout_val,
                **extra,
            )
            full = response.choices[0].message.content or ""
            # Use real token counts if available
            if hasattr(response, "usage") and response.usage:
                self.total_input_tokens += getattr(response.usage, "prompt_tokens", 0) or 0
                self.total_output_tokens += getattr(response.usage, "completion_tokens", 0) or 0
            else:
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
        failed_count = 0  # track actual failures not skips

        for model in chain:
            if self._is_exhausted(model):
                continue  # silently skip exhausted models

            try:
                if failed_count > 0:  # only notify on actual failure fallback
                    short = model.split("/")[-1][:30]
                    self._notify("falling back to " + short + "...")
                return self._call_model(model, messages, on_token)

            except Exception as e:
                last_error = e
                failed_count += 1

                if not _is_retryable(e):
                    # Non-retryable error (e.g. bad request, auth) — stop trying
                    raise

                # Retryable — mark exhausted with smart cooldown, try next
                self._mark_exhausted(model, e)
                short = model.split("/")[-1][:30]
                err_brief = _short_error(e)
                self._notify(short + " " + err_brief + " - trying next...")

                # TASK RECAP: on first fallback, inject a system message
                # so the new model doesn't confuse current task with earlier context
                if failed_count == 1 and len(messages) > 4:
                    last_user_msg = None
                    for msg in reversed(messages):
                        if msg.get("role") == "user":
                            c = msg.get("content", "")
                            if isinstance(c, str) and 10 < len(c) < 500:
                                last_user_msg = c
                                break
                    if last_user_msg:
                        messages = messages + [{
                            "role": "system",
                            "content": (
                                f"[MODEL SWITCHED: Continue with the CURRENT task only: "
                                f"{last_user_msg[:200]}. Do NOT restart from earlier context.]"
                            )
                        }]
                continue

        # All models exhausted
        tried = ", ".join(m.split("/")[-1][:20] for m in chain)
        last_err_str = _short_error(last_error) if last_error else "unknown"
        raise RuntimeError(
            f"All {len(chain)} models in fallback chain failed. "
            f"Tried: {tried}. "
            f"Last error: {last_err_str}"
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
        for model, entry in list(LLMClient._exhausted.items()):
            if isinstance(entry, tuple):
                ts, cooldown = entry
            else:
                ts, cooldown = entry, EXHAUSTION_COOLDOWN
            elapsed = now - ts
            if elapsed > cooldown:
                del LLMClient._exhausted[model]
                continue
            out.append({
                "model": model,
                "exhausted_for": int(elapsed),
                "retry_in": int(cooldown - elapsed),
                "cooldown_type": (
                    "quota-day" if cooldown >= 3600 else
                    "auth" if cooldown >= 3600 * 24 else
                    "service" if cooldown == COOLDOWN_SERVICE_DOWN else
                    "quota-min" if cooldown == COOLDOWN_QUOTA_MIN else
                    "default"
                ),
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
