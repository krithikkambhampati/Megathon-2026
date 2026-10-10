// Landing page (#/): a short hero and the catalogue of example homes from /v1/catalogue.
import { html, useState, useEffect, useCallback, useMemo } from "../lib.js";
import { api } from "../api.js";
import { label } from "../labels.js";
import { navigate } from "../router.js";
import { fmtArea, fmtScore } from "../format.js";
import { LinkButton, Button, Icon, EpcBadge, ScoreRing, ClassPill, Chip, Segmented, Skeleton, Notice, EmptyState, HouseGlyph } from "../ui.js";

const CLASS_ORDER = ["highly_efficient", "good", "moderate", "poor", "very_poor"];

// The catalogue sends the property type as display text; HouseGlyph wants its shape key.
function glyphType(text) {
  const t = (text || "").toLowerCase();
  if (t.includes("semi")) return "semi_detached";
  if (t.includes("detached")) return "detached";
  if (t.includes("terrace")) return "terraced";
  if (t.includes("bungalow")) return "bungalow";
  if (t.includes("maisonette")) return "maisonette";
  if (t.includes("flat") || t.includes("apartment")) return "flat";
  return "detached";
}

const bedroomsText = (n) => (n === null || n === undefined ? null : `${n} ${n === 1 ? "bedroom" : "bedrooms"}`);

function Hero() {
  return html`<section class="cat-hero" aria-labelledby="cat-title">
    <div class="stack gap-5 cat-hero-text">
      <span class="eyebrow">Green Home Score</span>
      <h1 id="cat-title">Know how green a home is, and what it would take to improve it.</h1>
      <p class="lead">A score out of 100 from the home's details and energy use, with the improvements that matter most,
        what they could save and how they could change its value.</p>
      <div class="row wrap gap-3">
        <${LinkButton} href="#/home/new" size="lg" iconRight="arrow-right">Assess your home<//>
        <${LinkButton} href="#/how-it-works" variant="ghost" size="lg">How it works<//>
      </div>
    </div>
    <ol class="cat-steps" aria-label="How it works">
      <li><span class="cat-step-icon"><${Icon} name="home" /></span><div><strong>Describe the home</strong><span>Type, age, walls, roof, heating. Leave anything you're unsure of.</span></div></li>
      <li><span class="cat-step-icon"><${Icon} name="leaf" /></span><div><strong>See its score</strong><span>Where it stands and the areas holding it back.</span></div></li>
      <li><span class="cat-step-icon"><${Icon} name="sliders" /></span><div><strong>Plan improvements</strong><span>Try upgrades and compare savings, carbon and value.</span></div></li>
    </ol>
  </section>`;
}

