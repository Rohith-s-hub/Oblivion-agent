import os
import json
from dotenv import load_dotenv
import litellm
from rich.console import Console

load_dotenv()

console = Console()

os.environ["OLLAMA_API_BASE"] = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
litellm.set_verbose = False


class LLMClient:
    def __init__(self):
        self.model = os.getenv("DEFAULT_MODEL", "ollama/qwen3-coder:480b-cloud")
        self.max_tokens = int(os.getenv("MAX_TOKENS", "4096"))
        self.temperature = float(os.getenv("TEMPERATURE", "0.1"))

    def chat(self, messages: list, stream: bool = True) -> str:
        try:
            response = litellm.completion(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stream=stream,
            )
            if stream:
                full_response = ""
                for chunk in response:
                    delta = chunk.choices[0].delta.content or ""
                    full_response += delta
                    print(delta, end="", flush=True)
                print()
                return full_response
            else:
                return response.choices[0].message.content
        except Exception as e:
            console.print(f"[red]LLM Error: {e}[/red]")
            raise

    def chat_json(self, messages: list) -> dict:
        json_messages = messages + [{
            "role": "system",
            "content": "Respond with ONLY valid JSON. No markdown, no explanation."
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
