// The report hero: who the home is, its score and EPC band now and after the plan, the key figures and data notes.
import { html } from "../../lib.js";
import { useStore } from "../../store.js";
import { navigate } from "../../router.js";
import { Button, ClassPill, EpcBadge, EpcLadder, Notice, ScoreRing, Stat } from "../../ui.js";
import { fmtIntensity, fmtKwh, fmtPct, fmtRange, fmtScore } from "../../format.js";
import { label, flagText, fieldText, reasonText } from "../../labels.js";

const FIELD_FLAGS = ["MISSING_FIELD", "IMPUTED_FIELD"];
const INSUFFICIENT = ["INSUFFICIENT_INFO_SCORE", "INSUFFICIENT_INFO_SAVINGS", "INSUFFICIENT_INFO_VALUE"];
const TONE = { error: "bad", warning: "warn", info: "info" };

// Fields we had to guess or that were left blank, as plain names, de-duplicated.
export function unknownFields(analysis) {
  const out = [];
  const add = (f) => { if (f && !out.includes(fieldText(f))) out.push(fieldText(f)); };
  (analysis.flags || []).filter((f) => FIELD_FLAGS.includes(f.code)).forEach((f) => add(f.field));
  Object.entries(analysis.home?.provenance || {}).forEach(([f, p]) => { if (p === "imputed" || p === "assumed") add(f); });
  return out;
}

