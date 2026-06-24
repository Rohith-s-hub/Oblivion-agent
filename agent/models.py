"""
Model Registry - catalog of LLMs Oblivion can talk to.

Add new models here. litellm handles the actual API calls based on the prefix:
  ollama/<name>     -> local Ollama
  groq/<name>       -> Groq API (needs GROQ_API_KEY)
  anthropic/<name>  -> Claude (needs ANTHROPIC_API_KEY)
  openai/<name>     -> GPT (needs OPENAI_API_KEY)
  deepseek/<name>   -> DeepSeek (needs DEEPSEEK_API_KEY)
"""
import os

MODELS = {
    "qwen-coder": {
        "id": "ollama/qwen3-coder:480b-cloud",
        "provider": "ollama",
        "speed": "medium",
        "cost": "FREE",
        "description": "Default - Qwen3 Coder 480B (Ollama Cloud)",
        "color": "#00ff9f",
        "api_key_env": None,
    },
    "groq-llama": {
        "id": "groq/llama-3.3-70b-versatile",
        "provider": "groq",
        "speed": "blazing",
        "cost": "FREE",
        "description": "Llama 3.3 70B via Groq (200+ tok/s)",
        "color": "#ff9500",
        "api_key_env": "GROQ_API_KEY",
    },
    "groq-deepseek": {
        "id": "groq/deepseek-r1-distill-llama-70b",
        "provider": "groq",
        "speed": "blazing",
        "cost": "FREE",
        "description": "DeepSeek R1 distill via Groq (thinking + fast)",
        "color": "#ff9500",
        "api_key_env": "GROQ_API_KEY",
    },
    "groq-gpt-oss": {
        "id": "groq/openai/gpt-oss-120b",
        "provider": "groq",
        "speed": "blazing",
        "cost": "FREE",
        "description": "GPT-OSS 120B via Groq",
        "color": "#ff9500",
        "api_key_env": "GROQ_API_KEY",
    },
    "claude-sonnet": {
        "id": "anthropic/claude-sonnet-4-20250514",
        "provider": "anthropic",
        "speed": "fast",
        "cost": "$3/$15 per 1M",
        "description": "Claude Sonnet 4 (genius-level, paid)",
        "color": "#cc785c",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "gpt-4o": {
        "id": "openai/gpt-4o",
        "provider": "openai",
        "speed": "fast",
        "cost": "$2.50/$10 per 1M",
        "description": "OpenAI GPT-4o (paid)",
        "color": "#10a37f",
        "api_key_env": "OPENAI_API_KEY",
    },
    "deepseek": {
        "id": "deepseek/deepseek-chat",
        "provider": "deepseek",
        "speed": "fast",
        "cost": "$0.14/1M (cheap!)",
        "description": "DeepSeek V3 (very cheap, very smart)",
        "color": "#4d6bfe",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "gemini-flash": {
        "id": "gemini/gemini-2.5-flash",
        "description": "Gemini 2.5 Flash — 1M context, blazing fast, generous free tier (recommended)",
        "color": "#4285F4",
        "context_window": 1_048_576,
        "supports_function_calling": True,
        "api_key_env": "GEMINI_API_KEY",
        "provider": "gemini",
            "cost": "FREE (1500 req/day)",
        "speed": "fast",
},
    "qwen3-coder-or": {
        "id": "openrouter/qwen/qwen3-coder:free",
        "provider": "openrouter",
        "speed": "fast",
        "cost": "FREE (OpenRouter)",
        "description": "Qwen3 Coder 480B via OpenRouter - 1M ctx, FREE backup",
        "color": "#a020f0",
        "api_key_env": "OPENROUTER_API_KEY",
        "context_window": 1_048_576,
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
    },
    "gpt-oss-or": {
        "id": "openrouter/openai/gpt-oss-120b:free",
        "provider": "openrouter",
        "speed": "fast",
        "cost": "FREE (OpenRouter)",
        "description": "OpenAI GPT-OSS 120B - open weights via OpenRouter, FREE",
        "color": "#10a37f",
        "api_key_env": "OPENROUTER_API_KEY",
        "context_window": 131_072,
    },
    "llama-3.3-or": {
        "id": "openrouter/meta-llama/llama-3.3-70b-instruct:free",
        "provider": "openrouter",
        "speed": "fast",
        "cost": "FREE (OpenRouter)",
        "description": "Meta Llama 3.3 70B via OpenRouter, FREE backup to Groq",
        "color": "#1877f2",
        "api_key_env": "OPENROUTER_API_KEY",
        "context_window": 131_072,
    },
        "gemini-pro": {
        "id": "gemini/gemini-2.5-pro",
        "description": "Gemini 2.5 Pro — smarter than Flash, slower, lower free quota",
        "color": "#1A73E8",
        "context_window": 2_097_152,
        "supports_function_calling": True,
        "api_key_env": "GEMINI_API_KEY",
        "provider": "gemini",
            "cost": "FREE (1500 req/day)",
        "speed": "fast",
},
}


def get_model_info(name_or_id: str) -> dict | None:
    """Look up a model by short name OR full id."""
    if name_or_id in MODELS:
        return {"name": name_or_id, **MODELS[name_or_id]}
    # Try to match by full id (so /model ollama/foo works too)
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
    # Not in catalog - return generic info
    return {
        "name": current_id.split("/")[-1][:25],
        "id": current_id,
        "provider": current_id.split("/")[0] if "/" in current_id else "unknown",
        "speed": "?",
        "cost": "?",
        "description": "Custom model (not in catalog)",
        "color": "#00d9ff",
        "api_key_env": None,
    }


def check_api_key(model_name: str) -> tuple[bool, str]:
    """
    Verify the model's API key is set.
    Returns (ok, message).
    """
    info = get_model_info(model_name)
    if not info:
        return False, f"Unknown model: {model_name}"

    key_env = info.get("api_key_env")
    if not key_env:
        return True, "ok"  # No key needed (e.g. Ollama)

    if not os.getenv(key_env):
        return False, (
            f"Missing API key for {info['provider']}. "
            f"Add {key_env}=... to ~/.oblivion/config.env then restart Oblivion."
        )

    return True, "ok"


def list_models_table() -> list[dict]:
    """Return all models as list of dicts (for display)."""
    return [{"name": name, **info} for name, info in MODELS.items()]
