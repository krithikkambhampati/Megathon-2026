// Overview: what makes up the score, the problem areas, how the home compares with similar homes, and an AI explanation.
import { html, useEffect, useRef } from "../../lib.js";
import { useStore, explain, explanationKey } from "../../store.js";
import { AiAnswer, Button, Chip, Icon, Notice, SectionHeader, Skeleton } from "../../ui.js";
import { fmtIntensity, fmtPct, fmtPoints, fmtRange, fmtScore } from "../../format.js";
import { label, componentText, issueText } from "../../labels.js";

const SEVERITY = { high: ["bad", "High"], medium: ["warn", "Medium"], low: ["info", "Low"] };
const BANDS = { lt50: "under 50 m²", "50_90": "50 to 90 m²", "90_130": "90 to 130 m²", "130_200": "130 to 200 m²", gt200: "over 200 m²" };

// Asks for the AI explanation once the panel is close to the screen, then renders it.
export function AiPanel({ analysis, section, title, followUp, onAsk }) {
  const ref = useRef(null);
  const key = explanationKey(analysis, section);
  const entry = useStore((s) => s.explanations[key]);
  useEffect(() => {
    const el = ref.current;
    if (!el || entry) return;
    if (typeof IntersectionObserver === "undefined") { explain(section, analysis); return; }
    const obs = new IntersectionObserver((es) => {
      if (es.some((e) => e.isIntersecting)) { obs.disconnect(); explain(section, analysis); }
    }, { rootMargin: "300px 0px" });
    obs.observe(el);
    return () => obs.disconnect();
  }, [key, !!entry]);

  let body;
  if (!entry || entry.loading) {
    body = html`<div class="stack gap-2" aria-busy="true"><${Skeleton} h=${14} w="92%" /><${Skeleton} h=${14} w="84%" /><${Skeleton} h=${14} w="60%" /></div>`;
  } else if (entry.error) {
    body = html`<div class="rs-ai-error row gap-3 wrap"><span class="muted small">The written explanation isn't available right now.</span>
      <${Button} variant="ghost" size="sm" icon="refresh" onClick=${() => onRetry(analysis, section)}>Try again<//></div>`;
  } else {
    body = html`<${AiAnswer} text=${entry.text} check=${entry.check} />`;
  }
  return html`<div class="rs-ai" ref=${ref}>
    <div class="row between wrap gap-2 rs-ai-head"><h3 class="rs-h3">${title}</h3>
      ${followUp && html`<button type="button" class="rs-link" onClick=${() => onAsk(followUp)}>Ask a follow-up<${Icon} name="arrow-right" size=${14} /></button>`}</div>
    ${body}</div>`;
}
function onRetry(analysis, section) {
  // explain() skips keys that already hold a result; an error entry has no text, so a retry goes through.
  explain(section, analysis);
}

function Components({ components }) {
  return html`<div class="rs-comp" role="table" aria-label="Score breakdown">
    <div class="rs-comp-row rs-comp-head" role="row">
      <span role="columnheader">Area</span><span role="columnheader">Weight</span>
      <span role="columnheader">Rating out of 100</span><span role="columnheader" class="rs-right">Points</span></div>
    ${components.map((c) => {
      const range = c.sub_score_range;
      const w = Math.max(0, Math.min(100, c.sub_score));
      const tone = c.sub_score >= 70 ? "good" : c.sub_score >= 40 ? "warn" : "bad";
      return html`<div class="rs-comp-row" role="row" key=${c.key}>
        <span role="cell" class="rs-comp-name">${componentText(c.key)}
          ${(c.provenance === "imputed" || c.provenance === "assumed") && html`<span class="faint small"> · estimated</span>`}</span>
        <span role="cell" class="num muted rs-comp-weight"><span class="rs-mobile-label">Weight </span>${fmtPct(c.weight * 100)}</span>
        <span role="cell" class="rs-comp-bar">
          <span class="rs-bar" aria-hidden="true"><span class=${`rs-bar-fill tone-${tone}`} style=${{ width: `${w}%` }}></span></span>
          <span class="num">${range ? fmtRange(range[0], range[1], fmtScore) : fmtScore(c.sub_score)}</span></span>
        <span role="cell" class="num rs-right rs-comp-pts">${fmtPoints(c.contribution)}<span class="rs-mobile-label"> points</span></span>
      </div>`;
    })}
  </div>`;
}

