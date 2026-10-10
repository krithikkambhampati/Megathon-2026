"""Scripted stand-in for an LLM: every P4 test (and `eval_llm --allow-no-llm` dry runs) works with no
network, GPU or Ollama. Not used by the app."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from greenhome.llm.client import LLMTimeout


class FakeClock:
    """Manual monotonic clock: pass `clock` to Deadline and `advance()` it from a FakeLLM reply."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@dataclass
class Slow:
    """A reply that takes `seconds` on the FakeLLM's clock. Past the call's timeout it raises LLMTimeout."""

    text: str
    seconds: float


@dataclass
class Call:
    system: str
    messages: list[dict]
    json_schema: dict | None
    max_tokens: int
    timeout_s: float | None


@dataclass
class ScriptedClient:
    """Returns scripted replies in order (implements the LLMClient Protocol). A reply is a str, an
    Exception (raised), a Slow, or a callable (system, messages) -> str. Running out of replies raises
    AssertionError (an unexpected call)."""

    replies: list[str | Exception | Slow | Callable[[str, list[dict]], str]] = field(default_factory=list)
    clock: FakeClock | None = None
    name: str = "fake:scripted"
    calls: list[Call] = field(default_factory=list)

    def generate(
        self,
        system: str,
        messages: list[dict],
        json_schema: dict | None = None,
        max_tokens: int = 400,
        *,
        timeout_s: float | None = None,
    ) -> str:
        self.calls.append(Call(system, messages, json_schema, max_tokens, timeout_s))
        assert self.replies, f"unexpected LLM call #{len(self.calls)}"
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, Slow):
            took = reply.seconds if timeout_s is None else min(reply.seconds, timeout_s)
            if self.clock is not None:
                self.clock.advance(took)
            if timeout_s is not None and reply.seconds > timeout_s:
                raise LLMTimeout(f"fake reply took {reply.seconds} s > {timeout_s} s")
            return reply.text
        if callable(reply):
            return reply(system, messages)
        return reply

    def ping(self, timeout_s: float = 2) -> bool:
        return True
