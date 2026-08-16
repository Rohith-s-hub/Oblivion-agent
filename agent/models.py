"""
Model Registry - catalog of LLMs Oblivion can talk to.

Add new models here. litellm handles the actual API calls based on the prefix:
  ollama/<name>     -> local Ollama
  groq/<name>       -> Groq API (needs GROQ_API_KEY)
  anthropic/<name>  -> Claude (needs ANTHROPIC_API_KEY)
  openai/<name>     -> GPT (needs OPENAI_API_KEY)
  deepseek/<name>   -> DeepSeek (needs DEEPSEEK_API_KEY)
  gemini/<name>     -> Gemini (needs GEMINI_API_KEY)
  openrouter/<name> -> OpenRouter (needs OPENROUTER_API_KEY)
"""
import os

MODELS = {
    "gemma4-cloud": {
        "id": "ollama/gemma4:31b-cloud",
        "provider": "ollama",
        "speed": "medium",
        "cost": "FREE (Ollama Cloud)",
        "description": "Google Gemma 4 31B via Ollama Cloud",
        "color": "#4285f4",
        "api_key_env": None,
        "context_window": 131_072,
        "rate_limit_delay": 1.0,  # 60.0 RPM max  # unlimited RPM max
    },
    "qwen35-local": {
        "id": "ollama/qwen3.5:4b",
        "provider": "ollama",
        "speed": "fast",
        "cost": "FREE (LOCAL - offline capable)",
        "description": "Qwen 3.5 4B running LOCALLY on your machine (offline, private)",
        "color": "#00d9ff",
        "api_key_env": None,
        "context_window": 32_768,
        "rate_limit_delay": 0.0,
    },
    "groq-llama": {
        "id": "groq/llama-3.3-70b-versatile",
        "provider": "groq",
        "speed": "blazing",
        "cost": "FREE",
        "description": "Llama 3.3 70B via Groq (200+ tok/s)",
        "color": "#ff9500",
        "api_key_env": "GROQ_API_KEY",
        "context_window": 128_000,
        "rate_limit_delay": 2.0,  # 30.0 RPM max
    },
    "groq-deepseek": {
        "id": "groq/deepseek-r1-distill-llama-70b",
        "provider": "groq",
        "speed": "blazing",
        "cost": "FREE",
        "description": "DeepSeek R1 distill via Groq (thinking + fast)",
        "color": "#ff9500",
        "api_key_env": "GROQ_API_KEY",
        "context_window": 128_000,
        "rate_limit_delay": 2.0,  # 30.0 RPM max
    },
    "groq-gpt-oss": {
        "id": "groq/openai/gpt-oss-120b",
        "provider": "groq",
        "speed": "blazing",
        "cost": "FREE",
        "description": "GPT-OSS 120B via Groq",
        "color": "#ff9500",
        "api_key_env": "GROQ_API_KEY",
        "context_window": 128_000,
        "rate_limit_delay": 2.0,  # 30.0 RPM max
    },
    "claude-sonnet": {
        "id": "anthropic/claude-sonnet-4-20250514",
        "provider": "anthropic",
        "speed": "fast",
        "cost": "$3/$15 per 1M",
        "description": "Claude Sonnet 4 (genius-level, paid)",
        "color": "#cc785c",
        "api_key_env": "ANTHROPIC_API_KEY",
        "context_window": 200_000,
        "rate_limit_delay": 1.0,  # 60.0 RPM max
    },
    "gpt-4o": {
        "id": "openai/gpt-4o",
        "provider": "openai",
        "speed": "fast",
        "cost": "$2.50/$10 per 1M",
        "description": "OpenAI GPT-4o (paid)",
        "color": "#10a37f",
        "api_key_env": "OPENAI_API_KEY",
        "context_window": 128_000,
        "rate_limit_delay": 1.0,  # 60.0 RPM max
    },
    "deepseek": {
        "id": "deepseek/deepseek-chat",
        "provider": "deepseek",
        "speed": "fast",
        "cost": "$0.14/1M (cheap!)",
        "description": "DeepSeek V3 (very cheap, very smart)",
        "color": "#4d6bfe",
        "api_key_env": "DEEPSEEK_API_KEY",
        "context_window": 64_000,
        "rate_limit_delay": 1.0,  # 60.0 RPM max
    },
    "gemini-flash": {
        "id": "gemini/gemini-2.5-flash",
        "provider": "gemini",
        "speed": "fast",
        "cost": "FREE (1500 req/day)",
        "description": "Gemini 2.5 Flash — 1M context, blazing fast, generous free tier (recommended)",
        "color": "#4285F4",
        "api_key_env": "GEMINI_API_KEY",
        "context_window": 1_048_576,
        "rate_limit_delay": 6.0,  # 10.0 RPM max
        "supports_function_calling": True,
    },
    "gemini-pro": {
        "id": "gemini/gemini-2.5-pro",
        "provider": "gemini",
        "speed": "medium",
        "cost": "FREE (limited quota)",
        "description": "Gemini 2.5 Pro — smarter than Flash, slower, lower free quota",
        "color": "#1A73E8",
        "api_key_env": "GEMINI_API_KEY",
        "context_window": 2_097_152,
        "rate_limit_delay": 12.0,  # 5.0 RPM max
        "supports_function_calling": True,
    },
    "nemotron-ultra": {
        "id": "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
        "provider": "openrouter",
        "speed": "medium",
        "cost": "FREE (OpenRouter)",
        "description": "NVIDIA Nemotron 3 Ultra 550B - 1M ctx, frontier reasoning",
        "color": "#76b900",
        "api_key_env": "OPENROUTER_API_KEY",
        "context_window": 1_000_000,
        "rate_limit_delay": 3.0,  # 20.0 RPM max
    },
    "gpt-oss-or": {
        "id": "openrouter/openai/gpt-oss-20b:free",
        "provider": "openrouter",
        "speed": "fast",
        "cost": "FREE (OpenRouter)",
        "description": "OpenAI GPT-OSS 20B via OpenRouter, 131K ctx, FREE",
        "color": "#10a37f",
        "api_key_env": "OPENROUTER_API_KEY",
        "context_window": 131_072,
        "rate_limit_delay": 3.0,  # 20.0 RPM max
    },
    "gemma-4-31b": {
        "id": "openrouter/google/gemma-4-31b-it:free",
        "provider": "openrouter",
        "speed": "fast",
        "cost": "FREE (OpenRouter)",
        "description": "Google Gemma 4 31B - 262K ctx, FREE, general purpose",
        "color": "#4285f4",
        "api_key_env": "OPENROUTER_API_KEY",
        "context_window": 262_144,
        "rate_limit_delay": 3.0,  # 20.0 RPM max
    },

    # ═══ OLLAMA CLOUD MODELS (unlimited, no rate limits!) ═══════════════
    "qwen3-coder": {
        "id": "ollama/qwen3-coder:480b-cloud",
        "provider": "ollama-cloud",
        "speed": "medium",
        "cost": "FREE (Ollama Cloud, unlimited)",
        "description": "Qwen3 Coder 480B - CODING SPECIALIST via Ollama Cloud",
        "color": "#00d9ff",
        "api_key_env": None,
        "context_window": 262_144,
        "rate_limit_delay": 0.0,  # no rate limit on Ollama Cloud
    },
    "qwen3-general": {
        "id": "ollama/qwen3.5:397b-cloud",
        "provider": "ollama-cloud",
        "speed": "medium",
        "cost": "FREE (Ollama Cloud, unlimited)",
        "description": "Qwen 3.5 397B - general purpose via Ollama Cloud",
        "color": "#00d9ff",
        "api_key_env": None,
        "context_window": 32_768,
        "rate_limit_delay": 0.0,
    },
    "glm-cloud": {
        "id": "ollama/glm-5.2:cloud",
        "provider": "ollama-cloud",
        "speed": "medium",
        "cost": "FREE (Ollama Cloud, unlimited)",
        "description": "GLM 5.2 via Ollama Cloud (multilingual)",
        "color": "#00d9ff",
        "api_key_env": None,
        "context_window": 32_768,
        "rate_limit_delay": 0.0,
    },
}


