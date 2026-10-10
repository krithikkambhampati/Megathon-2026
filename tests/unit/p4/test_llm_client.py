from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

import greenhome.llm.client as client_mod
from greenhome.llm.client import (
    CachedClient,
    LLMError,
    LLMTimeout,
    OllamaClient,
    OpenAICompatClient,
    make_client,
)
from greenhome.llm.fake import FakeClock, ScriptedClient
from greenhome.llm.settings import LLMSettings

SCHEMA = {"type": "object", "properties": {"mode": {"type": "string"}}}


def _settings(provider: str = "ollama", **kw) -> LLMSettings:
    return LLMSettings(provider=provider, model="m:1", base_url="http://llm.test", **kw)


def _ollama_lines(*pieces: str, prompt: int = 11, completion: int = 7) -> bytes:
    lines = [json.dumps({"message": {"content": p}, "done": False}) for p in pieces]
    lines.append(
        json.dumps(
            {"message": {"content": ""}, "done": True, "prompt_eval_count": prompt, "eval_count": completion}
        )
    )
    return ("\n".join(lines) + "\n").encode()


def _http(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------- Ollama ----------
def test_ollama_request_body_is_deterministic_and_keeps_model_loaded() -> None:
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=_ollama_lines("ok"))

    c = OllamaClient(_settings(), _http(handler))
    c.generate("SYS", [{"role": "user", "content": "hi"}], json_schema=SCHEMA, max_tokens=123)
    body = seen["body"]
    assert seen["url"] == "http://llm.test/api/chat"
    assert body["model"] == "m:1" and body["stream"] is True and body["keep_alive"] == "2h"
    assert body["options"] == {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 123}
    assert body["format"] == SCHEMA
    assert body["messages"][0] == {"role": "system", "content": "SYS"}


def test_ollama_omits_format_without_schema() -> None:
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=_ollama_lines("ok"))

    OllamaClient(_settings(), _http(handler)).generate("s", [])
    assert "format" not in seen["body"]


def test_ollama_stream_is_joined_and_usage_recorded() -> None:
    c = OllamaClient(_settings(), _http(lambda r: httpx.Response(200, content=_ollama_lines("Hel", "lo "))))
    assert c.generate("s", []) == "Hello"
    assert c.last_usage.prompt_tokens == 11 and c.last_usage.completion_tokens == 7


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="boom"),
        httpx.Response(
            200, content=b'{"message": {"content": "cut"}, "done": true, "done_reason": "length"}\n'
        ),
        httpx.Response(200, content=b'{"error": "model not found"}\n'),
        httpx.Response(200, content=_ollama_lines()),  # empty reply
        httpx.Response(200, content=b"not json\n"),
    ],
)
def test_ollama_bad_replies_raise_llm_error(response) -> None:
    with pytest.raises(LLMError):
        OllamaClient(_settings(), _http(lambda r: response)).generate("s", [])


def test_connection_error_is_llm_error_and_read_timeout_is_llm_timeout() -> None:
    def refuse(req):
        raise httpx.ConnectError("refused")

    def slow(req):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(LLMError):
        OllamaClient(_settings(), _http(refuse)).generate("s", [])
    with pytest.raises(LLMTimeout):
        OllamaClient(_settings(), _http(slow)).generate("s", [])


def test_deadline_is_enforced_mid_stream(monkeypatch) -> None:
    clock = FakeClock()
    monkeypatch.setattr(client_mod, "time", SimpleNamespace(monotonic=clock))

    def body():
        yield json.dumps({"message": {"content": "a"}, "done": False}).encode() + b"\n"
        clock.advance(6)  # the model is slow: past the 5 s timeout
        yield json.dumps({"message": {"content": "b"}, "done": False}).encode() + b"\n"
        yield json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n"

    c = OllamaClient(_settings(), _http(lambda r: httpx.Response(200, content=body())))
    with pytest.raises(LLMTimeout):
        c.generate("s", [], timeout_s=5)


def test_no_time_left_skips_the_http_call() -> None:
    def handler(req):
        raise AssertionError("must not call")

    with pytest.raises(LLMTimeout):
        OllamaClient(_settings(), _http(handler)).generate("s", [], timeout_s=0)


def test_has_model_matches_exact_tag_and_latest() -> None:
    tags = httpx.Response(200, json={"models": [{"name": "m:1"}, {"name": "other:latest"}]})
    assert OllamaClient(_settings(), _http(lambda r: tags)).has_model()
    s = LLMSettings(provider="ollama", model="other", base_url="http://llm.test")
    assert OllamaClient(s, _http(lambda r: tags)).has_model()
    s = LLMSettings(provider="ollama", model="missing:1", base_url="http://llm.test")
    assert not OllamaClient(s, _http(lambda r: tags)).has_model()


