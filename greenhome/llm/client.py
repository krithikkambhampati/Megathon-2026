"""LLM client adapters (BUILD_GUIDE P4.1, CR-7): Ollama + any OpenAI-compatible endpoint, plus a cache.

Both adapters stream over plain httpx so the caller's deadline is enforced on our side: we stop reading
when time is up and raise `LLMTimeout`. Every failure is an `LLMError`; callers turn it into the template
answer, so the app works with the LLM down (BUILD_GUIDE P4 hazard 3). Temperature 0 and seed 42 (BUILD_GUIDE L5).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

from greenhome.llm.settings import LLMSettings, get_llm_settings

log = logging.getLogger(__name__)


class LLMError(Exception):
    """The LLM could not give an answer: unreachable, HTTP error, malformed reply."""


TRUNCATED = "reply cut off at max_tokens"


class LLMTimeout(LLMError):
    """The call ran past its timeout (including mid-stream)."""


class LLMRateLimited(LLMError):
    """HTTP 429 from a hosted endpoint (Groq free tier: per-model requests/day and tokens/minute)."""

    def __init__(self, message: str, retry_after_s: float) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


_DURATION = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_UNIT_S = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
_DEFAULT_RETRY_S = 10.0


def _retry_after(headers: httpx.Headers) -> float:
    """Seconds to wait after a 429: `retry-after`, else Groq's `x-ratelimit-reset-*` ("764ms", "8m38.4s")."""
    raw = headers.get("retry-after")
    if raw:
        try:
            return max(float(raw), 0.0)
        except ValueError:
            pass
    waits = []
    for h in ("x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        parts = _DURATION.findall(headers.get(h, ""))
        if parts:
            waits.append(sum(float(n) * _UNIT_S[u] for n, u in parts))
    return min(waits) if waits else _DEFAULT_RETRY_S


@dataclass
class Usage:
    """Stats of the last generate() call, for the benchmark and the eval report."""

    seconds: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    load_seconds: float | None = None  # Ollama: time spent loading the model into memory
    reasoning_tokens: int | None = None  # hosted reasoning models (gpt-oss): hidden tokens inside completion
    cached: bool = False


class LLMClient(Protocol):
    name: str

    def generate(
        self,
        system: str,
        messages: list[dict],
        json_schema: dict | None = None,
        max_tokens: int = 400,
        *,
        timeout_s: float | None = None,
    ) -> str: ...

    def ping(self, timeout_s: float = 2) -> bool: ...


def _messages(system: str, messages: list[dict]) -> list[dict]:
    return [{"role": "system", "content": system}, *messages]


class _StreamingClient:
    """Shared streaming loop. Subclasses build the request and parse one stream line."""

    def __init__(self, settings: LLMSettings, http: httpx.Client | None = None) -> None:
        self.settings = settings
        self.http = http or httpx.Client()
        self.last_usage: Usage | None = None
        self._cooldown_until = 0.0  # after a 429: fail fast (→ template) instead of hammering the endpoint

    @property
    def name(self) -> str:
        return f"{self.settings.provider}:{self.settings.model}"

    # --- subclass hooks ---
    def _request(
        self, system: str, messages: list[dict], json_schema: dict | None, max_tokens: int
    ) -> tuple[str, dict, dict]:
        raise NotImplementedError

    def _parse_line(self, line: str) -> tuple[str, bool, dict]:
        """→ (text piece, done, usage fields). Raises LLMError on an error line or a reply cut at max_tokens
        (a truncated answer is never cached or shown)."""
        raise NotImplementedError

    # --- shared ---
    def generate(
        self,
        system: str,
        messages: list[dict],
        json_schema: dict | None = None,
        max_tokens: int = 400,
        *,
        timeout_s: float | None = None,
    ) -> str:
        timeout = self.settings.call_timeout_s if timeout_s is None else timeout_s
        if timeout <= 0:
            raise LLMTimeout("no time left for an LLM call")
        wait = self._cooldown_until - time.monotonic()
        if wait > 0:
            raise LLMRateLimited(f"rate limited, retry in {wait:.1f} s", wait)
        url, body, headers = self._request(system, messages, json_schema, max_tokens)
        start = time.monotonic()
        end = start + timeout
        # Read timeout covers the wait for the first token (prompt evaluation); the loop below enforces the
        # total. ponytail: a stream that stalls mid-answer can overrun by one read timeout; tokens normally
        # arrive every ~50 ms, so this is theoretical. Upgrade path: read in a worker thread.
        http_timeout = httpx.Timeout(timeout, connect=min(self.settings.connect_timeout_s, timeout))
        parts: list[str] = []
        usage: dict = {}
        try:
            with self.http.stream("POST", url, json=body, headers=headers, timeout=http_timeout) as r:
                if r.status_code == 429:
                    r.read()
                    wait = _retry_after(r.headers)
                    self._cooldown_until = time.monotonic() + wait
                    raise LLMRateLimited(f"HTTP 429, retry in {wait:.1f} s", wait)
                if r.status_code != 200:
                    r.read()
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
                for line in r.iter_lines():
                    if time.monotonic() > end:
                        raise LLMTimeout(f"answer took longer than {timeout:.1f} s")
                    if not line.strip():
                        continue
                    piece, done, u = self._parse_line(line)
                    parts.append(piece)
                    usage.update(u)
                    if done:
                        break
        except httpx.TimeoutException as e:
            raise LLMTimeout(str(e) or "timed out") from e
        except httpx.HTTPError as e:
            raise LLMError(f"{type(e).__name__}: {e}") from e
        self.last_usage = Usage(seconds=time.monotonic() - start, **usage)
        text = "".join(parts).strip()
        if not text:
            raise LLMError("empty reply")
        return text


class OllamaClient(_StreamingClient):
    """POST {base_url}/api/chat (Ollama ≥ 0.5 for JSON-schema `format`)."""

    def _request(self, system, messages, json_schema, max_tokens):
        s = self.settings
        body: dict[str, Any] = {
            "model": s.model,
            "messages": _messages(system, messages),
            "stream": True,
            "keep_alive": s.keep_alive,  # on EVERY request: one without it resets the unload timer to 5 min
            "options": {
                "temperature": s.temperature,
                "seed": s.seed,
                "num_ctx": s.num_ctx,
                "num_predict": max_tokens,
            },
        }
        if json_schema is not None:
            body["format"] = json_schema
        return f"{s.base_url.rstrip('/')}/api/chat", body, {}

    def _parse_line(self, line):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise LLMError(f"bad stream line: {line[:100]}") from e
        if "error" in obj:
            raise LLMError(str(obj["error"]))
        done = bool(obj.get("done"))
        usage = {}
        if done:
            if obj.get("done_reason") == "length":
                raise LLMError(TRUNCATED)
            load_ns = obj.get("load_duration")
            usage = {
                "prompt_tokens": obj.get("prompt_eval_count"),
                "completion_tokens": obj.get("eval_count"),
                "load_seconds": None if load_ns is None else load_ns / 1e9,
            }
        return (obj.get("message") or {}).get("content", ""), done, usage

    def ping(self, timeout_s: float = 2) -> bool:
        return self._tags(timeout_s) is not None

    def has_model(self, timeout_s: float | None = None) -> bool:
        names = self._tags(timeout_s) or []
        want = self.settings.model
        return want in names or (":" not in want and f"{want}:latest" in names)

    def _tags(self, timeout_s: float | None) -> list[str] | None:
        try:
            r = self.http.get(
                f"{self.settings.base_url.rstrip('/')}/api/tags",
                timeout=timeout_s or self.settings.connect_timeout_s,
            )
            r.raise_for_status()
            return [m.get("name", "") for m in r.json().get("models", [])]
        except (httpx.HTTPError, ValueError):
            return None

    def warm_up(self) -> float:
        """Load the model into memory: a 1-token request with the SAME options as real calls (a different
        num_ctx would make Ollama reload) and keep_alive. Returns seconds taken."""
        start = time.monotonic()
        try:
            self.generate(
                "",
                [{"role": "user", "content": "hi"}],
                max_tokens=self.settings.tokens("warmup", 1),
                timeout_s=self.settings.warmup_timeout_s,
            )
        except LLMError as e:
            # A 1-token reply is meant to stop at max_tokens: the model is loaded, which is all we want.
            if TRUNCATED not in str(e):
                raise
        return time.monotonic() - start

    def gpu_fraction(self) -> float | None:
        """Share of the loaded model that sits in VRAM (`/api/ps`); None if unknown or not loaded."""
        try:
            r = self.http.get(
                f"{self.settings.base_url.rstrip('/')}/api/ps", timeout=self.settings.connect_timeout_s
            )
            r.raise_for_status()
            for m in r.json().get("models", []):
                if m.get("name") == self.settings.model or m.get("model") == self.settings.model:
                    size = m.get("size") or 0
                    return (m.get("size_vram") or 0) / size if size else None
        except (httpx.HTTPError, ValueError):
            pass
        return None

    def unload(self) -> None:
        """Unload the model (keep_alive 0). Used by the bench between candidates."""
        try:
            self.http.post(
                f"{self.settings.base_url.rstrip('/')}/api/generate",
                json={"model": self.settings.model, "keep_alive": 0},
                timeout=self.settings.connect_timeout_s * 5,
            )
        except httpx.HTTPError:
            pass


class OpenAICompatClient(_StreamingClient):
    """POST {base_url}/chat/completions on any OpenAI-compatible endpoint (BUILD_GUIDE L5 hosted fallback).

    Plain httpx instead of the `openai` SDK so streaming and the deadline work the same as Ollama.
    """

    def _headers(self) -> dict:
        key = self.settings.api_key
        return {"Authorization": f"Bearer {key}"} if key else {}

    def _request(self, system, messages, json_schema, max_tokens):
        s = self.settings
        body: dict[str, Any] = {
            "model": s.model,
            "messages": _messages(system, messages),
            "temperature": s.temperature,
            "seed": s.seed,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            **s.extra_for(),  # e.g. gpt-oss: reasoning_effort low, reasoning hidden (config/llm.yaml)
        }
        if json_schema is not None:  # strict off: discriminated unions are rejected by strict mode
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": json_schema, "strict": False},
            }
        return f"{s.base_url.rstrip('/')}/chat/completions", body, self._headers()

    def _parse_line(self, line):
        if not line.startswith("data:"):
            return "", False, {}
        data = line[5:].strip()
        if data == "[DONE]":
            return "", True, {}
        try:
            obj = json.loads(data)
        except json.JSONDecodeError as e:
            raise LLMError(f"bad stream line: {line[:100]}") from e
        if "error" in obj:
            raise LLMError(str(obj["error"]))
        usage = {}
        u = obj.get("usage") or (obj.get("x_groq") or {}).get("usage")  # Groq may nest it under x_groq
        if u:
            usage = {
                "prompt_tokens": u.get("prompt_tokens"),
                "completion_tokens": u.get("completion_tokens"),
                "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            }
        choices = obj.get("choices") or [{}]
        if choices[0].get("finish_reason") == "length":
            raise LLMError(TRUNCATED)
        return (choices[0].get("delta") or {}).get("content") or "", False, usage

    def ping(self, timeout_s: float = 2) -> bool:
        try:
            r = self.http.get(
                f"{self.settings.base_url.rstrip('/')}/models",
                headers=self._headers(),
                timeout=timeout_s or self.settings.connect_timeout_s,
            )
            if r.status_code in (401, 403):
                log.warning(
                    "LLM API key rejected by %s (HTTP %s): check LLM_API_KEY",
                    self.settings.base_url,
                    r.status_code,
                )
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def has_model(self, timeout_s: float | None = None) -> bool:
        """The model is listed by GET /models. If the list can't be read, trust the first request instead."""
        try:
            r = self.http.get(
                f"{self.settings.base_url.rstrip('/')}/models",
                headers=self._headers(),
                timeout=timeout_s or self.settings.connect_timeout_s,
            )
            r.raise_for_status()
            ids = [m.get("id") for m in r.json().get("data", [])]
        except (httpx.HTTPError, ValueError, AttributeError):
            return True
        return not ids or self.settings.model in ids

    def warm_up(self) -> float:
        """Nothing to load on a hosted endpoint: one tiny real answer checks key, model and request fields
        (a 1-token reply would be cut by a reasoning model's hidden tokens)."""
        start = time.monotonic()
        try:
            self.generate(
                "Reply with one word.",
                [{"role": "user", "content": "ping"}],
                max_tokens=self.settings.tokens("warmup_hosted", 128),
                timeout_s=self.settings.warmup_timeout_s,
            )
        except LLMError as e:
            # Cut at max_tokens still proves key, model and request fields work, which is all we want.
            if TRUNCATED not in str(e):
                raise
        return time.monotonic() - start


class CachedClient:
    """In-memory LRU over identical requests (BUILD_GUIDE P4.1). Failures are not cached.

    Temperature 0 + fixed seed make a repeated request return the same text, so caching changes nothing
    but latency. The timeout is not part of the key: it changes when an answer arrives, not what it says.
    """

    def __init__(self, inner: Any, max_entries: int = 1024) -> None:
        self.inner = inner
        self.max_entries = max_entries
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.Lock()  # FastAPI runs sync routes in a thread pool
        self.last_usage: Usage | None = None
        self._ping: tuple[float, bool] | None = None  # (monotonic time, result)

    @property
    def name(self) -> str:
        return self.inner.name

    @staticmethod
    def key(name: str, system: str, messages: list[dict], json_schema: dict | None, max_tokens: int) -> str:
        blob = json.dumps(
            [name, system, messages, json_schema, max_tokens], sort_keys=True, ensure_ascii=False
        )
        return hashlib.sha256(blob.encode()).hexdigest()

    def generate(
        self,
        system: str,
        messages: list[dict],
        json_schema: dict | None = None,
        max_tokens: int = 400,
        *,
        timeout_s: float | None = None,
    ) -> str:
        k = self.key(self.name, system, messages, json_schema, max_tokens)
        with self._lock:
            if k in self._cache:
                self._cache.move_to_end(k)
                self.last_usage = Usage(seconds=0.0, cached=True)
                return self._cache[k]
        text = self.inner.generate(system, messages, json_schema, max_tokens, timeout_s=timeout_s)
        with self._lock:
            self.last_usage = getattr(self.inner, "last_usage", None)
            self._cache[k] = text
            if len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)
        return text

    def ping(self, timeout_s: float = 2) -> bool:
        """Cached for `ping_cache_s` (health is polled on every UI rerun; a hosted ping is a network call)."""
        ttl = getattr(getattr(self.inner, "settings", None), "ping_cache_s", 0.0)
        now = time.monotonic()
        if self._ping is not None and now - self._ping[0] < ttl:
            return self._ping[1]
        ping = getattr(self.inner, "ping", None)
        ok = bool(ping and ping(timeout_s))
        self._ping = (now, ok)
        return ok


