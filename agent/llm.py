import os
import json
from typing import Callable, Optional
from dotenv import load_dotenv
import litellm
from rich.console import Console

load_dotenv()

console = Console()

os.environ["OLLAMA_API_BASE"] = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
litellm.set_verbose = False
litellm.drop_params = True  # silently drop unsupported params per-provider


class LLMClient:
    def __init__(self):
        self.max_tokens = int(os.getenv("MAX_TOKENS", "4096"))
        self.temperature = float(os.getenv("TEMPERATURE", "0.1"))
        # Token tracking (cumulative across all calls in this session)
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        # Load persisted exhausted models from disk
        LLMClient._exhausted_models = LLMClient._load_exhausted()

    @property
    def model(self) -> str:
        """Read model fresh each call - allows mid-session switching."""
        return os.getenv("DEFAULT_MODEL", "ollama/qwen3-coder:480b-cloud")

    def chat(self, messages: list, stream: bool = True) -> str:
        """Sync chat - prints stream to stdout (used by CLI)."""
        try:
            response = litellm.completion(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stream=stream,
            )
            if stream:
                full = ""
                for chunk in response:
                    delta = chunk.choices[0].delta.content or ""
                    full += delta
                    print(delta, end="", flush=True)
                print()
                # Rough token estimate for streamed responses
                self.total_output_tokens += len(full) // 4
                self.total_input_tokens += sum(len(m.get("content", "")) for m in messages) // 4
                return full
            else:
                content = response.choices[0].message.content
                if hasattr(response, "usage") and response.usage:
                    self.total_input_tokens += response.usage.prompt_tokens or 0
                    self.total_output_tokens += response.usage.completion_tokens or 0
                return content
        except Exception as e:
            console.print(f"[red]LLM Error: {e}[/red]")
            raise

    # Smart fallback chain: try these in order if primary fails.
    # All Groq models verified live as of fix date.
    # Ordering: code-specialist first, then large generalists, then fast small, then Ollama.
    FALLBACK_CHAIN = [
        # PRIMARY: Gemini 2.5 Flash — 1M context, generous free tier
        "gemini/gemini-2.5-flash",
        # SECONDARY: Local Ollama (no rate limits, slow but reliable)
        "ollama/qwen3-coder:480b-cloud",
        # TERTIARY: Groq (fast but daily rate limit)
        "groq/llama-3.3-70b-versatile",
        # QUATERNARY: Other Groq options
        "groq/openai/gpt-oss-120b",
        "groq/meta-llama/llama-4-scout-17b-16e-instruct",
        # EXTRA FREE: Cerebras (very fast, generous limits)
        "cerebras/llama-3.3-70b",
    ]
    # Track which models are known-exhausted (persisted across restarts)
    @classmethod
    def _exhausted_file(cls):
        from pathlib import Path as _P
        d = _P.home() / ".ai-agent"
        d.mkdir(parents=True, exist_ok=True)
        return d / "exhausted_models.txt"

    @classmethod
    def _load_exhausted(cls):
        """In-memory only. Wipe any stale on-disk cache from old versions."""
        try:
            f = cls._exhausted_file()
            if f.exists():
                f.unlink()
        except Exception:
            pass
        return set()

    @classmethod
    def _save_exhausted(cls, models: set):
        """No-op. Exhaustion is per-session only, never persisted."""
        pass

    # Loaded fresh from disk on each LLMClient instantiation
    _exhausted_models: set = set()

    def chat_stream(
        self,
        messages: list,
        on_token: Optional[Callable[[str], None]] = None,
    ) -> str:
        """DIRECT CALL — no fallback chain. Uses self.model only.

        The fallback chain was causing silent model switches that burned
        through free-tier quotas. This version calls ONLY the configured
        default model. If it fails, it raises the error directly so the
        user knows to wait or switch models manually with /model.
        """
        import litellm
        model = self.model
        try:
            response = litellm.completion(
                model=model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stream=True,
            )
            full = ""
            for chunk in response:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    full += delta
                    if on_token:
                        on_token(delta)
            self.total_output_tokens += len(full) // 4
            self.total_input_tokens += sum(len(m.get("content", "")) for m in messages) // 4
            return full
        except Exception as e:
            err_msg = str(e)[:500]
            console.print(f"[red]LLM error ({model}): {err_msg}[/red]")
            raise


    def reset_exhausted_models(self):
        """Clear the exhausted-models cache (useful after quota resets)."""
        self._exhausted_models.clear()
        LLMClient._save_exhausted(set())
        console.print("[green]Exhausted-models cache cleared (disk + memory).[/green]")

    def _stream_with_model(self, model: str, messages: list, on_token) -> str:
        """Internal: actual streaming call to a specific model."""
        response = litellm.completion(
            model=model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            stream=True,
        )
        full = ""
        for chunk in response:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                full += delta
                if on_token:
                    on_token(delta)
        self.total_output_tokens += len(full) // 4
        self.total_input_tokens += sum(len(m.get("content", "")) for m in messages) // 4
        return full

    def get_token_stats(self) -> dict:
        return {
            "input": self.total_input_tokens,
            "output": self.total_output_tokens,
            "total": self.total_input_tokens + self.total_output_tokens,
        }

    def reset_token_stats(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0

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
            console.print(f"[yellow]JSON parse failed: {e}[/yellow]")
            return {"error": "invalid_json", "raw": raw}