function HomeCard({ home }) {
  const open = (e) => { e.preventDefault(); navigate(`/home/${home.id}`); };
  const meta = [home.location, home.property_type, bedroomsText(home.bedrooms),
    home.floor_area_m2 === null || home.floor_area_m2 === undefined ? null : fmtArea(home.floor_area_m2)].filter(Boolean);
  const hasAfter = home.score_after !== null && home.score_after !== undefined;
  return html`<article class=${`cat-card ${home.reference ? "is-reference" : ""}`}>
    ${home.reference && html`<div class="cat-ref"><${Icon} name="info" size=${14} />From the challenge brief</div>`}
    <div class="cat-card-top">
      <span class="cat-glyph"><${HouseGlyph} type=${glyphType(home.property_type)} size=${40} /></span>
      <${EpcBadge} rating=${home.epc_rating} />
    </div>
    <div class="stack gap-1">
      <h3 class="cat-name"><a href=${`#/home/${encodeURIComponent(home.id)}`} onClick=${open}>${home.name}</a></h3>
      <p class="cat-meta">${meta.join(" · ")}</p>
    </div>
    ${home.summary && html`<p class="cat-summary">${home.summary}</p>`}
    <div class="cat-score">
      <${ScoreRing} score=${home.score ?? null} cls=${home.score_class} size=${64} stroke=${6} label="" />
      <div class="stack gap-1">
        <${ClassPill} cls=${home.score_class} />
        ${hasAfter && html`<span class="cat-after">Could reach <strong class="num">${fmtScore(home.score_after)}</strong></span>`}
      </div>
    </div>
    ${home.highlights && home.highlights.length > 0 && html`<div class="row wrap gap-2 cat-chips">
      ${home.highlights.map((h) => html`<${Chip} key=${h}>${h}<//>`)}</div>`}
    <span class="cat-go" aria-hidden="true">View this home <${Icon} name="arrow-right" size=${16} /></span>
  </article>`;
}

function SkeletonCard() {
  return html`<div class="cat-card is-skeleton" aria-hidden="true">
    <div class="cat-card-top"><${Skeleton} h=${40} w=${40} r=${8} /><${Skeleton} h=${28} w=${44} /></div>
    <div class="stack gap-2"><${Skeleton} h=${20} w="80%" /><${Skeleton} h=${14} w="60%" /></div>
    <${Skeleton} h=${14} /><${Skeleton} h=${14} w="70%" />
    <div class="row gap-3"><${Skeleton} h=${64} w=${64} r=${999} /><${Skeleton} h=${28} w=${110} r=${999} /></div>
  </div>`;
}

export function CatalogueScreen() {
  const [homes, setHomes] = useState(null);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("all");

  const load = useCallback(() => {
    let live = true;
    setError(null); setHomes(null);
    api.catalogue().then((data) => live && setHomes(Array.isArray(data) ? data : []))
      .catch((err) => live && setError(err.message));
    return () => { live = false; };
  }, []);
  useEffect(() => load(), [load]);

  const sorted = useMemo(() => homes ? [...homes].sort((a, b) => (b.reference ? 1 : 0) - (a.reference ? 1 : 0)) : [], [homes]);
  const classes = useMemo(() => CLASS_ORDER.filter((c) => sorted.some((h) => h.score_class === c)), [sorted]);
  const shown = filter === "all" ? sorted : sorted.filter((h) => h.score_class === filter);
  const filterOptions = [{ value: "all", label: "All" }, ...classes.map((c) => ({ value: c, label: label("ScoreClass", c) }))];

  return html`<div class="container page cat">
    <${Hero} />
    <section class="cat-list" aria-labelledby="cat-homes">
      <div class="cat-list-head">
        <div class="stack gap-2">
          <h2 id="cat-homes">Explore example homes</h2>
          <p class="muted">Real homes from public records. Open one to see its full report, then try improvements. Scores are estimates.</p>
        </div>
        ${homes && classes.length > 1 && html`<div class="cat-filter">
          <${Segmented} options=${filterOptions} value=${filter} onChange=${setFilter} ariaLabel="Filter by score" /></div>`}
      </div>
      ${error ? html`<div class="stack gap-3 cat-error">
          <${Notice} tone="bad" title="We couldn't load the example homes">${error}<//>
          <div><${Button} variant="secondary" icon="refresh" onClick=${load}>Try again<//></div>
        </div>`
      : !homes ? html`<div class="cat-grid" aria-busy="true">${[0, 1, 2, 3, 4, 5].map((i) => html`<${SkeletonCard} key=${i} />`)}</div>`
      : sorted.length === 0 ? html`<${EmptyState} title="No example homes yet" body="You can still assess your own home from scratch."
          action=${html`<${LinkButton} href="#/home/new" iconRight="arrow-right">Assess your home<//>`} />`
      : shown.length === 0 ? html`<${EmptyState} title="No homes in this group" action=${html`<${Button} variant="secondary" onClick=${() => setFilter("all")}>Show all homes<//>`} />`
      : html`<div class="cat-grid">${shown.map((h) => html`<${HomeCard} key=${h.id} home=${h} />`)}</div>`}
    </section>
  </div>`;
}