class FailoverClient:
    """Tries each client in order while the earlier ones are rate limited (Groq quotas are per model).

    Any other error is raised at once: it is not a quota problem, so another model would not help.
    """

    def __init__(self, clients: list[Any]) -> None:
        self.clients = clients
        self.settings = clients[0].settings
        self.last_usage: Usage | None = None

    @property
    def name(self) -> str:
        return self.clients[0].name

    def generate(
        self,
        system: str,
        messages: list[dict],
        json_schema: dict | None = None,
        max_tokens: int = 400,
        *,
        timeout_s: float | None = None,
    ) -> str:
        for i, c in enumerate(self.clients):
            try:
                text = c.generate(system, messages, json_schema, max_tokens, timeout_s=timeout_s)
            except LLMRateLimited:
                if i == len(self.clients) - 1:
                    raise
                log.info("LLM %s rate limited; trying %s", c.name, self.clients[i + 1].name)
                continue
            self.last_usage = c.last_usage
            return text
        raise LLMError("no LLM clients")

    def ping(self, timeout_s: float = 2) -> bool:
        return self.clients[0].ping(timeout_s)

    def warm_up(self) -> float:
        return self.clients[0].warm_up()


_ADAPTERS = {"ollama": OllamaClient, "openai_compat": OpenAICompatClient}