function list(items) {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function Verdict({ analysis }) {
  const { score, score_after: after, value } = analysis;
  const cls = label("ScoreClass", score.score_class).toLowerCase();
  const parts = [`This home scores ${fmtScore(score.score)} out of 100, which is ${cls}.`];
  if (after?.status === "ok" && after.score !== null && after.score !== score.score) {
    parts.push(`The full improvement plan could take it to ${fmtScore(after.score)} (${label("ScoreClass", after.score_class).toLowerCase()})`
      + (value?.rating_after && value?.rating_before && value.rating_after !== value.rating_before
        ? `, and its EPC rating from ${value.rating_before} to ${value.rating_after}.` : "."));
  } else if (after?.status === "ok" && after.score === score.score) {
    parts.push("There is little left to improve with the measures we assess.");
  }
  return html`<p class="rs-verdict">${parts.join(" ")}</p>`;
}

function Flags({ analysis }) {
  const flags = analysis.flags || [];
  const seen = new Set();
  const notes = [];
  const fields = unknownFields(analysis);
  for (const f of flags) {
    if (FIELD_FLAGS.includes(f.code) || seen.has(f.code)) continue;
    if (f.code === "INSUFFICIENT_INFO_SCORE" && analysis.score.status === "insufficient") continue;  // shown above
    seen.add(f.code);
    const tone = INSUFFICIENT.includes(f.code) ? "info" : (TONE[f.severity] || "info");
    notes.push(html`<${Notice} key=${f.code} tone=${tone} title=${flagText(f.code)}>
      ${f.field ? html`<span>Check: ${fieldText(f.field)}.</span>` : null}<//>`);
  }
  if (fields.length && analysis.score.status !== "insufficient") {
    notes.unshift(html`<${Notice} key="fields" tone="info" title="Some answers were estimated">
      Not answered, so estimated from similar homes: ${list(fields)}. Adding them makes the report more accurate.<//>`);
  }
  if (!notes.length) return null;
  return html`<div class="rs-flags stack gap-2">${notes}</div>`;
}

function KeyStats({ analysis }) {
  const { score_after: after, savings, home, peer } = analysis;
  const stats = [];
  if (after?.status === "ok") {
    stats.push(html`<${Stat} key="after" label="Score after the full plan" value=${fmtScore(after.score)}
      hint=${label("ScoreClass", after.score_class)} tone="good" />`);
  }
  if (home.intensity_kwh_m2 !== null && home.intensity_kwh_m2 !== undefined) {
    stats.push(html`<${Stat} key="int" label="Energy use per m²" value=${fmtIntensity(home.intensity_kwh_m2)}
      hint=${peer ? `Similar homes: ${fmtIntensity(peer.p50_kwh_m2)} typical` : home.energy?.purchased_kwh != null ? `${fmtKwh(home.energy.purchased_kwh)} in total` : null} />`);
  } else if (home.energy?.purchased_kwh != null) {
    stats.push(html`<${Stat} key="use" label="Energy use" value=${fmtKwh(home.energy.purchased_kwh)} />`);
  }
  if (savings.status === "ok") {
    stats.push(html`<${Stat} key="pot" label="Improvement potential" value=${fmtPct(savings.improvement_potential_pct)}
      hint="Less energy bought each year. Estimate" tone="good" />`);
  } else {
    stats.push(html`<${Stat} key="pot" label="Improvement potential" value="—"
      hint=${savings.status === "out_of_scope" ? reasonText("OUT_OF_SCOPE_FUEL") : flagText("INSUFFICIENT_INFO_SAVINGS")} />`);
  }
  return html`<div class="rs-stats">${stats}</div>`;
}

export function ReportSummary({ analysis, homeName, onAsk }) {
  const homeId = useStore((s) => s.homeId);
  const { score, value, home } = analysis;
  const h = home.home;
  const insufficient = score.status !== "ok" || score.score === null;
  const now = value?.rating_before ?? h.energy_rating ?? null;
  const potential = value?.rating_after ?? null;
  const ranged = score.score_range && score.score_range[0] !== score.score_range[1];
  const meta = [h.property_type && label("PropertyType", h.property_type), h.region && label("Region", h.region)].filter(Boolean);

  const actions = html`<div class="row wrap gap-2 rs-actions">
    <${Button} variant="secondary" icon="edit" onClick=${() => navigate(`/home/${homeId || "new"}`)}>Edit details<//>
    <${Button} variant="primary" icon="message" onClick=${() => onAsk("")}>Ask about this home<//>
  </div>`;

  if (insufficient) {
    const fields = unknownFields(analysis);
    return html`<header class="rs-hero"><div class="container">
      <div class="stack gap-2 rs-title"><span class="eyebrow">Green Home Report</span><h1>${homeName || "Your home"}</h1>
        ${meta.length > 0 && html`<p class="muted">${meta.join(" · ")}</p>`}</div>
      <div class="rs-insufficient stack gap-4">
        <${Notice} tone="warn" title="We need a few more details to score this home">
          ${fields.length
            ? html`<span>Please add: ${list(fields)}. Answer what you can; "Not sure" is fine for the rest.</span>`
            : "Some key answers are missing. Add what you know about the home and its energy use."}<//>
        ${actions}
      </div>
    </div></header>`;
  }

  return html`<header class="rs-hero"><div class="container">
    <div class="rs-grid">
      <div class="stack gap-5 rs-main">
        <div class="stack gap-2 rs-title"><span class="eyebrow">Green Home Report</span><h1>${homeName || "Your home"}</h1>
          ${meta.length > 0 && html`<p class="muted">${meta.join(" · ")}</p>`}</div>
        <div class="rs-scoreline">
          <${ScoreRing} score=${score.score} cls=${score.score_class} size=${152} />
          <div class="stack gap-3 rs-scoremeta">
            <span class="rs-label">Green Home Score</span>
            <${ClassPill} cls=${score.score_class} />
            ${ranged && html`<span class="muted small">Likely between ${fmtRange(score.score_range[0], score.score_range[1], fmtScore)}, as some answers were estimated</span>`}
            <div class="row gap-2 rs-epc">
              <${EpcBadge} rating=${now} />
              ${potential && html`<span class="muted small">now</span><span class="rs-arrow" aria-hidden="true">→</span><${EpcBadge} rating=${potential} /><span class="muted small">potential</span>`}
            </div>
          </div>
        </div>
        <${Verdict} analysis=${analysis} />
        ${actions}
      </div>
      ${potential && html`<aside class="rs-ladder" aria-label="EPC rating now and after the plan">
        <span class="rs-label">EPC rating</span><${EpcLadder} rating=${now} after=${potential} />
        <span class="faint small">Rating after the plan is an estimate.</span></aside>`}
    </div>
    <${KeyStats} analysis=${analysis} />
    <${Flags} analysis=${analysis} />
  </div></header>`;
}
