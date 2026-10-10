// How it works: the methodology behind the score, the retrofit catalogue, the carbon factors, the data
// sources, the headline evaluation results and what the language model does. Data from api.methodology().
import { html, useState, useEffect } from "../lib.js";
import { api } from "../api.js";
import { label, componentText } from "../labels.js";
import { fmtPct, fmtScore, fmtGbpCost, fmtRange, fmtIntensity } from "../format.js";
import { ClassPill, EpcBadge, Disclosure, Notice, Skeleton, Icon, Button, Chip } from "../ui.js";

const DATA_SOURCES = [
  ["Energy Performance Certificates (EPC)", "Ratings, fabric, heating and floor area for homes in England and Wales. Used to train the rating and energy models and to fill in what a homeowner isn't sure about."],
  ["HM Land Registry Price Paid", "Recorded sale prices. Used with the house price index to estimate what a home is worth today."],
  ["UK House Price Index", "Regional price movements, used to bring past sale prices up to date."],
  ["National Energy Efficiency Data-Framework (NEED)", "Measured gas and electricity use by home type, used to check that estimated energy use is realistic."],
];

const FUEL_NAMES = { electricity: "Electricity", gas: "Mains gas" };
const SUB_TABLES = [
  ["heating", "HeatingSystem"], ["glazing", "Glazing"], ["renewables", "Renewables"], ["smart_controls", "SmartControls"],
];
// Shades of the one brand colour for the weights bar (no rainbow).
const SHADES = [100, 84, 68, 54, 42, 32, 24, 18];

const pct = (frac) => fmtPct(frac * 100); // the one allowed conversion: a weight fraction shown as a percent

function Section({ id, eyebrow, title, intro, children }) {
  return html`<section class="section method-section" id=${id} aria-labelledby=${`${id}-h`}>
    <div class="row between wrap gap-4" style=${{ alignItems: "flex-end", marginBottom: 24 }}>
      <div class="stack gap-2" style=${{ maxWidth: 680 }}>${eyebrow && html`<span class="eyebrow">${eyebrow}</span>`}
        <h2 id=${`${id}-h`}>${title}</h2>${intro && html`<p class="muted">${intro}</p>`}</div></div>
    ${children}</section>`;
}

function Weights({ weights }) {
  const entries = Object.entries(weights || {});
  if (!entries.length) return html`<p class="muted">The weights aren't available right now.</p>`;
  return html`<div class="stack gap-5">
    <div class="m-bar" role="img" aria-label=${entries.map(([k, w]) => `${componentText(k)} ${pct(w)}`).join(", ")}>
      ${entries.map(([k, w], i) => html`<span key=${k} class="m-bar-seg" title=${`${componentText(k)}: ${pct(w)}`}
        style=${{ flexGrow: w, background: `color-mix(in srgb, var(--brand) ${SHADES[i % SHADES.length]}%, var(--surface))` }}></span>`)}
    </div>
    <ol class="m-weights">
      ${entries.map(([k, w], i) => html`<li key=${k}>
        <span class="m-swatch" style=${{ background: `color-mix(in srgb, var(--brand) ${SHADES[i % SHADES.length]}%, var(--surface))` }}></span>
        <span class="grow">${componentText(k)}</span><span class="num m-weight">${pct(w)}</span></li>`)}
    </ol></div>`;
}

function Classes({ classes }) {
  if (!classes?.length) return null;
  return html`<ul class="m-classes">
    ${classes.map((c, i) => {
      const upper = i > 0 ? classes[i - 1].min : null;
      const range = upper === null ? `${fmtScore(c.min)} and above`
        : c.min === 0 ? `Under ${fmtScore(upper)}` : `${fmtScore(c.min)} to under ${fmtScore(upper)}`;
      return html`<li key=${c.class}><${ClassPill} cls=${c.class} /><span class="num muted">${range}</span></li>`;
    })}</ul>`;
}

function PointsTable({ caption, rows }) {
  return html`<table class="m-table m-table-compact"><caption>${caption}</caption>
    <thead><tr><th scope="col">Feature</th><th scope="col" class="m-num">Points</th></tr></thead>
    <tbody>${rows.map(([k, name, pts]) => html`<tr key=${k}><td>${name}</td><td class="m-num num">${fmtScore(pts)}</td></tr>`)}</tbody></table>`;
}