# ── Context window lookup ─────────────────────────────────────────────────────
# Used by runtime.py to set compression threshold dynamically
# Keyed by full model ID (as used in litellm calls)
CONTEXT_WINDOWS: dict[str, int] = {
    info["id"]: info["context_window"]
    for info in MODELS.values()
    if "context_window" in info
}

# Rate limit delays keyed by full model ID
RATE_LIMIT_DELAYS: dict[str, float] = {
    info["id"]: info.get("rate_limit_delay", 1.5)
    for info in MODELS.values()
}


def get_context_limit(model_id: str) -> int:
    """
    Get context window size for a model ID.
    Returns safe conservative limit (80% of max to leave room for response).
    Falls back to 8000 tokens if model unknown.
    """
    # Try exact match
    if model_id in CONTEXT_WINDOWS:
        return int(CONTEXT_WINDOWS[model_id] * 0.80)

    # Try partial match (model ID might have version suffix)
    for known_id, window in CONTEXT_WINDOWS.items():
        if known_id in model_id or model_id in known_id:
            return int(window * 0.80)

    # Provider-based fallback
    if "gemini" in model_id:
        return 800_000    # Gemini models have huge context
    if "groq" in model_id:
        return 100_000    # Groq models: 128K
    if "claude" in model_id or "anthropic" in model_id:
        return 160_000    # Claude: 200K
    if "ollama" in model_id:
        return 26_000     # Local models: conservative
    if "openrouter" in model_id:
        return 100_000    # OpenRouter: assume 131K

    return 8_000          # Unknown: safe default