def _warm_up(inner: Any) -> None:
    """Background warm-up: load the model, then report whether it fits on the GPU."""
    try:
        log.info("LLM %s warmed up in %.1f s", inner.name, inner.warm_up())
    except LLMError as e:
        log.warning("LLM warm-up failed (%s); first answers may use templates", e)
        return
    frac = getattr(inner, "gpu_fraction", lambda: None)()
    if frac is not None and frac < 0.999:
        log.warning(
            "LLM %s is only %.0f%% on the GPU: answers will be slow (try a smaller model)",
            inner.name,
            100 * frac,
        )


def make_client(
    settings: LLMSettings | None = None,
    http: httpx.Client | None = None,
    *,
    warm_up: Literal["background", "blocking", "off"] = "background",
) -> LLMClient | None:
    """CR-7. None when the LLM is not configured, unreachable or the model is missing. Never raises.

    The model is warmed up in a background thread by default, so API start-up isn't blocked; an early
    question simply waits for the load (or falls back to the template if the budget runs out).
    """
    try:
        s = settings or get_llm_settings()
        if not s.enabled:
            log.info("LLM off: provider=%s model=%s (set LLM_PROVIDER and pin a model)", s.provider, s.model)
            return None
        inner = _ADAPTERS[s.provider](s, http)
        if not inner.ping(s.connect_timeout_s):
            log.warning("LLM off: %s not reachable at %s", s.provider, s.base_url)
            return None
        if not inner.has_model():
            if s.provider == "ollama":
                log.warning("LLM off: model %r is not pulled. Run: ollama pull %s", s.model, s.model)
            else:
                log.warning("LLM off: %r is not listed at %s/models (check LLM_MODEL)", s.model, s.base_url)
            return None
        log.info("LLM on: %s at %s", inner.name, s.base_url)
        if warm_up == "blocking":
            _warm_up(inner)
        elif warm_up == "background":
            threading.Thread(target=_warm_up, args=(inner,), name="llm-warmup", daemon=True).start()
        if s.provider == "openai_compat" and s.fallback_models:
            backups = [
                OpenAICompatClient(s.model_copy(update={"model": m}), inner.http) for m in s.fallback_models
            ]
            return CachedClient(FailoverClient([inner, *backups]), s.cache_max_entries)
        return CachedClient(inner, s.cache_max_entries)
    except Exception:
        log.exception("LLM client failed to start; running without an LLM")
        return None
