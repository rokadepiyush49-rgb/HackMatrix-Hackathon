"""Groq chat completions for the Investigation Council — the only module that talks to Groq.

Groq serves an OpenAI-compatible API. This client uses the standard library (no extra dependency) and:

  • keeps the key in the Authorization header only — never in logs, errors, traces or API responses;
  • retries only what is worth retrying (429 after `retry-after`, 5xx, timeouts, network), a bounded number
    of times, and never past the caller's deadline;
  • classifies every failure (`LLMError.kind`) so the harness can fall back instead of guessing;
  • asks for strict JSON-schema output on models that support it, plain JSON mode elsewhere.

Model facts below were checked on console.groq.com/docs/models, /docs/structured-outputs and
/docs/reasoning on 10 Oct 2026. `GROQ_CONTEXT_WINDOW` overrides the window for any other model.
"""

from __future__ import annotations

import json
import logging
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

log = logging.getLogger("sutra.council.llm")

MODEL_LIMITS: dict[str, dict] = {
    # context window, max completion tokens, strict json_schema support, reasoning parameters
    "openai/gpt-oss-120b": {"context": 131_072, "max_completion": 65_536, "strict": True, "reasoning": "gpt-oss"},
    "openai/gpt-oss-20b": {"context": 131_072, "max_completion": 65_536, "strict": True, "reasoning": "gpt-oss"},
    "qwen/qwen3.8-27b": {"context": 131_072, "max_completion": 16_384, "strict": True, "reasoning": "qwen"},
    "llama-3.3-70b-versatile": {"context": 131_072, "max_completion": 32_768, "strict": False, "reasoning": None},
    "llama-3.1-8b-instant": {"context": 131_072, "max_completion": 131_072, "strict": False, "reasoning": None},
}
UNKNOWN_MODEL_CONTEXT = 32_768  # conservative when neither the table nor GROQ_CONTEXT_WINDOW knows the model
MAX_RATE_LIMIT_WAIT_S = 60.0

# (url, body or None for GET, headers, timeout) -> (status, headers, body)
Transport = Callable[[str, bytes | None, dict[str, str], float], tuple[int, dict[str, str], bytes]]


def urllib_transport(url: str, body: bytes | None, headers: dict[str, str], timeout: float) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — fixed https base URL from settings
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read() or b""


class LLMError(Exception):
    """A classified failure. `kind` decides what the harness does; the message never holds secrets or content."""

    RETRYABLE = frozenset({"rate_limit", "server", "timeout", "network"})

    def __init__(self, kind: str, message: str, status: int | None = None, attempts: int = 0):
        super().__init__(message)
        self.kind, self.status, self.attempts = kind, status, attempts

    @property
    def retryable(self) -> bool:
        return self.kind in self.RETRYABLE


@dataclass
class Completion:
    text: str
    model: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    attempts: int
    latency_ms: int
    request_id: str | None = None
    ratelimit: dict = field(default_factory=dict)


def _error_detail(body: bytes) -> tuple[str, str]:
    """Groq's error type/code and a short message — trimmed, never the request."""
    try:
        err = json.loads(body or b"{}").get("error", {}) or {}
    except (ValueError, AttributeError):
        return "", ""
    return str(err.get("code") or err.get("type") or ""), str(err.get("message") or "")[:200]


