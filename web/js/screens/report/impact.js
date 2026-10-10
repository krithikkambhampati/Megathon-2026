// Savings and value of the full plan: energy per fuel, carbon, indicative value change, with AI explanations.
import { html } from "../../lib.js";
import { useStore, explain, explanationKey } from "../../store.js";
import { fmtKwh, fmtKwhSaving, fmtKgSaving, fmtTonnes, fmtPct, fmtRange, fmtGbpValue, fmtSap, isIncrease } from "../../format.js";
import { label, reasonText } from "../../labels.js";
import { Button, Icon, Notice, Skeleton, Stat, SectionHeader, EpcBadge, AiAnswer, EmptyState } from "../../ui.js";

// On-demand AI explanation of one report section (store.explain caches per analysis + section).
export function ExplainPanel({ analysis, section, cta }) {
  const key = explanationKey(analysis, section);
  const ex = useStore((s) => (key ? s.explanations[key] : null));
  if (!ex) return html`<div><${Button} variant="secondary" size="sm" icon="spark" onClick=${() => explain(section, analysis)}>${cta}<//></div>`;
  if (ex.loading) return html`<div class="rb-ai-loading stack gap-2" aria-busy="true"><${Skeleton} h=${14} w="92%" /><${Skeleton} h=${14} w="80%" /><${Skeleton} h=${14} w="55%" /></div>`;
  if (ex.error) return html`<${Notice} tone="warn" title="We couldn't write an explanation just now">${ex.error}<//>`;
  return html`<${AiAnswer} text=${ex.text} check=${ex.check} />`;
}

// Paired bars for before / after. Widths are purely visual (relative to the larger figure in the table).
function Bar({ value, max, tone }) {
  const w = value > 0 && max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return html`<span class="rb-bar" aria-hidden="true"><span class=${`rb-bar-fill rb-${tone}`} style=${{ width: `${w}%` }}></span></span>`;
}

function SavingCell({ x }) {
  return html`<span class=${`num ${isIncrease(x) ? "rb-bad" : "rb-good"}`}>${fmtKwhSaving(x)}</span>`;
}

function EnergyTable({ savings }) {
  const { baseline, after, saving } = savings;
  const max = Math.max(baseline?.electricity_kwh || 0, baseline?.gas_kwh || 0, after?.electricity_kwh || 0, after?.gas_kwh || 0);
  const rows = [
    ["Electricity", "bolt", "elec", baseline?.electricity_kwh, after?.electricity_kwh, saving?.electricity_kwh],
    ["Gas", "flame", "gas", baseline?.gas_kwh, after?.gas_kwh, saving?.gas_kwh],
  ];
  return html`<div class="rb-table-wrap"><table class="rb-table">
    <caption class="sr-only">Energy use per year, today and after the plan</caption>
    <thead><tr><th scope="col">Fuel</th><th scope="col">Today</th><th scope="col">After the plan</th><th scope="col">Saving</th></tr></thead>
    <tbody>
      ${rows.map(([name, icon, tone, b, a, s]) => html`<tr key=${name}>
        <th scope="row"><span class=${`rb-fuel rb-${tone}-ink`}><${Icon} name=${icon} size=${16} />${name}</span></th>
        <td data-label="Today"><span class="num">${fmtKwh(b)}</span><${Bar} value=${b} max=${max} tone=${tone} /></td>
        <td data-label="After the plan"><span class="num">${fmtKwh(a)}</span><${Bar} value=${a} max=${max} tone=${tone} /></td>
        <td data-label="Saving"><${SavingCell} x=${s} /></td></tr>`)}
      <tr class="rb-total"><th scope="row">All energy bought</th>
        <td data-label="Today"><span class="num">${fmtKwh(baseline?.purchased_kwh)}</span></td>
        <td data-label="After the plan"><span class="num">${fmtKwh(after?.purchased_kwh)}</span></td>
        <td data-label="Saving"><${SavingCell} x=${saving?.net_kwh} /></td></tr>
    </tbody></table></div>`;
}