# ---------- OpenAI-compatible ----------
def _sse(*pieces: str) -> bytes:
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}" for p in pieces]
    lines.append(
        f"data: {json.dumps({'choices': [], 'usage': {'prompt_tokens': 3, 'completion_tokens': 2}})}"
    )
    lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode()


def test_openai_compat_request_and_stream() -> None:
    seen = {}

    def handler(req):
        seen["url"], seen["auth"] = str(req.url), req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=_sse("Hi", " there"))

    c = OpenAICompatClient(_settings("openai_compat", api_key="sk-test"), _http(handler))
    assert c.generate("S", [], json_schema=SCHEMA, max_tokens=50) == "Hi there"
    b = seen["body"]
    assert seen["url"] == "http://llm.test/chat/completions" and seen["auth"] == "Bearer sk-test"
    assert (b["temperature"], b["seed"], b["max_tokens"], b["stream"]) == (0, 42, 50, True)
    assert b["response_format"]["json_schema"]["schema"] == SCHEMA
    assert c.last_usage.prompt_tokens == 3


def test_openai_compat_cut_off_reply_is_an_error() -> None:
    line = f"data: {json.dumps({'choices': [{'delta': {'content': 'x'}, 'finish_reason': 'length'}]})}\n\n"
    c = OpenAICompatClient(
        _settings("openai_compat"), _http(lambda r: httpx.Response(200, content=line.encode()))
    )
    with pytest.raises(LLMError):
        c.generate("s", [])


def test_gpu_fraction_reads_api_ps() -> None:
    ps = httpx.Response(200, json={"models": [{"name": "m:1", "size": 100, "size_vram": 80}]})
    assert OllamaClient(_settings(), _http(lambda r: ps)).gpu_fraction() == 0.8


# ---------- Cache ----------
def test_cache_hits_identical_requests_only() -> None:
    fake = ScriptedClient(["one", "two", "three"])
    c = CachedClient(fake)
    assert c.generate("s", [{"role": "user", "content": "q"}]) == "one"
    assert c.generate("s", [{"role": "user", "content": "q"}], timeout_s=3) == "one"  # timeout not in key
    assert c.last_usage.cached
    assert c.generate("s", [{"role": "user", "content": "q"}], max_tokens=10) == "two"
    assert c.generate("s", [{"role": "user", "content": "q"}], json_schema=SCHEMA) == "three"
    assert len(fake.calls) == 3


def test_cache_does_not_store_failures_and_evicts_lru() -> None:
    fake = ScriptedClient([LLMError("down"), "ok", "a", "b", "a2"])
    c = CachedClient(fake, max_entries=2)
    with pytest.raises(LLMError):
        c.generate("s", [])
    assert c.generate("s", []) == "ok"  # the failure was not cached
    c.generate("a", [])
    c.generate("b", [])  # evicts "s" (least recently used)
    assert c.generate("a", []) == "a"  # still cached
    assert c.generate("s", []) == "a2"  # re-fetched
    assert c.name == "fake:scripted"


# ---------- make_client ----------
def _never(req):
    raise AssertionError("no HTTP call expected")


def test_make_client_off_when_not_configured() -> None:
    assert make_client(LLMSettings(), _http(_never)) is None
    assert make_client(LLMSettings(provider="ollama"), _http(_never)) is None  # model not pinned


def test_make_client_none_when_unreachable_or_model_missing() -> None:
    def refuse(req):
        raise httpx.ConnectError("refused")

    assert make_client(_settings(), _http(refuse)) is None
    tags = httpx.Response(200, json={"models": [{"name": "something-else:1"}]})
    assert make_client(_settings(), _http(lambda r: tags)) is None


def test_make_client_warms_the_model_and_returns_cached_client() -> None:
    warm = {}

    def handler(req):
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "m:1"}]})
        warm["body"] = json.loads(req.content)
        return httpx.Response(200, content=_ollama_lines("."))

    c = make_client(_settings(), _http(handler), warm_up="blocking")
    assert isinstance(c, CachedClient) and bool(c)  # P5 checks `if app.state.llm`
    body = warm["body"]
    assert body["keep_alive"] == "2h" and body["options"]["num_predict"] == 1
    assert body["options"]["num_ctx"] == _settings().num_ctx  # same options as real calls: no reload


def test_make_client_survives_a_failed_warm_up() -> None:
    def handler(req):
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "m:1"}]})
        raise httpx.ReadTimeout("cold load too slow")

    assert make_client(_settings(), _http(handler), warm_up="blocking") is not None


def test_make_client_never_raises(monkeypatch) -> None:
    def boom():
        raise RuntimeError("bad config")

    monkeypatch.setattr(client_mod, "get_llm_settings", boom)
    assert make_client() is None
