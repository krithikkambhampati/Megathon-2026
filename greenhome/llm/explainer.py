"""Explanations (README P4.3/P4.4, CR-7): fact sheet → LLM → number checker → retry once → template.

`explain()` never raises. With no LLM, a timeout, an LLM error or two failed checks it returns the
deterministic template built from the same fact sheet, with `CheckReport.fallback_used = True`. The whole
answer shares one time budget (`answer_budget_s`, P5 request). `answer_sheet()` is the shared loop that
`chat.py` also uses for what-if answers.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import jinja2

from greenhome.contracts import AnalysisResult, CheckReport
from greenhome.llm.budget import Deadline
from greenhome.llm.checker import check, feedback
from greenhome.llm.client import LLMClient, LLMError
from greenhome.llm.facts import FactSheet, build_fact_sheet
from greenhome.llm.settings import LLMSettings, get_llm_settings

log = logging.getLogger(__name__)

Section = Literal["score", "recommendations", "savings", "value"]
SECTIONS: tuple[str, ...] = ("score", "recommendations", "savings", "value")
_HERE = Path(__file__).resolve().parent
_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader([_HERE / "templates", _HERE / "prompts"]),
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
    undefined=jinja2.ChainableUndefined,  # a missing optional view key renders as empty, never crashes
)
_BLANKS = re.compile(r"\n{3,}")
UNAVAILABLE = "Sorry, an explanation isn't available right now. The figures on screen are still correct."


@dataclass
class Attempt:
    text: str
    report: CheckReport
    seconds: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass
class AnswerTrace:
    """Everything that happened for one answer (the eval's before/after-checker numbers come from here)."""

    sheet: FactSheet
    text: str
    check: CheckReport
    attempts: list[Attempt] = field(default_factory=list)
    fallback_reason: str | None = None  # no_llm | no_time | llm_error | failed_check | None (LLM text shown)
    seconds: float = 0.0


ExplainTrace = AnswerTrace


def render(name: str, **ctx) -> str:
    """Render a template or prompt; tidy blank lines so the text reads as plain paragraphs."""
    text = _ENV.get_template(name).render(**ctx)
    return _BLANKS.sub("\n\n", text).strip()


def render_template(sheet: FactSheet, name: str | None = None) -> str:
    return render(name or f"{sheet.section}.j2", view=sheet.view, notes=sheet.notes)


def system_prompt(sheet: FactSheet, task: str) -> str:
    reasons = "\n".join(f"{code}: {text}" for code, text in sheet.reasons.items()) or "(none)"
    return render(
        "_system.j2",
        facts_json=sheet.lines() or "(none)",
        notes="\n".join(sheet.notes) or "(none)",
        reasons=reasons,
        statuses=", ".join(f"{k} {v}" for k, v in sheet.statuses.items()),
        task=task,
    )


def _template_answer(
    sheet: FactSheet, template: str | None, attempts: int, reason: str
) -> tuple[str, CheckReport]:
    text = render_template(sheet, template)
    report = check(text, sheet)
    if not report.passed:  # a template that fails its own checker is a bug: log it, still show it
        log.error(
            "template %s failed the checker: %s %s",
            template or sheet.section,
            report.unsupported,
            report.banned_phrases,
        )
    return text, report.model_copy(update={"attempts": attempts, "fallback_used": True})


def answer_sheet(
    sheet: FactSheet,
    llm: LLMClient | None,
    *,
    task: str,
    user_message: str,
    deadline: Deadline,
    settings: LLMSettings | None = None,
    template: str | None = None,
    tokens_key: str = "explain",
    allow_retry: bool = True,
) -> AnswerTrace:
    """The guarded loop: generate → check → (retry once with feedback, if time allows) → template."""
    s = settings or get_llm_settings()
    start = time.monotonic()
    attempts: list[Attempt] = []

    def done(text: str, report: CheckReport, reason: str | None) -> AnswerTrace:
        return AnswerTrace(sheet, text, report, attempts, reason, time.monotonic() - start)

    def fallback(reason: str) -> AnswerTrace:
        text, report = _template_answer(sheet, template, len(attempts), reason)
        return done(text, report, reason)

    if llm is None:
        return fallback("no_llm")
    if not deadline.can_call(s.min_call_s):
        return fallback("no_time")
    system = system_prompt(sheet, task)
    messages: list[dict] = [{"role": "user", "content": user_message}]
    for n in (1, 2):
        t0 = time.monotonic()
        try:
            text = llm.generate(
                system, messages, None, s.tokens(tokens_key), timeout_s=deadline.call_timeout(s.cap("answer"))
            )
        except LLMError as e:
            log.info("LLM attempt %d failed (%s); using the template", n, e)
            return fallback("llm_error")
        usage = getattr(llm, "last_usage", None)
        report = check(text, sheet)
        attempts.append(
            Attempt(
                text,
                report,
                time.monotonic() - t0,
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
            )
        )
        if report.passed:
            return done(text, report.model_copy(update={"attempts": n}), None)
        if n == 2 or not allow_retry or not deadline.can_call(s.min_retry_s):
            break
        messages += [{"role": "assistant", "content": text}, {"role": "user", "content": feedback(report)}]
    return fallback("failed_check")


def explain_traced(
    result: AnalysisResult,
    section: Section,
    llm: LLMClient | None,
    *,
    deadline: Deadline | None = None,
    question: str | None = None,
    focus: list[str] | None = None,
    settings: LLMSettings | None = None,
) -> AnswerTrace:
    s = settings or get_llm_settings()
    deadline = deadline or Deadline(s.answer_budget_s)
    sheet = build_fact_sheet(result, section, focus=focus)
    task = render(f"explain_{section}.j2", question=question)
    return answer_sheet(
        sheet,
        llm,
        task=task,
        user_message=question or f"Explain my home's {section} results.",
        deadline=deadline,
        settings=s,
    )


def explain(result: AnalysisResult, section: Section, llm: LLMClient | None) -> tuple[str, CheckReport]:
    """CR-7. Never raises: any failure (even a bug in the fact sheet) gives a safe answer, not a 500."""
    try:
        if section not in SECTIONS:
            raise ValueError(f"unknown section {section!r}")
        trace = explain_traced(result, section, llm)
        return trace.text, trace.check
    except Exception:
        log.exception("explain(%s) failed; returning the safe fallback text", section)
        return UNAVAILABLE, CheckReport(
            passed=True, numbers_found=[], unsupported=[], banned_phrases=[], attempts=0, fallback_used=True
        )
