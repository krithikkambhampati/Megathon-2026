// "Try a scenario": pick improvements, run them, and compare against the recommended plan using the API's diff.
import { html, useState, useEffect } from "../../lib.js";
import { useStore, runScenario, clearScenario } from "../../store.js";
import { fmtScore, fmtSap, fmtKwhSaving, fmtKgSaving, fmtPct, fmtDelta, isIncrease, MINUS } from "../../format.js";
import { label, reasonText } from "../../labels.js";
import { Button, Toggle, Notice, Skeleton, SectionHeader, ClassPill, EpcBadge, Chip, EmptyState } from "../../ui.js";

const sameSet = (a, b) => a.length === b.length && a.every((x) => b.includes(x));

// Diff rows we show, in order, and how to format each side. Higher is better for every numeric row here.
const ROWS = [
  ["score_after", "Score after the works", "score", (v) => fmtScore(v)],
  ["class_after", "Score class after the works", null, (v) => html`<${ClassPill} cls=${v} />`],
  ["rating_after", "Energy rating after", null, (v) => html`<${EpcBadge} rating=${v} size="sm" />`],
  ["sap_after", "SAP points after", "sap", (v) => fmtSap(v)],
  ["net_kwh", "Energy saved", "kwh_per_year", (v) => savingText(v)],
  ["electricity_kwh", "Electricity saved", "kwh_per_year", (v) => savingText(v)],
  ["gas_kwh", "Gas saved", "kwh_per_year", (v) => savingText(v)],
  ["carbon_total_kg", "Carbon saved", "kg_per_year", (v) => html`<span class=${`num ${isIncrease(v) ? "rb-bad" : ""}`}>${fmtKgSaving(v)}</span>`],
  ["value_uplift_pct_mid", "Indicative value change", "pct", (v) => fmtPct(v)],
];
function savingText(v) { return html`<span class=${`num ${isIncrease(v) ? "rb-bad" : ""}`}>${fmtKwhSaving(v)}</span>`; }
const cell = (out) => typeof out === "string" ? html`<span class="num">${out}</span>` : out;

function DeltaCell({ row, unit }) {
  if (!unit) return row.base === row.new ? html`<span class="faint">Same</span>` : html`<span class="muted">Changed</span>`;
  const text = fmtDelta(row.delta, unit);
  if (text.startsWith("+")) return html`<span class="num rb-good">${text}</span>`;
  if (text.startsWith(MINUS)) return html`<span class="num rb-bad">${text}</span>`;
  return html`<span class="faint">${row.delta === null ? "—" : "No change"}</span>`;
}

function DiffTable({ diff }) {
  const byKey = Object.fromEntries(diff.rows.map((r) => [r.key, r]));
  return html`<div class="rb-table-wrap"><table class="rb-table rb-diff">
    <caption class="sr-only">Recommended plan compared with your scenario</caption>
    <thead><tr><th scope="col"></th><th scope="col">Recommended plan</th><th scope="col">Your scenario</th><th scope="col">Difference</th></tr></thead>
    <tbody>${ROWS.filter(([k]) => byKey[k]).map(([k, name, unit, fmt]) => {
      const r = byKey[k];
      return html`<tr key=${k}><th scope="row">${name}</th><td data-label="Plan">${cell(fmt(r.base))}</td><td data-label="Scenario">${cell(fmt(r.new))}</td>
        <td data-label="Difference"><${DeltaCell} row=${r} unit=${unit} /></td></tr>`;
    })}</tbody></table></div>`;
}

function ScoreCard({ title, result, highlight }) {
  const after = result?.score_after;
  return html`<div class=${`rb-score-card ${highlight ? "is-new" : ""}`}>
    <span class="stat-label">${title}</span>
    <div class="row gap-3 wrap"><span class="rb-score num">${after && after.status === "ok" ? fmtScore(after.score) : "—"}</span>
      <span class="muted small">out of 100</span></div>
    <${ClassPill} cls=${after && after.status === "ok" ? after.score_class : null} />
  </div>`;
}

