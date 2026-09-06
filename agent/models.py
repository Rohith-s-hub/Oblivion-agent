"""
Model Registry - catalog of verified working LLMs for Oblivion.
"""
import os

MODELS = {
    # ═══ FAST WORKING CLOUD MODELS ═════════════════════════════════
    "groq-gpt-oss": {
        "id": "groq/openai/gpt-oss-120b",
        "provider": "groq",
        "speed": "blazing (707ms)",
        "cost": "FREE (Groq)",
        "description": "GPT-OSS 120B via Groq ⚡ Ultra fast",
        "color": "#ff9500",
        "api_key_env": "GROQ_API_KEY",
        "context_window": 131_072,
        "rate_limit_delay": 0.0,
    },
    "gemini-flash": {
        "id": "gemini/gemini-2.5-flash",
        "provider": "gemini",
        "speed": "fast (2.8s)",
        "cost": "FREE (1500 req/day)",
        "description": "Gemini 2.5 Flash — 1M context, high capability",
        "color": "#4285F4",
        "api_key_env": "GEMINI_API_KEY",
        "context_window": 1_048_576,
        "rate_limit_delay": 0.5,
        "supports_function_calling": True,
    },
    "groq-llama-70b": {
        "id": "groq/openai/gpt-oss-120b",
        "provider": "groq",
        "speed": "blazing",
        "cost": "FREE (Groq)",
        "description": "Llama 3.1 70B via Groq (fast & capable)",
        "color": "#ff9500",
        "api_key_env": "GROQ_API_KEY",
        "context_window": 131_072,
        "rate_limit_delay": 0.2,
    },

    # ═══ LOCAL / OLLAMA MODELS ══════════════════════════════════════
    "gemma4-cloud": {
        "id": "ollama/gemma4:31b-cloud",
        "provider": "ollama",
        "speed": "medium",
        "cost": "FREE (Ollama Cloud)",
        "description": "Google Gemma 4 31B via Ollama Cloud",
        "color": "#4285f4",
        "api_key_env": None,
        "context_window": 131_072,
        "rate_limit_delay": 0.0,
    },
    "qwen35-local": {
        "id": "ollama/qwen3.5:4b",
        "provider": "ollama",
        "speed": "fast",
        "cost": "FREE (LOCAL - offline capable)",
        "description": "Qwen 3.5 4B running locally on your machine",
        "color": "#00d9ff",
        "api_key_env": None,
        "context_window": 32_768,
        "rate_limit_delay": 0.0,
    },

    # ═══ KEY-READY FLAGSHIPS (Active when keys set) ═════════════════
    "claude-sonnet": {
        "id": "anthropic/claude-3-5-sonnet-20241022",
        "provider": "anthropic",
        "speed": "fast",
        "cost": "Paid ($3/$15 per 1M)",
        "description": "Claude 3.5 Sonnet (genius-level)",
        "color": "#cc785c",
        "api_key_env": "ANTHROPIC_API_KEY",
        "context_window": 200_000,
        "rate_limit_delay": 0.0,
    },
    "gpt-4o": {
        "id": "openai/gpt-4o",
        "provider": "openai",
        "speed": "fast",
        "cost": "Paid ($2.50/$10 per 1M)",
        "description": "OpenAI GPT-4o Flagship",
        "color": "#10a37f",
        "api_key_env": "OPENAI_API_KEY",
        "context_window": 128_000,
        "rate_limit_delay": 0.0,
    },
    "deepseek": {
        "id": "deepseek/deepseek-chat",
        "provider": "deepseek",
        "speed": "fast",
        "cost": "$0.14/1M (cheap)",
        "description": "DeepSeek V3 (smart & cost effective)",
        "color": "#4d6bfe",
        "api_key_env": "DEEPSEEK_API_KEY",
        "context_window": 64_000,
        "rate_limit_delay": 0.0,
    },
}

CONTEXT_WINDOWS = {info["id"]: info["context_window"] for info in MODELS.values() if "context_window" in info}
RATE_LIMIT_DELAYS = {info["id"]: info.get("rate_limit_delay", 0.0) for info in MODELS.values()}


def get_context_limit(model_id: str) -> int:
    if model_id in CONTEXT_WINDOWS:
        return int(CONTEXT_WINDOWS[model_id] * 0.80)
    for known_id, window in CONTEXT_WINDOWS.items():
        if known_id in model_id or model_id in known_id:
            return int(window * 0.80)
    if "gemini" in model_id:
        return 800_000
    if "groq" in model_id:
        return 100_000
    if "claude" in model_id or "anthropic" in model_id:
        return 160_000
    if "ollama" in model_id:
        return 26_000
    return 32_000


def get_rate_delay(model_id: str) -> float:
    if model_id in RATE_LIMIT_DELAYS:
        return RATE_LIMIT_DELAYS[model_id]
    if "gemini" in model_id:
        return 0.5
    if "groq" in model_id:
        return 0.0
    return 0.0


def get_model_info(name_or_id: str) -> dict | None:
    if name_or_id in MODELS:
        return {"name": name_or_id, **MODELS[name_or_id]}
    for name, info in MODELS.items():
        if info["id"] == name_or_id:
            return {"name": name, **info}
    return None


def get_current_model_info() -> dict:
    current_id = os.getenv("DEFAULT_MODEL", "groq/openai/gpt-oss-120b")
    info = get_model_info(current_id)
    if info:
        return info
    return {
        "name": current_id.split("/")[-1][:25],
        "id": current_id,
        "provider": current_id.split("/")[0] if "/" in current_id else "unknown",
        "speed": "fast",
        "cost": "custom",
        "description": "Custom model",
        "color": "#00d9ff",
        "api_key_env": None,
        "context_window": 32_000,
        "rate_limit_delay": 0.0,
    }


def check_api_key(model_name: str) -> tuple[bool, str]:
    info = get_model_info(model_name)
    if not info:
        return False, f"Unknown model: {model_name}"
    key_env = info.get("api_key_env")
    if not key_env:
        return True, "ok"
    if not os.getenv(key_env):
        return False, (
            f"Missing API key for {info['provider']}.\n"
            f"Add {key_env}=... to ~/.oblivion/config.env then restart Oblivion."
        )
    return True, "ok"


def list_models_table() -> list[dict]:
    return [{"name": name, **info} for name, info in MODELS.items()]
