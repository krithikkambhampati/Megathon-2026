"""Chat (README §4.3, P4.5, CR-7): router → what-if / explain / memory / out-of-scope / unclear.

Stateless: multi-turn state is `req.current_scenario` only; P5 keeps the transcript and passes
`base = engine.analyse(req.home, ctx)`. What-ifs rerun P2's engine BEFORE anything is explained, so the
LLM never sees a question without the recomputed results. Memory messages return a proposal and are never
stored here. `chat()` never raises because of the LLM or a bad scenario.
"""

from __future__ import annotations

import logging

from pydantic import ValidationError

from greenhome import format as fmt
from greenhome.contracts import (
    AnalysisResult,
    ChatRequest,
    ChatResponse,
    CheckReport,
    CustomerContext,
    MemoryEventIn,
    Scenario,
)
from greenhome.core.diff import diff_results
from greenhome.llm._labels import label
from greenhome.llm.budget import Deadline
from greenhome.llm.checker import check
from greenhome.llm.client import LLMClient
from greenhome.llm.explainer import answer_sheet, explain_traced, render
from greenhome.llm.facts import Fact, build_fact_sheet
from greenhome.llm.memory_parser import parse_memory
from greenhome.llm.router import route
from greenhome.llm.settings import LLMSettings, get_llm_settings
from greenhome.llm.whatif_parser import parse_whatif

log = logging.getLogger(__name__)

_PRIORITY_TEXT = {
    "carbon": "cutting carbon",
    "bills": "lower energy bills",
    "value": "property value",
    "balanced": "a balance of carbon, bills and value",
}
SORRY = "Sorry, I couldn't answer that just now. The figures on screen are still correct."


def _template_reply(
    base: AnalysisResult, template: str, user_facts: list[Fact] | None = None, **ctx
) -> tuple[str, CheckReport]:
    """A deterministic reply, checked like any other answer."""
    sheet = build_fact_sheet(base, "memory", user_facts=user_facts)
    text = render(template, **ctx)
    report = check(text, sheet)
    return text, report.model_copy(update={"attempts": 0, "fallback_used": True})


def _memory_lines(events: list[MemoryEventIn]) -> tuple[list[str], list[Fact]]:
    lines, facts = [], []
    for e in events:
        p = e.payload
        if p.kind == "completed_retrofit":
            when = f" (in {p.completed_on})" if p.completed_on else ""
            if p.completed_on:
                facts.append(
                    Fact(
                        id="U",
                        key="user.completed_on",
                        value=p.completed_on,
                        display=p.completed_on,
                        unit="text",
                        label="When you said it was installed",
                    )
                )
            lines.append(f"You've already had {label('Retrofit', p.retrofit).lower()} installed{when}.")
        elif p.kind == "exclude":
            lines.append(f"You don't want {label('Retrofit', p.retrofit).lower()}.")
        elif p.kind == "budget":
            shown = fmt.fmt_gbp_cost(p.max_budget_gbp)
            facts.append(
                Fact(
                    id="U",
                    key="user.max_budget_gbp",
                    value=p.max_budget_gbp,
                    display=shown,
                    unit="gbp_cost",
                    label="Your stated budget",
                )
            )
            lines.append(f"Your budget for retrofits is {shown}.")
        elif p.kind == "preference":
            lines.append(f"What matters most to you is {_PRIORITY_TEXT[p.priority]}.")
        elif p.kind == "response":
            verb = "turned down" if p.response == "declined" else "accepted"
            lines.append(f"You {verb} {label('Retrofit', p.retrofit).lower()} before.")
    return lines, facts


def _reply(
    req: ChatRequest,
    base: AnalysisResult,
    intent: str,
    text: str,
    report: CheckReport,
    *,
    scenario: Scenario | None = None,
    result: AnalysisResult | None = None,
    diff=None,
    memory: list[MemoryEventIn] | None = None,
) -> ChatResponse:
    return ChatResponse(
        answer=text,
        intent=intent,
        scenario=scenario if scenario is not None else req.current_scenario,
        result=result,
        base_result_id=base.analysis_id,
        check=report,
        memory_proposal=memory,
        diff=diff,
    )