function ScenarioResult({ analysis, onAsk }) {
  const scenarioAnalysis = useStore((s) => s.scenarioAnalysis);
  const scenarioDiff = useStore((s) => s.scenarioDiff);
  if (!scenarioAnalysis) return null;
  const rejected = scenarioAnalysis.rejected || [];
  const sav = scenarioAnalysis.savings;
  return html`<div class="rb-result stack gap-5" aria-live="polite">
    <div class="row between wrap gap-3">
      <h3>Your scenario compared with the plan</h3>
      <div class="row gap-2 wrap">
        <${Button} variant="secondary" size="sm" icon="message" onClick=${() => onAsk("Explain this scenario")}>Explain this scenario<//>
        <${Button} variant="ghost" size="sm" icon="close" onClick=${clearScenario}>Clear<//>
      </div>
    </div>
    ${rejected.length > 0 && html`<${Notice} tone="warn" title="Some improvements were left out">
      <ul class="rb-list">${rejected.map((r) => html`<li key=${r.retrofit}><strong>${label("Retrofit", r.retrofit)}</strong>: ${reasonText(r.reason)}</li>`)}</ul><//>`}
    ${sav.status === "out_of_scope" && html`<${Notice} tone="warn" title="Savings can't be estimated">${reasonText("OUT_OF_SCOPE_FUEL")}<//>`}
    ${sav.status === "insufficient" && html`<${Notice} title="Not enough information to estimate savings for this scenario" />`}
    <div class="rb-score-pair">
      <${ScoreCard} title="Recommended plan" result=${analysis} />
      <${ScoreCard} title="Your scenario" result=${scenarioAnalysis} highlight=${true} />
    </div>
    ${scenarioDiff ? html`<${DiffTable} diff=${scenarioDiff} />
      ${scenarioDiff.retrofits_added.length > 0 && html`<div class="row wrap gap-2"><span class="muted small">Added to the plan</span>
        ${scenarioDiff.retrofits_added.map((r) => html`<${Chip} key=${r} tone="brand" icon="plus">${label("Retrofit", r)}<//>`)}</div>`}
      ${scenarioDiff.retrofits_removed.length > 0 && html`<div class="row wrap gap-2"><span class="muted small">Left out of the plan</span>
        ${scenarioDiff.retrofits_removed.map((r) => html`<${Chip} key=${r} tone="outline" icon="minus">${label("Retrofit", r)}<//>`)}</div>`}`
      : html`<p class="muted small">A side-by-side comparison isn't available for this scenario.</p>`}
    <p class="faint small">Estimates. Value changes are indicative, not financial advice.</p>
  </div>`;
}

export function ScenarioSection({ analysis, onAsk }) {
  const scenario = useStore((s) => s.scenario);
  const scenarioBusy = useStore((s) => s.scenarioBusy);
  const scenarioError = useStore((s) => s.scenarioError);
  const plan = analysis?.savings?.retrofits || [];
  const [selected, setSelected] = useState(plan);
  const scenarioKey = scenario ? `${scenario.mode}:${(scenario.retrofits || []).join(",")}` : "";

  // Reflect a scenario set elsewhere (e.g. by the chat) in the toggles.
  useEffect(() => {
    if (!scenario) setSelected(plan);
    else if (scenario.mode === "custom") setSelected(scenario.retrofits || []);
    else if (scenario.mode === "none") setSelected([]);
  }, [scenarioKey, analysis?.analysis_id]);

  if (!analysis) return html`<div class="stack gap-4"><${Skeleton} h=${28} w="40%" /><${Skeleton} h=${200} r=${12} /></div>`;
  const recs = analysis.recommendations || [];
  const toggle = (r, on) => setSelected((cur) => on ? [...cur.filter((x) => x !== r), r] : cur.filter((x) => x !== r));
  const isPlan = sameSet(selected, plan);

  return html`<div class="rb-scenario stack gap-6">
    <${SectionHeader} eyebrow="Try a scenario" title="Choose your own set of improvements"
      intro="Switch improvements on or off and see how the result compares with the recommended plan." />
    ${recs.length === 0 ? html`<${EmptyState} title="No improvements to try" body="We didn't find any improvements that apply to this home." />`
    : html`<div class="rb-picker">
      <ul class="rb-toggles" aria-label="Improvements">
        ${recs.map((r) => {
          const off = r.feasibility === "infeasible";
          const why = r.reasons?.[0];
          const note = off ? (why ? reasonText(why) : label("Feasibility", r.feasibility))
            : r.feasibility === "needs_survey" ? (why ? reasonText(why) : label("Feasibility", r.feasibility))
            : plan.includes(r.retrofit) ? "In the recommended plan" : null;
          return html`<li key=${r.retrofit} class=${`rb-toggle-row ${off ? "is-off" : ""}`}>
            <${Toggle} checked=${!off && selected.includes(r.retrofit)} disabled=${off || scenarioBusy}
              onChange=${(on) => toggle(r.retrofit, on)} label=${label("Retrofit", r.retrofit)} />
            ${note && html`<span class=${`small ${off ? "muted" : r.feasibility === "needs_survey" ? "rb-warn" : "faint"}`}>${note}</span>`}
          </li>`;
        })}
      </ul>
      <div class="row wrap gap-2 rb-picker-actions">
        <${Button} icon="sliders" loading=${scenarioBusy} onClick=${() => runScenario(selected)}>Run scenario<//>
        ${!isPlan && html`<${Button} variant="ghost" size="sm" icon="refresh" disabled=${scenarioBusy} onClick=${() => setSelected(plan)}>Back to the plan<//>`}
        <span class="muted small">${selected.length === 0 ? "Nothing selected: shows the home as it is today." : `${selected.length} selected`}</span>
      </div>
    </div>`}
    ${scenarioError && html`<${Notice} tone="bad" title="We couldn't run that scenario">${scenarioError}<//>`}
    ${scenarioBusy ? html`<div class="stack gap-3" aria-busy="true"><${Skeleton} h=${96} r=${12} /><${Skeleton} h=${240} r=${12} /></div>`
      : html`<${ScenarioResult} analysis=${analysis} onAsk=${onAsk} />`}
  </div>`;
}