function Issues({ issues }) {
  if (!issues.length) return html`<p class="muted">No problem areas stand out for this home.</p>`;
  return html`<ul class="rs-issues">
    ${issues.map((i) => {
      const [tone, text] = SEVERITY[i.severity] || ["", i.severity];
      return html`<li key=${i.code} class="rs-issue">
        <div class="stack gap-1"><strong>${issueText(i.code)}</strong>
          ${i.component && html`<span class="muted small">Affects ${componentText(i.component).charAt(0).toLowerCase() + componentText(i.component).slice(1)}</span>`}</div>
        <${Chip} tone=${tone}>${text}<//></li>`;
    })}</ul>`;
}

function Peers({ peer }) {
  const v = peer.intensity_kwh_m2;
  const top = Math.max(v, peer.p90_kwh_m2) * 1.12;  // chart scale only, never shown
  const at = (x) => `${Math.max(0, Math.min(100, (x / top) * 100))}%`;
  const verdict = v > peer.p90_kwh_m2 ? "Uses more energy per m² than 90% of similar homes."
    : v > peer.p75_kwh_m2 ? "Uses more energy per m² than 75% of similar homes."
    : v > peer.p50_kwh_m2 ? "Uses a little more energy per m² than a typical similar home."
    : "Uses less energy per m² than a typical similar home.";
  const group = [peer.property_type ? label("PropertyType", peer.property_type).toLowerCase() + "s" : "homes", BANDS[peer.floor_area_band]].filter(Boolean).join(", ");
  const tone = v > peer.p75_kwh_m2 ? "bad" : v > peer.p50_kwh_m2 ? "warn" : "good";
  return html`<div class="rs-peer stack gap-4">
    <p class=${`rs-peer-verdict tone-${tone}`}>${verdict}</p>
    <div class="rs-peer-track" role="img" aria-label=${`Your home ${fmtIntensity(v)}; typical ${fmtIntensity(peer.p50_kwh_m2)}`}>
      <span class="rs-peer-zone" style=${{ left: at(peer.p75_kwh_m2), width: `calc(100% - ${at(peer.p75_kwh_m2)})` }}></span>
      ${[["p50", peer.p50_kwh_m2, "Typical"], ["p75", peer.p75_kwh_m2, null], ["p90", peer.p90_kwh_m2, null]].map(([k, x, t]) =>
        html`<span key=${k} class="rs-peer-tick" style=${{ left: at(x) }}>${t && html`<span class="rs-peer-tick-label">${t}</span>`}</span>`)}
      <span class=${`rs-peer-you tone-${tone}`} style=${{ left: at(v) }}><span class="rs-peer-you-label">You</span></span>
    </div>
    <dl class="rs-peer-legend">
      <div><dt>Your home</dt><dd class="num">${fmtIntensity(v)}</dd></div>
      <div><dt>Typical similar home</dt><dd class="num">${fmtIntensity(peer.p50_kwh_m2)}</dd></div>
      <div><dt>Higher use (top 25%)</dt><dd class="num">${fmtIntensity(peer.p75_kwh_m2)}</dd></div>
      <div><dt>Highest use (top 10%)</dt><dd class="num">${fmtIntensity(peer.p90_kwh_m2)}</dd></div>
    </dl>
    <p class="faint small">Compared with ${group}.</p>
  </div>`;
}

export function ScoreSection({ analysis, onAsk }) {
  const { score, issues = [], peer } = analysis;
  const ok = score.status === "ok" && score.score !== null;
  const followUp = ok ? `Why is my score ${fmtScore(score.score)}?` : "What do you need to score my home?";
  return html`<div class="rs-section">
    <${SectionHeader} eyebrow="Overview" title="What makes up your score"
      intro="Seven areas each give a rating out of 100. Weighted together they make the Green Home Score." />
    ${ok ? html`<${Components} components=${score.components} />`
      : html`<${Notice} tone="warn" title="Not enough information for a score">Add the missing details to see how each area scores.<//>`}
    <div class="rs-two">
      <div class="stack gap-3">
        <h3 class="rs-h3">Problem areas</h3>
        <${Issues} issues=${issues} />
      </div>
      <div class="stack gap-3">
        <h3 class="rs-h3">Compared with similar homes</h3>
        ${peer ? html`<${Peers} peer=${peer} />`
          : html`<p class="muted">We can't compare this home yet: it needs its actual energy use and floor area.</p>`}
      </div>
    </div>
    <${AiPanel} analysis=${analysis} section="score" title="Your score, explained" followUp=${followUp} onAsk=${onAsk} />
  </div>`;
}