class GroqClient:
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.groq.com/openai/v1",
                 timeout_s: float = 30.0, max_retries: int = 2, reasoning_effort: str = "",
                 context_window: int = 0, transport: Transport | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        if not api_key:
            raise LLMError("config", "GROQ_API_KEY is not set")
        if not model:
            raise LLMError("config", "GROQ_MODEL is not set")
        if not base_url.startswith("https://") and not base_url.startswith("http://127.0.0.1"):
            raise LLMError("config", "GROQ_BASE_URL must be https")
        self._key = api_key
        self.model, self.base_url = model, base_url.rstrip("/")
        self.timeout_s, self.max_retries, self.reasoning_effort = timeout_s, max_retries, reasoning_effort
        self._transport, self._sleep, self._clock = transport or urllib_transport, sleep, clock
        self.facts = MODEL_LIMITS.get(model, {})
        self.context_window = context_window or self.facts.get("context", UNKNOWN_MODEL_CONTEXT)

    def __repr__(self) -> str:  # never show the key
        return f"GroqClient(model={self.model!r}, base_url={self.base_url!r})"

    @property
    def strict_schema(self) -> bool:
        return bool(self.facts.get("strict"))

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json",
                "User-Agent": "sutra-council/1.0"}

    def check(self) -> dict:
        """Is the key accepted and the configured model served? (GET /models — costs no tokens.)"""
        try:
            status, _h, body = self._transport(f"{self.base_url}/models", None, self._headers(), self.timeout_s)
        except TimeoutError:
            return {"ok": False, "kind": "timeout", "detail": "Groq did not answer in time"}
        except (urllib.error.URLError, OSError) as e:
            return {"ok": False, "kind": "network", "detail": type(e).__name__}
        if status in (401, 403):
            return {"ok": False, "kind": "auth", "detail": "Groq refused the API key"}
        if status != 200:
            return {"ok": False, "kind": "server", "detail": f"HTTP {status}"}
        try:
            ids = {m.get("id") for m in json.loads(body).get("data", [])}
        except (ValueError, AttributeError):
            return {"ok": False, "kind": "malformed", "detail": "unreadable model list"}
        listed = self.model in ids
        return {"ok": listed, "kind": None if listed else "config", "model": self.model, "model_listed": listed,
                "detail": "model available" if listed else f"{self.model} is not offered to this key"}

    def chat(self, messages: list[dict], *, schema: dict | None = None, schema_name: str = "output",
             max_completion_tokens: int = 2048, deadline: float | None = None, temperature: float = 0.2) -> Completion:
        body: dict = {"model": self.model, "messages": messages, "max_completion_tokens": max_completion_tokens,
                      "temperature": temperature}
        if schema is not None:
            body["response_format"] = ({"type": "json_schema", "json_schema": {"name": schema_name, "strict": True,
                                                                               "schema": schema}}
                                       if self.strict_schema else {"type": "json_object"})
        flavour = self.facts.get("reasoning")
        if flavour == "gpt-oss":
            body["include_reasoning"] = False
            if self.reasoning_effort:
                body["reasoning_effort"] = self.reasoning_effort
        elif flavour == "qwen":
            body["reasoning_format"] = "hidden"
        payload = json.dumps(body).encode()
        url = f"{self.base_url}/chat/completions"
        attempt, t_start = 0, self._clock()
        while True:
            attempt += 1
            timeout = self.timeout_s
            if deadline is not None:
                left = deadline - self._clock()
                if left <= 1:
                    raise LLMError("timeout", "investigation deadline reached before the call", attempts=attempt - 1)
                timeout = min(timeout, left)
            t0 = self._clock()
            try:
                status, headers, raw = self._transport(url, payload, self._headers(), timeout)
            except TimeoutError:
                err = LLMError("timeout", f"no answer within {timeout:.0f}s", attempts=attempt)
                status, headers, raw = None, {}, b""
            except (urllib.error.URLError, OSError) as e:
                err = LLMError("network", f"network error ({type(e).__name__})", attempts=attempt)
                status, headers, raw = None, {}, b""
            else:
                err = None
            ms = int((self._clock() - t0) * 1000)
            if err is None and status == 200:
                return self._parse(raw, headers, attempt, int((self._clock() - t_start) * 1000))
            if err is None:
                code, msg = _error_detail(raw)
                if status == 429:
                    err = LLMError("rate_limit", "Groq rate limit reached", status, attempt)
                elif status in (401, 403):
                    err = LLMError("auth", "Groq refused the API key", status, attempt)
                elif status == 404:
                    err = LLMError("config", f"model {self.model} not found", status, attempt)
                elif status == 400 and code == "json_validate_failed":
                    err = LLMError("malformed", "output did not match the schema", status, attempt)
                elif status >= 500:
                    err = LLMError("server", f"Groq server error {status}", status, attempt)
                else:
                    err = LLMError("bad_request", f"HTTP {status} {code}: {msg}".strip(), status, attempt)
            log.warning("groq.call.failed model=%s kind=%s status=%s attempt=%s ms=%s", self.model, err.kind, status,
                        attempt, ms)
            if not err.retryable or attempt > self.max_retries:
                err.attempts = attempt
                raise err
            wait = self._backoff(err, headers, attempt)
            if deadline is not None and self._clock() + wait >= deadline - 1:
                err.attempts = attempt
                raise err
            self._sleep(wait)

    def _backoff(self, err: LLMError, headers: dict, attempt: int) -> float:
        if err.kind == "rate_limit":
            try:
                return min(float(headers.get("retry-after", "2")), MAX_RATE_LIMIT_WAIT_S)
            except ValueError:
                return 2.0
        return min(8.0, 2 ** (attempt - 1)) + random.uniform(0, 0.25)

    def _parse(self, raw: bytes, headers: dict, attempts: int, ms: int) -> Completion:
        try:
            data = json.loads(raw)
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
            finish = choice.get("finish_reason") or ""
            usage = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LLMError("malformed", f"unreadable completion ({type(e).__name__})", 200, attempts) from None
        if finish == "length":
            raise LLMError("truncated", "completion hit max_completion_tokens", 200, attempts)
        if not text.strip():
            raise LLMError("malformed", "empty completion", 200, attempts)
        rl = {k: headers.get(f"x-ratelimit-{k}") for k in ("remaining-tokens", "reset-tokens", "remaining-requests")
              if headers.get(f"x-ratelimit-{k}") is not None}
        c = Completion(text, data.get("model", self.model), finish, int(usage.get("prompt_tokens") or 0),
                       int(usage.get("completion_tokens") or 0), attempts, ms, headers.get("x-request-id"), rl)
        log.info("groq.call model=%s finish=%s prompt_tokens=%s completion_tokens=%s attempts=%s ms=%s",
                 c.model, finish, c.prompt_tokens, c.completion_tokens, attempts, ms)
        return c


def client_from_settings(transport: Transport | None = None) -> GroqClient | None:
    """The configured client, or None when the council should not call an LLM."""
    from app.core.config import get_settings

    s = get_settings()
    if s.council_engine == "deterministic" or not s.groq_api_key:
        return None
    return GroqClient(s.groq_api_key, s.groq_model, s.groq_base_url, s.groq_timeout_s, s.groq_max_retries,
                      s.groq_reasoning_effort, s.groq_context_window, transport)
