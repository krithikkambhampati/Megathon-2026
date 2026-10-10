// Improvement plan: the recommended measures in order, what each saves on its own, cost, and what doesn't fit this home.
import { html } from "../../lib.js";
import { Button, Chip, Icon, Notice, SectionHeader } from "../../ui.js";
import { fmtGbpCost, fmtKgSaving, fmtKwhSaving, fmtRange, isIncrease } from "../../format.js";
import { label, flagText, reasonText } from "../../labels.js";
import { AiPanel } from "./score.js";

const SUIT_TONE = { high: "good", medium: "brand", low: "" };
const lower = (s) => (s ? s.charAt(0).toLowerCase() + s.slice(1) : s);
const names = (codes) => codes.map((r) => label("Retrofit", r));
function joinList(items) {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function Saving({ icon, name, value, cls }) {
  const up = isIncrease(value);
  return html`<div class=${`rp-saving ${cls || ""} ${up ? "is-up" : ""}`}>
    <span class="rp-saving-label">${icon && html`<${Icon} name=${icon} size=${14} />`}${name}</span>
    <span class="num rp-saving-value">${fmtKwhSaving(value)}</span></div>`;
}

function FeasChip({ rec }) {
  if (rec.feasibility === "needs_survey") return html`<${Chip} tone="warn" icon="info">${label("Feasibility", rec.feasibility)}<//>`;
  if (!rec.suitability) return null;
  return html`<${Chip} tone=${SUIT_TONE[rec.suitability] || ""}>${label("Suitability", rec.suitability)} suitability<//>`;
}

function Recommendation({ rec, inPlan, onAsk }) {
  const name = label("Retrofit", rec.retrofit);
  const s = rec.standalone_saving;
  const deps = (rec.depends_on || []).filter((d) => inPlan.has(d));
  const carbonUp = isIncrease(rec.standalone_carbon_kg);
  return html`<li class="rp-item">
    <div class="rp-rank num" aria-hidden="true">${rec.rank}</div>
    <div class="rp-body stack gap-3">
      <div class="row between wrap gap-3">
        <div class="row wrap gap-2"><h3 class="rp-name"><span class="sr-only">Step ${rec.rank}: </span>${name}</h3><${FeasChip} rec=${rec} /></div>
        <div class="rp-cost"><span class="muted small">Typical cost</span> <span class="num">${fmtRange(rec.cost_low_gbp, rec.cost_high_gbp, fmtGbpCost)}</span></div>
      </div>
      ${s ? html`<div class="rp-savings">
          <${Saving} icon="bolt" name="Electricity" value=${s.electricity_kwh} cls="is-elec" />
          <${Saving} icon="flame" name="Gas" value=${s.gas_kwh} cls="is-gas" />
          <${Saving} name="Net energy" value=${s.net_kwh} cls="is-net" />
          <div class=${`rp-saving is-carbon ${carbonUp ? "is-up" : ""}`}><span class="rp-saving-label"><${Icon} name="leaf" size=${14} />Carbon</span>
            <span class="num rp-saving-value">${fmtKgSaving(rec.standalone_carbon_kg)}</span></div>
        </div>`
        : html`<p class="muted small">No energy saving estimate for this measure.</p>`}
      ${rec.reasons?.length > 0 && html`<ul class="rp-reasons">${rec.reasons.map((r) => html`<li key=${r}>${reasonText(r)}</li>`)}</ul>`}
      <div class="row between wrap gap-3">
        ${deps.length > 0 ? html`<span class="rp-after small"><${Icon} name="chevron-right" size=${14} />Best done after ${joinList(names(deps).map(lower))}</span>` : html`<span></span>`}
        <${Button} variant="ghost" size="sm" iconRight="arrow-right" onClick=${() => onAsk(`What if I only install ${lower(name)}?`)}>What if I only did this?<//>
      </div>
    </div>
  </li>`;
}

function NotSuitable({ items }) {
  if (!items.length) return null;
  return html`<div class="stack gap-3 rp-out">
    <h3 class="rs-h3">Not in this plan</h3>
    <ul class="rp-out-list">
      ${items.map(({ retrofit, reasons, feasibility }) => html`<li key=${retrofit} class="rp-out-item">
        <div class="row wrap gap-2"><strong>${label("Retrofit", retrofit)}</strong>
          ${feasibility === "infeasible" && html`<${Chip}>${label("Feasibility", feasibility)}<//>`}</div>
        ${reasons.length > 0 && html`<span class="muted small">${reasons.map(reasonText).join(" ")}</span>`}
      </li>`)}
    </ul></div>`;
}

export function PlanSection({ analysis, onAsk }) {
  const recs = analysis.recommendations || [];
  const plan = recs.filter((r) => r.rank !== null && r.rank !== undefined).sort((a, b) => a.rank - b.rank);
  const inPlan = new Set(plan.map((r) => r.retrofit));
  const out = recs.filter((r) => !inPlan.has(r.retrofit)).map((r) => ({ retrofit: r.retrofit, reasons: r.reasons || [], feasibility: r.feasibility }));
  for (const rj of analysis.rejected || []) {
    if (!out.some((o) => o.retrofit === rj.retrofit)) out.push({ retrofit: rj.retrofit, reasons: [rj.reason], feasibility: "infeasible" });
  }
  const status = analysis.savings?.status;

  return html`<div class="rs-section">
    <${SectionHeader} eyebrow="Improvement plan" title="What to do, in order"
      intro="Ranked by how well each measure suits this home. Savings are for each measure on its own, per year." />
    ${status === "out_of_scope" && html`<div class="rp-notice"><${Notice} tone="info" title=${flagText("OUT_OF_SCOPE_FUEL")}>${reasonText("OUT_OF_SCOPE_FUEL")} The measures below still apply.<//></div>`}
    ${status === "insufficient" && html`<div class="rp-notice"><${Notice} tone="info" title=${flagText("INSUFFICIENT_INFO_SAVINGS")}>Add your heating system and energy use to see savings for each measure.<//></div>`}
    ${plan.length
      ? html`<ol class="rp-list">${plan.map((r) => html`<${Recommendation} key=${r.retrofit} rec=${r} inPlan=${inPlan} onAsk=${onAsk} />`)}</ol>
        <p class="faint small rp-note">Savings, carbon and costs are estimates. An increase is shown in red: some measures swap gas for electricity.</p>`
      : html`<p class="muted">There are no measures we would recommend for this home right now.</p>`}
    <${NotSuitable} items=${out} />
    <${AiPanel} analysis=${analysis} section="recommendations" title="Why this order"
      followUp=${plan.length ? `Why is ${lower(label("Retrofit", plan[0].retrofit))} first?` : "What could I do to improve my home?"} onAsk=${onAsk} />
  </div>`;
}