def _whatif(req, engine, llm, ctx, base, deadline, s, focus) -> ChatResponse:
    parsed = parse_whatif(
        req.message, req.home, base, req.current_scenario, llm=llm, deadline=deadline, settings=s
    )
    if parsed.scenario is None:
        text, report = _template_reply(base, "unclear.j2", clarify=parsed.clarify)
        return _reply(req, base, "unclear", text, report)
    try:
        result = engine.run_scenario(req.home, parsed.scenario, ctx)
    except (ValidationError, ValueError) as e:
        log.info("scenario %s failed in the engine: %s", parsed.scenario.name, e)
        text, report = _template_reply(
            base,
            "unclear.j2",
            clarify="I couldn't run that scenario for your home. Could you say it another way?",
        )
        return _reply(req, base, "unclear", text, report)
    diff = diff_results(base, result)
    sheet = build_fact_sheet(
        result, "whatif", base=base, diff=diff, focus=focus, user_facts=parsed.user_facts
    )
    trace = answer_sheet(
        sheet,
        llm,
        task=render("whatif_answer.j2", question=req.message),
        user_message=req.message,
        deadline=deadline,
        settings=s,
        template="whatif.j2",
        tokens_key="whatif_answer",
        allow_retry=parsed.method != "llm",
    )  # an LLM parse already used part of the budget
    return _reply(
        req, base, "whatif", trace.text, trace.check, scenario=parsed.scenario, result=result, diff=diff
    )


def _explain(req, engine, llm, ctx, base, deadline, s, r) -> ChatResponse:
    target, diff = base, None
    if req.current_scenario is not None and req.current_scenario != Scenario():
        try:
            target = engine.run_scenario(req.home, req.current_scenario, ctx)
        except (ValidationError, ValueError):
            target = base
        if r.refers_to_change and target is not base:  # "why did the score go up?" → the what-if diff
            diff = diff_results(base, target)
            sheet = build_fact_sheet(target, "whatif", base=base, diff=diff, focus=r.focus)
            trace = answer_sheet(
                sheet,
                llm,
                task=render("whatif_answer.j2", question=req.message),
                user_message=req.message,
                deadline=deadline,
                settings=s,
                template="whatif.j2",
                tokens_key="whatif_answer",
            )
            return _reply(req, base, "explain", trace.text, trace.check, result=target, diff=diff)
    trace = explain_traced(
        target, r.section, llm, deadline=deadline, question=req.message, focus=r.focus, settings=s
    )
    return _reply(req, base, "explain", trace.text, trace.check, result=target)


def _memory(req, llm, base, deadline, s) -> ChatResponse:
    events = parse_memory(req.message, base, llm=llm, deadline=deadline, settings=s)
    if not events:
        text, report = _template_reply(
            base,
            "unclear.j2",
            clarify=(
                "I didn't catch anything to remember. You can tell me a retrofit you've already had done, "
                "one you don't want, your budget, or whether you care most about carbon, bills or value."
            ),
        )
        return _reply(req, base, "unclear", text, report)
    lines, facts = _memory_lines(events)
    text, report = _template_reply(base, "memory_confirm.j2", user_facts=facts, lines=lines)
    return _reply(req, base, "memory", text, report, memory=events)


def chat(
    req: ChatRequest,
    engine,
    llm: LLMClient | None,
    ctx: CustomerContext | None,
    base: AnalysisResult,
    *,
    settings: LLMSettings | None = None,
) -> ChatResponse:
    """CR-7. `engine` is greenhome.core.orchestrator.Engine (or P5's FixtureEngine with the same methods)."""
    s = settings or get_llm_settings()
    deadline = Deadline(s.answer_budget_s)
    try:
        r = route(
            req.message, has_scenario=req.current_scenario is not None, llm=llm, deadline=deadline, settings=s
        )
        if r.intent == "whatif":
            return _whatif(req, engine, llm, ctx, base, deadline, s, r.focus)
        if r.intent == "explain":
            return _explain(req, engine, llm, ctx, base, deadline, s, r)
        if r.intent == "memory":
            return _memory(req, llm, base, deadline, s)
        text, report = _template_reply(
            base, "out_of_scope.j2" if r.intent == "out_of_scope" else "unclear.j2"
        )
        return _reply(req, base, r.intent, text, report)
    except Exception:
        log.exception("chat failed; returning the safe reply")
        report = CheckReport(
            passed=True, numbers_found=[], unsupported=[], banned_phrases=[], attempts=0, fallback_used=True
        )
        return ChatResponse(
            answer=SORRY,
            intent="unclear",
            scenario=req.current_scenario,
            result=None,
            base_result_id=base.analysis_id,
            check=report,
        )