function SubScores({ tables, bounds }) {
  if (!tables) return null;
  const ee = tables.energy_efficiency, ins = tables.insulation;
  return html`<${Disclosure} title="Points for each feature" meta="Out of 100">
    <div class="m-subgrid">
      ${ee && html`<table class="m-table m-table-compact"><caption>${componentText("energy_efficiency")}</caption>
        <thead><tr><th scope="col">EPC rating</th><th scope="col" class="m-num">Points</th></tr></thead>
        <tbody>${Object.entries(ee).map(([b, pts]) => html`<tr key=${b}><td><${EpcBadge} rating=${b} size="sm" /></td><td class="m-num num">${fmtScore(pts)}</td></tr>`)}</tbody></table>`}
      ${bounds && html`<div class="stack gap-2"><h3 class="m-h4">${componentText("consumption_intensity")}</h3>
        <p class="muted small">Full points at ${fmtIntensity(bounds.i_best)} or less, none at ${fmtIntensity(bounds.i_worst)} or more, and in proportion between.</p></div>`}
      ${ins && html`<div class="stack gap-3">
        <h3 class="m-h4">${componentText("insulation")}</h3>
        ${ins.roof_weight != null && ins.wall_weight != null && html`<p class="muted small">The roof counts for ${pct(ins.roof_weight)} and the walls for ${pct(ins.wall_weight)}.</p>`}
        ${ins.roof && html`<${PointsTable} caption="Loft or roof" rows=${Object.entries(ins.roof).map(([k, v]) => [k, label("RoofInsulation", k), v])} />`}
        ${ins.wall && html`<${PointsTable} caption="Walls" rows=${Object.entries(ins.wall).flatMap(([k, v]) => v !== null && typeof v === "object"
          ? Object.entries(v).map(([t, pts]) => [`${k}-${t}`, `${label("WallInsulation", k)}: ${label("WallType", t).toLowerCase()}`, pts])
          : [[k, label("WallInsulation", k), v]])} />`}</div>`}
      ${SUB_TABLES.filter(([k]) => tables[k]).map(([k, en]) => html`<${PointsTable} key=${k} caption=${componentText(k)}
        rows=${Object.entries(tables[k]).map(([v, pts]) => [v, label(en, v), pts])} />`)}
    </div><//>`;
}

function prereqText(p) {
  if (p && p.insulation_sub_score_min != null) {
    const also = p.or_in_package_any?.length ? ", or insulation added in the same plan" : "";
    return `Needs reasonable insulation first (an insulation score of at least ${fmtScore(p.insulation_sub_score_min)} out of 100)${also}.`;
  }
  return null;
}

function Retrofit({ r }) {
  const [lo, hi] = r.cost_gbp || [];
  const prereqs = (r.prerequisites || []).map(prereqText).filter(Boolean);
  return html`<li class="m-retro">
    <div class="m-retro-head">
      <h3 class="m-h4">${label("Retrofit", r.retrofit)}</h3>
      <span class="num m-retro-cost">${fmtRange(lo, hi, fmtGbpCost)}</span>
    </div>
    <div class="row wrap gap-2">
      ${r.lifetime_years != null && html`<${Chip}>Lasts about ${r.lifetime_years} years<//>`}
      ${r.grant_gbp > 0 && html`<${Chip} tone="good">Grant available: ${fmtGbpCost(r.grant_gbp)}<//>`}
    </div>
    ${prereqs.map((t) => html`<p class="small muted" key=${t}>${t}</p>`)}
    ${(r.source || r.notes) && html`<${Disclosure} title="Sources and notes">
      <div class="stack gap-2 small m-prose">${r.source && html`<p><strong>Source.</strong> ${r.source}</p>`}${r.notes && html`<p><strong>Note.</strong> ${r.notes}</p>`}</div><//>`}
  </li>`;
}

function Results({ results }) {
  const models = results?.models || [];
  const llm = results?.llm;
  if (!models.length && !llm?.rows?.length) return null;
  return html`<${Section} id="results" eyebrow="Evaluation" title="How accurate it is"
    intro="Measured on homes the models never saw during training, against a simple baseline. These are headline figures from our evaluation.">
    ${models.length > 0 && html`<div class="m-scroll"><table class="m-table">
      <thead><tr><th scope="col">What</th><th scope="col">Measure</th><th scope="col" class="m-num">Result</th><th scope="col" class="m-num">Simple baseline</th></tr></thead>
      <tbody>${models.map((m, i) => html`<tr key=${i}><td><strong>${m.model}</strong></td><td>${m.metric}</td>
        <td class="m-num num">${m.value ?? "—"}</td><td class="m-num num muted">${m.baseline ?? "—"}</td></tr>`)}</tbody></table></div>`}
    ${llm?.rows?.length > 0 && html`<div class="stack gap-3" style=${{ marginTop: 32 }}>
      <h3>Written explanations</h3>
      ${llm.scenarios != null && html`<p class="muted small">Tested on ${llm.scenarios} realistic questions and report sections.</p>`}
      <div class="m-scroll"><table class="m-table">
        <thead><tr><th scope="col">Measure</th><th scope="col" class="m-num">Result</th><th scope="col" class="m-num">Target</th></tr></thead>
        <tbody>${llm.rows.map((r, i) => html`<tr key=${i}><td>${r.metric}</td><td class="m-num num">${r.value ?? "—"}</td><td class="m-num num muted">${r.target ?? "—"}</td></tr>`)}</tbody></table></div></div>`}
  <//>`;
}

