"""Model clients: Ollama and OpenAI-compatible local servers (llama.cpp, LM Studio)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass




class LLMError(RuntimeError):
    pass


def _get_json(url: str, timeout: float = 5.0) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise LLMError(f"{url}: HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise LLMError(f"cannot reach {url} ({getattr(e, 'reason', e)})") from None


class _HTTPFailure(Exception):
    def __init__(self, code: int, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def _post_json(url: str, body: dict, timeout: float) -> dict:
    """POST JSON, return JSON. HTTP errors -> _HTTPFailure (the caller words them); no connection -> OSError."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise _HTTPFailure(e.code, e.read().decode("utf-8", "replace")[:300]) from None


_UNREACHABLE = (urllib.error.URLError, TimeoutError, ConnectionError)
MAX_TOKENS = 400  # one LogicSpec answer; UDTs ask for more


BACKENDS = {
    "ollama": {"label": "Ollama", "url": "http://127.0.0.1:11434"},
    "llamacpp": {"label": "llama.cpp server (GGUF, grammar-constrained)", "url": "http://127.0.0.1:8080"},
    "openai": {"label": "OpenAI-compatible (LM Studio, Jan, vLLM...)", "url": "http://127.0.0.1:1234"},
}


@dataclass
class OllamaClient:
    model: str = "phi4-mini"
    url: str = "http://127.0.0.1:11434"
    timeout: float = 300.0  # CPU-only machines can be slow
    think: bool | None = None  # None = model default; False = ask thinking models not to think
    context: int = 16384  # Ollama's own default (2048-4096) can cut a prompt with a project's tags
    supports_grammar = False  # Ollama only constrains to JSON schemas

    def list_models(self) -> list[str]:
        data = _get_json(f"{self.url.rstrip('/')}/api/tags")
        return sorted(m.get("name") or m.get("model") for m in data.get("models", []))

    def chat(self, messages: list[dict], grammar: str | None = None, max_tokens: int = MAX_TOKENS) -> str:
        body = {"model": self.model, "messages": messages, "stream": False,
                "options": {"temperature": 0, "num_predict": max_tokens, "num_ctx": self.context}}
        if self.think is not None:
            body["think"] = self.think
        try:
            data = _post_json(f"{self.url.rstrip('/')}/api/chat", body, self.timeout)
        except _HTTPFailure as e:
            if e.code == 404 and "not found" in e.detail:
                raise LLMError(f"Ollama has no model '{self.model}'. Run: ollama pull {self.model}") from None
            raise LLMError(f"Ollama error {e.code}: {e.detail}") from None
        except _UNREACHABLE as e:
            raise LLMError(f"Cannot reach Ollama at {self.url} ({e}). Is Ollama running?") from None
        return (data.get("message") or {}).get("content", "")


@dataclass
class OpenAICompatClient:
    """Any local server with the OpenAI chat API: llama.cpp's llama-server, LM Studio, Jan, vLLM.

    With grammar=True (llama-server) each request carries a GBNF grammar, so the
    reply is guaranteed to be valid LogicSpec over the allowed tags.
    """
    model: str = ""
    url: str = "http://127.0.0.1:8080"
    timeout: float = 300.0
    grammar: bool = False
    think: bool | None = None  # False: ask the chat template not to think (Qwen3 & co.)

    @property
    def supports_grammar(self) -> bool:
        return self.grammar

    def list_models(self) -> list[str]:
        data = _get_json(f"{self.url.rstrip('/')}/v1/models")
        return sorted(m.get("id", "") for m in data.get("data", []) if m.get("id"))

    def chat(self, messages: list[dict], grammar: str | None = None, max_tokens: int = MAX_TOKENS) -> str:
        body = {"messages": messages, "temperature": 0, "max_tokens": max_tokens, "stream": False}
        if self.model:
            body["model"] = self.model
        if grammar and self.grammar:
            body["grammar"] = grammar
        if self.think is False:
            # Qwen-style templates: skip the <think> block in the prompt itself, so the
            # server does not have to force-close it (forced tokens and grammars clash)
            body["chat_template_kwargs"] = {"enable_thinking": False}
        try:
            data = _post_json(f"{self.url.rstrip('/')}/v1/chat/completions", body, self.timeout)
        except _HTTPFailure as e:
            if grammar and e.code in (400, 500) and "grammar" in e.detail.lower():
                raise LLMError(f"the server rejected the grammar: {e.detail}") from None
            raise LLMError(f"server error {e.code}: {e.detail}") from None
        except _UNREACHABLE as e:
            raise LLMError(f"Cannot reach the model server at {self.url} ({e}). Is it running?") from None
        choices = data.get("choices") or [{}]
        return (choices[0].get("message") or {}).get("content", "") or ""


def make_client(backend: str = "ollama", url: str | None = None, model: str = "", think: bool | None = None,
                context: int = 16384):
    """context: tokens the model may see (Ollama only; llama.cpp fixes it with -c at server start)."""
    backend = backend if backend in BACKENDS else "ollama"
    url = url or BACKENDS[backend]["url"]
    if backend == "ollama":
        return OllamaClient(model=model or "phi4-mini", url=url, think=think, context=context)
    if backend == "llamacpp" and think is None:
        think = False  # the grammar allows no thinking text, and forced think tags break it
    return OpenAICompatClient(model=model, url=url, grammar=(backend == "llamacpp"), think=think)


# ---------------------------------------------------------------- prompt pieces