def get_rate_delay(model_id: str) -> float:
    """
    Get rate limit delay in seconds for a model.
    Used by runtime.py between LLM calls.
    """
    if model_id in RATE_LIMIT_DELAYS:
        return RATE_LIMIT_DELAYS[model_id]

    # Provider-based fallback
    if "gemini" in model_id:
        return 6.0
    if "groq" in model_id:
        return 0.5
    if "ollama" in model_id:
        return 0.0
    if "openrouter" in model_id:
        return 1.0

    return 1.5  # conservative default


def get_model_info(name_or_id: str) -> dict | None:
    """Look up a model by short name OR full id."""
    if name_or_id in MODELS:
        return {"name": name_or_id, **MODELS[name_or_id]}
    for name, info in MODELS.items():
        if info["id"] == name_or_id:
            return {"name": name, **info}
    return None


def get_current_model_info() -> dict:
    """Find current model in registry based on env var."""
    current_id = os.getenv("DEFAULT_MODEL", "ollama/qwen3-coder:480b-cloud")
    info = get_model_info(current_id)
    if info:
        return info
    return {
        "name": current_id.split("/")[-1][:25],
        "id": current_id,
        "provider": current_id.split("/")[0] if "/" in current_id else "unknown",
        "speed": "?",
        "cost": "?",
        "description": "Custom model (not in catalog)",
        "color": "#00d9ff",
        "api_key_env": None,
        "context_window": 8_000,
        "rate_limit_delay": 1.5,
    }


def check_api_key(model_name: str) -> tuple[bool, str]:
    """Verify the model API key is set. Returns (ok, message)."""
    info = get_model_info(model_name)
    if not info:
        return False, f"Unknown model: {model_name}"

    key_env = info.get("api_key_env")
    if not key_env:
        return True, "ok"

    if not os.getenv(key_env):
        return False, (
            f"Missing API key for {info['provider']}. "
            f"Add {key_env}=... to ~/.oblivion/config.env then restart Oblivion."
        )

    return True, "ok"


def list_models_table() -> list[dict]:
    """Return all models as list of dicts (for display)."""
    return [{"name": name, **info} for name, info in MODELS.items()]
