from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

import greenhome.llm.client as client_mod
from greenhome.llm.client import (
    CachedClient,
    LLMError,
    LLMRateLimited,
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


def test_openai_compat_sends_model_extras_and_reads_groq_usage() -> None:
    seen = {}
    usage = {
        "prompt_tokens": 9,
        "completion_tokens": 40,
        "completion_tokens_details": {"reasoning_tokens": 30},
    }
    last = {"choices": [{"delta": {}, "finish_reason": "stop"}], "x_groq": {"usage": usage}}
    body = (
        f"data: {json.dumps({'choices': [{'delta': {'content': 'ok'}}]})}\n\n"
        f"data: {json.dumps(last)}\n\ndata: [DONE]\n\n"
    )

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=body.encode())

    s = _settings(
        "openai_compat", request_extra={"m:": {"reasoning_effort": "low", "include_reasoning": False}}
    )
    c = OpenAICompatClient(s, _http(handler))
    assert c.generate("S", []) == "ok"
    assert seen["body"]["reasoning_effort"] == "low" and seen["body"]["include_reasoning"] is False
    assert seen["body"]["stream_options"] == {"include_usage": True}
    assert (c.last_usage.completion_tokens, c.last_usage.reasoning_tokens) == (40, 30)


def test_ollama_body_never_gets_hosted_extras() -> None:
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=_ollama_lines("ok"))

    OllamaClient(_settings(request_extra={"m:": {"reasoning_effort": "low"}}), _http(handler)).generate(
        "S", []
    )
    assert "reasoning_effort" not in seen["body"]


@pytest.mark.parametrize(
    ("headers", "wait"),
    [
        ({"retry-after": "7"}, 7.0),
        ({"x-ratelimit-reset-tokens": "764ms"}, 0.764),
        ({"x-ratelimit-reset-requests": "8m38.4s"}, 518.4),
        ({}, 10.0),
    ],
)
def test_429_raises_rate_limited_then_cools_down_without_requests(headers, wait) -> None:
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(429, headers=headers, text="slow down")

    c = OpenAICompatClient(_settings("openai_compat"), _http(handler))
    with pytest.raises(LLMRateLimited) as e:
        c.generate("s", [])
    assert e.value.retry_after_s == pytest.approx(wait)
    if wait > 0.5:
        with pytest.raises(LLMRateLimited):
            c.generate("s", [])
        assert len(calls) == 1  # cooling down: no second request


def test_openai_compat_has_model_reads_models_list_and_ping_401() -> None:
    models = httpx.Response(200, json={"data": [{"id": "m:1"}, {"id": "other"}]})
    assert OpenAICompatClient(_settings("openai_compat"), _http(lambda r: models)).has_model()
    other = httpx.Response(200, json={"data": [{"id": "other"}]})
    assert not OpenAICompatClient(_settings("openai_compat"), _http(lambda r: other)).has_model()
    denied = OpenAICompatClient(_settings("openai_compat"), _http(lambda r: httpx.Response(401)))
    assert not denied.ping()


def test_openai_compat_warm_up_asks_for_a_real_short_answer() -> None:
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=_sse("pong"))

    c = OpenAICompatClient(_settings("openai_compat", max_tokens={"warmup_hosted": 128}), _http(handler))
    assert c.warm_up() >= 0
    assert seen["body"]["max_tokens"] == 128 and seen["body"]["messages"][0]["content"]


def test_cached_client_caches_ping_result() -> None:
    n = []
    inner = SimpleNamespace(
        name="x", settings=SimpleNamespace(ping_cache_s=30.0), ping=lambda t=2: n.append(1) or True
    )
    c = CachedClient(inner)
    assert c.ping() and c.ping() and len(n) == 1


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


def test_warm_up_accepts_its_own_one_token_cut_off() -> None:
    """Warm-up asks for 1 token, so Ollama always answers done_reason=length. That's success, not an error
    (before this, every `make llm-bench` run failed with "warm-up failed: reply cut off at max_tokens")."""
    cut = b'{"message": {"content": "H"}, "done": true, "done_reason": "length"}\n'
    c = OllamaClient(_settings(), _http(lambda r: httpx.Response(200, content=cut)))
    assert c.warm_up() >= 0


def test_warm_up_still_raises_real_errors() -> None:
    c = OllamaClient(
        _settings(), _http(lambda r: httpx.Response(200, content=b'{"error": "model not found"}\n'))
    )
    with pytest.raises(LLMError):
        c.warm_up()


def test_failover_client_moves_on_only_when_rate_limited() -> None:
    from greenhome.llm.client import FailoverClient

    def stub(name, reply):
        def gen(*a, **k):
            if isinstance(reply, Exception):
                raise reply
            return reply

        return SimpleNamespace(name=name, settings=_settings("openai_compat"), last_usage=None, generate=gen)

    limited = LLMRateLimited("429", 5.0)
    assert FailoverClient([stub("a", limited), stub("b", "ok")]).generate("s", []) == "ok"
    with pytest.raises(LLMRateLimited):
        FailoverClient([stub("a", limited), stub("b", limited)]).generate("s", [])
    with pytest.raises(LLMError):  # a real error is not a quota problem: no failover
        FailoverClient([stub("a", LLMError("boom")), stub("b", "ok")]).generate("s", [])
