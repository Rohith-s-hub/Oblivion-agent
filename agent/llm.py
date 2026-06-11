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

    FALLBACK_MODEL = "ollama/qwen3-coder:480b-cloud"

    def chat_stream(
        self,
        messages: list,
        on_token: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Streaming chat with callback (used by TUI).
        Auto-falls back to qwen-coder on rate limit / context errors.
        """
        primary_model = self.model
        try:
            return self._stream_with_model(primary_model, messages, on_token)
        except Exception as e:
            error_msg = str(e).lower()
            # Decide if we should fallback
            fallback_triggers = [
                "ratelimiterror", "rate_limit", "rate limit",
                "request too large", "context length", "context_length_exceeded",
                "tokens per minute", "tpm", "model is overloaded",
                "service unavailable", "503",
            ]
            should_fallback = any(t in error_msg for t in fallback_triggers)

            if should_fallback and primary_model != self.FALLBACK_MODEL:
                console.print(
                    f"[yellow]⚠ {primary_model} failed ({type(e).__name__}). "
                    f"Falling back to qwen-coder...[/yellow]"
                )
                if on_token:
                    on_token(f"\n[yellow]⚠ Fallback to qwen-coder due to: {type(e).__name__}[/yellow]\n")
                try:
                    return self._stream_with_model(self.FALLBACK_MODEL, messages, on_token)
                except Exception as fallback_err:
                    console.print(f"[red]Fallback also failed: {fallback_err}[/red]")
                    raise
            # Not a fallback-able error, or already on fallback model
            console.print(f"[red]LLM Error: {e}[/red]")
            raise

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