function SavingsBlock({ analysis }) {
  const { savings, carbon } = analysis;
  if (savings.status === "out_of_scope") return html`<${Notice} tone="warn" title="Savings can't be estimated for this home">
    ${reasonText("OUT_OF_SCOPE_FUEL")} The score and improvement plan above still apply.<//>`;
  if (savings.status === "insufficient" || !savings.saving) return html`<${Notice} title="Not enough information to estimate savings">
    Add your yearly electricity and gas use, or more details about the home, to see estimated savings.<//>`;
  if (!savings.retrofits.length) return html`<${EmptyState} title="No improvements to estimate"
    body="There are no suitable improvements in the plan for this home, so there are no savings to show." />`;

  const elecUp = isIncrease(savings.saving.electricity_kwh);
  const hasHeatPump = savings.retrofits.includes("air_source_heat_pump");
  const carbonUp = carbon && isIncrease(carbon.total_kg);
  const range = savings.saving_low && savings.saving_high ? fmtRange(savings.saving_low.net_kwh, savings.saving_high.net_kwh, fmtKwh) : null;

  return html`<div class="stack gap-6">
    <div class="rb-stats">
      <${Stat} label="Energy saved" value=${fmtKwhSaving(savings.saving.net_kwh)} tone=${isIncrease(savings.saving.net_kwh) ? "bad" : "good"}
        hint=${range ? `Likely range ${range}` : "Across all fuels, per year"} />
      <${Stat} label="Less energy bought" value=${fmtPct(savings.improvement_potential_pct)} hint="Compared with today" />
      ${carbon && html`<${Stat} label=${carbonUp ? "Carbon added" : "Carbon saved"} tone=${carbonUp ? "bad" : "good"}
        value=${carbonUp ? fmtKgSaving(carbon.total_kg) : fmtTonnes(carbon.total_kg)} hint="Per year" />`}
    </div>
    <p class="muted small rb-plan-list">The plan: ${savings.retrofits.map((r) => label("Retrofit", r)).join(", ")}.</p>
    <${EnergyTable} savings=${savings} />
    ${elecUp && html`<div class="rb-explain-up"><${Icon} name="info" size=${16} /><p>
      ${hasHeatPump
        ? "A heat pump runs on electricity instead of gas, so your electricity use goes up while your gas use falls much further. Overall you buy less energy."
        : reasonText("ELECTRICITY_RISES_GAS_FALLS")}</p></div>`}
    ${carbon && html`<div class="rb-carbon">
      <h3 class="rb-h4">Carbon</h3>
      <dl class="rb-dl">
        <div><dt>From electricity</dt><dd class=${`num ${isIncrease(carbon.electricity_kg) ? "rb-bad" : ""}`}>${fmtKgSaving(carbon.electricity_kg)}</dd></div>
        <div><dt>From gas</dt><dd class=${`num ${isIncrease(carbon.gas_kg) ? "rb-bad" : ""}`}>${fmtKgSaving(carbon.gas_kg)}</dd></div>
        <div><dt>In total</dt><dd class=${`num ${carbonUp ? "rb-bad" : "rb-good"}`}>${fmtKgSaving(carbon.total_kg)}</dd></div>
      </dl>
      <p class="faint small">Calculated with UK government carbon conversion factors.</p>
    </div>`}
  </div>`;
}

function ValueBlock({ value }) {
  if (value.status !== "ok") return html`<${Notice} title="Not enough information for a value estimate">
    An indicative value change needs the home's energy rating, or enough details for us to estimate it.<//>`;
  const source = value.current_value_source === "user" ? "Your estimate" : value.current_value_source === "model" ? "Our estimate" : null;
  return html`<div class="rb-value">
    <div class="rb-value-ratings" aria-label="Energy rating today and after the plan">
      <div class="stack gap-1"><span class="stat-label">Rating today</span><div class="row gap-2"><${EpcBadge} rating=${value.rating_before} />
        <span class="muted small"><span class="num">${fmtSap(value.sap_before)}</span> of 100 points</span></div></div>
      <${Icon} name="arrow-right" size=${20} className="faint" />
      <div class="stack gap-1"><span class="stat-label">After the plan</span><div class="row gap-2"><${EpcBadge} rating=${value.rating_after} />
        <span class="muted small"><span class="num">${fmtSap(value.sap_after)}</span> of 100 points</span></div></div>
    </div>
    <div class="rb-stats">
      <${Stat} label="Indicative value change" value=${fmtPct(value.uplift_pct_mid)} hint=${`Likely between ${fmtRange(value.uplift_pct_low, value.uplift_pct_high, fmtPct)}`} />
      ${value.value_low_gbp !== null && value.value_high_gbp !== null && html`<${Stat} label="Indicative value after the works"
        value=${fmtRange(value.value_low_gbp, value.value_high_gbp, fmtGbpValue)}
        hint=${value.current_value_gbp !== null ? `From ${fmtGbpValue(value.current_value_gbp)} today${source ? ` (${source.toLowerCase()})` : ""}` : null} />`}
    </div>
    <p class="faint small">Indicative, not financial advice. Homes with better energy ratings tend to sell for more, but that doesn't mean the works alone would add this value.</p>
  </div>`;
}

export function ImpactSection({ analysis, onAsk }) {
  if (!analysis) return html`<div class="stack gap-4"><${Skeleton} h=${28} w="40%" /><${Skeleton} h=${200} r=${12} /></div>`;
  const savingsOk = analysis.savings.status === "ok" && analysis.savings.saving;
  return html`<div class="rb-impact stack gap-6">
    <${SectionHeader} eyebrow="Savings and value" title="What the full plan could change"
      intro="Estimates for doing every improvement in the plan, based on a typical year of energy use."
      actions=${html`<${Button} variant="ghost" size="sm" icon="message" onClick=${() => onAsk("How much could I save with the full plan?")}>Ask about savings<//>`} />
    <div class="rb-block">
      <div class="rb-block-head"><h3>Energy and carbon</h3><span class="chip chip-outline">Estimates</span></div>
      <${SavingsBlock} analysis=${analysis} />
      ${savingsOk && html`<${ExplainPanel} analysis=${analysis} section="savings" cta="Explain these savings" />`}
    </div>
    <div class="rb-block">
      <div class="rb-block-head"><h3>Property value</h3><span class="chip chip-outline">Indicative</span></div>
      <${ValueBlock} value=${analysis.value} />
      ${analysis.value.status === "ok" && html`<${ExplainPanel} analysis=${analysis} section="value" cta="Explain the value change" />`}
    </div>
  </div>`;
}