function Ai() {
  const items = [
    ["spark", "It explains, it doesn't calculate", "Every score, saving, cost and value comes from the engine. The language model only puts those numbers into plain English."],
    ["shield", "Every number is checked", "Before an explanation is shown, each figure in it is compared with the computed figures. Anything that doesn't match, or a saving described as an increase, fails the check."],
    ["check", "A standard answer if it fails", "If the check fails or the model isn't available, you see a standard written summary of the same figures instead. The page says which one you're reading."],
    ["warning", "What it won't do", "It is told never to give financial advice, promise savings or make up figures, and the check above backs that up for numbers."],
  ];
  return html`<ul class="m-ai">${items.map(([icon, t, body]) => html`<li key=${t}>
    <span class="m-ai-icon"><${Icon} name=${icon} size=${18} /></span>
    <div class="stack gap-1"><h3 class="m-h4">${t}</h3><p class="muted">${body}</p></div></li>`)}</ul>`;
}

function Loading() {
  return html`<div class="stack gap-4" aria-busy="true"><${Skeleton} h=${28} w="40%" /><${Skeleton} h=${20} /><${Skeleton} h=${160} />
    <${Skeleton} h=${28} w="30%" /><${Skeleton} h=${220} /></div>`;
}

export function MethodScreen() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setError(null);
    api.methodology().then((d) => live && setData(d)).catch((e) => live && setError(e));
    return () => { live = false; };
  }, [attempt]);

  return html`<div class="container page method">
    <header class="stack gap-3 method-hero">
      <span class="eyebrow">How it works</span>
      <h1>How the Green Home Score is worked out</h1>
      <p class="lead">A score out of 100 built from seven parts of a home, an improvement plan costed from published sources, and
        savings, carbon and value estimates from models trained on public data. Here is what goes in and how well it does.</p>
    </header>

    ${error && !data && html`<div class="stack gap-3" style=${{ marginTop: 32 }}><${Notice} tone="bad" title="We couldn't load the method">${error.message}<//>
      <div><${Button} variant="secondary" icon="refresh" onClick=${() => setAttempt(attempt + 1)}>Try again<//></div></div>`}
    ${!data && !error && html`<div style=${{ marginTop: 40 }}><${Loading} /></div>`}

    ${data && html`
      <${Section} id="score" eyebrow="The score" title="How the score works"
        intro="Each part of the home gets points out of 100. The score is the weighted average, so the parts that matter most for energy count for more.">
        <div class="m-two">
          <${Weights} weights=${data.weights} />
          <div class="stack gap-3"><h3 class="m-h4">Score classes</h3><${Classes} classes=${data.classes} />
            <p class="muted small">If too little is known about a home, we say so rather than guess a score.</p></div>
        </div>
        <div style=${{ marginTop: 24 }}><${SubScores} tables=${data.sub_score_tables} bounds=${data.intensity_bounds} /></div>
      <//>

      <${Section} id="retrofits" eyebrow="Improvements" title="The improvements we consider"
        intro="Typical installed costs for a home in England and Wales. Your plan only includes the ones that suit your home, in a sensible order. Costs are estimates.">
        ${data.retrofit_catalogue?.length
          ? html`<ul class="m-retros">${data.retrofit_catalogue.map((r) => html`<${Retrofit} key=${r.retrofit} r=${r} />`)}</ul>`
          : html`<p class="muted">The list of improvements isn't available right now.</p>`}
      <//>

      ${data.emission_factors?.length > 0 && html`<${Section} id="carbon" eyebrow="Carbon" title="Carbon factors"
        intro="Carbon is energy use multiplied by the government's published factor for each fuel. Carbon figures are estimates.">
        <div class="m-scroll"><table class="m-table">
          <thead><tr><th scope="col">Fuel</th><th scope="col" class="m-num">kg CO2e per kWh</th><th scope="col">What it covers</th></tr></thead>
          <tbody>${data.emission_factors.map((f) => html`<tr key=${f.fuel}><td><strong>${FUEL_NAMES[f.fuel] ?? label("MainFuel", f.fuel)}</strong></td>
            <td class="m-num num">${f.kg_co2e_per_kwh ?? "—"}</td><td class="muted">${f.scope ?? ""}${f.year ? ` (${f.year})` : ""}</td></tr>`)}</tbody></table></div>
        <div style=${{ marginTop: 16 }}><${Disclosure} title="Where the factors come from">
          <ul class="stack gap-2 small m-prose">${data.emission_factors.map((f) => html`<li key=${f.fuel}><strong>${FUEL_NAMES[f.fuel] ?? label("MainFuel", f.fuel)}.</strong> ${f.source}</li>`)}</ul><//></div>
      <//>`}

      <${Section} id="data" eyebrow="Data" title="The data behind it"
        intro="Public, open data for England and Wales.">
        <dl class="m-sources">${DATA_SOURCES.map(([n, d]) => html`<div key=${n}><dt>${n}</dt><dd class="muted">${d}</dd></div>`)}</dl>
      <//>

      <${Results} results=${data.results} />

      <${Section} id="ai" eyebrow="Explanations" title="What the AI does and doesn't do"
        intro="Written explanations in the report and the answers to your questions come from a language model, with guard rails.">
        <${Ai} />
      <//>

      <p class="muted small m-foot">Savings, carbon and costs are estimates; value changes are indicative. Nothing here is a guarantee or financial advice.</p>
    `}
  </div>`;
}
