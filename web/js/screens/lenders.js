// Lenders: a precomputed portfolio ranked by improvement potential (GET /v1/portfolio).
// Rows that are also catalogue homes can be opened; the rest are read-only.
import { html, useState, useEffect, useMemo } from "../lib.js";
import { api } from "../api.js";
import { navigate } from "../router.js";
import { label, issueText } from "../labels.js";
import { fmtPct, fmtScore } from "../format.js";
import { Button, Icon, EpcBadge, ClassPill, Stat, Segmented, Select, Field, Skeleton, Notice, EmptyState, SectionHeader } from "../ui.js";

const CLASSES = ["highly_efficient", "good", "moderate", "poor", "very_poor"];
const PAGE = 25;
const nil = (x) => x === null || x === undefined;

// Ordering only (no arithmetic on results). Missing values always sort last.
const SORTS = {
  rank: { label: "Rank", key: (r) => r.rank, dir: 1 },
  score: { label: "Score", key: (r) => r.score, dir: 1 },
  potential: { label: "Improvement potential", key: (r) => r.improvement_potential_pct, dir: -1 },
};
function sortRows(rows, by, dir) {
  const key = SORTS[by].key;
  return [...rows].sort((a, b) => {
    const x = key(a), y = key(b);
    if (nil(x) && nil(y)) return a.rank - b.rank;
    if (nil(x)) return 1;
    if (nil(y)) return -1;
    return x === y ? a.rank - b.rank : (x < y ? -1 : 1) * dir;
  });
}

const SAVINGS_NOTE = {
  insufficient: "Not enough information to estimate savings",
  out_of_scope: "Savings not estimated for this kind of home",
};

function homeTitle(row, cat) {
  if (cat?.name) return cat.name;
  const type = row.property_type ? label("PropertyType", row.property_type) : "Home";
  return type;
}

// ---------- loading / error ----------
function Loading() {
  return html`<div class="stack gap-6" aria-busy="true">
    <div class="lenders-stats">${[0, 1, 2, 3].map((i) => html`<div key=${i} class="stack gap-2"><${Skeleton} h=${12} w="60%" /><${Skeleton} h=${30} w="45%" /></div>`)}</div>
    <div class="stack gap-3">${[0, 1, 2, 3, 4].map((i) => html`<${Skeleton} key=${i} h=${18} />`)}</div>
    <div class="stack gap-2">${[0, 1, 2, 3, 4, 5].map((i) => html`<${Skeleton} key=${i} h=${52} />`)}</div>
  </div>`;
}

function LoadError({ err, onRetry }) {
  if (err.status === 503) {
    return html`<${Notice} tone="info" title="The portfolio view isn't ready yet">
      Portfolio rankings are worked out in advance rather than live, so every home is scored the same way.
      This one hasn't been prepared on this server yet. Individual homes can still be assessed from the <a href="#/">Homes</a> page.
    <//>`;
  }
  return html`<div class="stack gap-3" style=${{ alignItems: "flex-start" }}>
    <${Notice} tone="bad" title="We couldn't load the portfolio">${err.message}<//>
    <${Button} variant="secondary" size="sm" icon="refresh" onClick=${onRetry}>Try again<//>
  </div>`;
}

// ---------- headline ----------
function Headline({ data }) {
  const rows = data.rows;
  const poor = rows.filter((r) => r.is_poor === true).length;
  const unknown = rows.filter((r) => nil(r.score)).length;
  const top = rows.find((r) => !nil(r.improvement_potential_pct));
  const listed = rows.length;
  return html`<div class="lenders-stats">
    <${Stat} label="Homes ranked" value=${data.total.toLocaleString("en-GB")}
      hint=${data.total > listed ? `Top ${listed.toLocaleString("en-GB")} shown here` : "Ranked by improvement potential"} />
    <${Stat} label="Poor or very poor" value=${listed ? fmtPct((poor / listed) * 100) : "—"} tone=${poor ? "bad" : ""}
      hint=${`${poor} of ${listed} homes`} />
    <${Stat} label="Highest improvement potential" value=${top ? fmtPct(top.improvement_potential_pct) : "—"}
      hint="Share of bought energy that could be saved" />
    <${Stat} label="Not enough information" value=${String(unknown)}
      hint=${unknown === 1 ? "Home that couldn't be scored" : "Homes that couldn't be scored"} />
  </div>`;
}

function Distribution({ rows }) {
  const counts = CLASSES.map((c) => [c, rows.filter((r) => r.score_class === c).length]);
  const unknown = rows.filter((r) => !r.score_class).length;
  if (unknown) counts.push([null, unknown]);
  const max = Math.max(1, ...counts.map(([, n]) => n));
  return html`<div class="lenders-dist" role="list" aria-label="Homes by score class">
    ${counts.map(([c, n]) => html`<div class="lenders-dist-row" role="listitem" key=${c || "none"}>
      <div class="lenders-dist-label"><${ClassPill} cls=${c} /></div>
      <div class="lenders-dist-track" aria-hidden="true">
        <div class="lenders-dist-bar" style=${{ width: `${(n / max) * 100}%`, background: c ? `var(--cls-${c})` : "var(--line-strong)" }}></div>
      </div>
      <span class="lenders-dist-n num">${n}<span class="sr-only">${n === 1 ? " home" : " homes"}</span></span>
    </div>`)}
  </div>`;
}

// ---------- table ----------
function SortHeader({ id, sort, onSort, className = "" }) {
  const active = sort.by === id;
  const ariaSort = active ? (sort.dir === 1 ? "ascending" : "descending") : "none";
  return html`<th scope="col" aria-sort=${ariaSort} class=${className}>
    <button type="button" class=${`lenders-sort ${active ? "is-active" : ""}`} onClick=${() => onSort(id)}>
      ${SORTS[id].label}<${Icon} name="chevron-down" size=${14} className=${active && sort.dir === 1 ? "is-up" : ""} />
    </button></th>`;
}

function Row({ row, cat }) {
  const open = cat ? () => navigate(`/home/${row.property_id}`) : null;
  const where = row.region ? label("Region", row.region) : null;
  const sub = [cat?.name && row.property_type ? label("PropertyType", row.property_type) : null, where].filter(Boolean).join(" · ");
  const note = SAVINGS_NOTE[row.savings_status];
  return html`<tr class=${open ? "is-link" : ""} onClick=${open || undefined}>
    <td class="lenders-rank num" data-label="Rank">${row.rank}</td>
    <td class="lenders-home" data-label="Home">
      <div class="row gap-3">
        ${cat?.epc_rating ? html`<${EpcBadge} rating=${cat.epc_rating} size="sm" />` : html`<span class="lenders-noepc" title="EPC rating not known">—</span>`}
        <div class="stack grow">
          ${open
            ? html`<button type="button" class="lenders-open" onClick=${(e) => { e.stopPropagation(); open(); }}>${homeTitle(row, cat)}</button>`
            : html`<span class="lenders-title">${homeTitle(row, cat)}</span>`}
          ${sub && html`<span class="muted small">${sub}</span>`}
        </div>
      </div>
    </td>
    <td data-label="Score">
      <div class="row gap-2"><span class="num lenders-score">${fmtScore(row.score)}</span><${ClassPill} cls=${row.score_class} /></div>
    </td>
    <td class="num" data-label="Score after works">${cat && !nil(cat.score_after) ? fmtScore(cat.score_after) : html`<span class="faint">—</span>`}</td>
    <td data-label="Improvement potential">
      ${nil(row.improvement_potential_pct)
        ? html`<span class="faint">—</span>`
        : html`<div class="lenders-pot"><span class="num">${fmtPct(row.improvement_potential_pct)}</span>
            <span class="lenders-pot-track" aria-hidden="true"><span style=${{ width: `${Math.max(0, Math.min(100, row.improvement_potential_pct))}%` }}></span></span></div>`}
    </td>
    <td data-label="Main issues">
      ${row.key_issues.length
        ? html`<ul class="lenders-issues">${row.key_issues.map((c) => html`<li key=${c}>${issueText(c)}</li>`)}</ul>`
        : html`<span class="muted small">${nil(row.score) ? "Not enough information" : "No major issues"}</span>`}
      ${note && html`<div class="lenders-note small">${note}</div>`}
    </td>
    <td class="lenders-go" aria-hidden="true">${open && html`<${Icon} name="chevron-right" size=${16} />`}</td>
  </tr>`;
}

function Table({ rows, catalogue }) {
  const [view, setView] = useState("all");
  const [region, setRegion] = useState(null);
  const [type, setType] = useState(null);
  const [sort, setSort] = useState({ by: "rank", dir: 1 });
  const [shown, setShown] = useState(PAGE);
  useEffect(() => setShown(PAGE), [view, region, type, sort.by, sort.dir]);

  const regions = useMemo(() => [...new Set(rows.map((r) => r.region).filter(Boolean))]
    .map((v) => ({ value: v, label: label("Region", v) })).sort((a, b) => a.label.localeCompare(b.label)), [rows]);
  const types = useMemo(() => [...new Set(rows.map((r) => r.property_type).filter(Boolean))]
    .map((v) => ({ value: v, label: label("PropertyType", v) })).sort((a, b) => a.label.localeCompare(b.label)), [rows]);

  const filtered = useMemo(() => sortRows(rows.filter((r) =>
    (view === "all" || (view === "poor" && r.is_poor === true) || (view === "unscored" && nil(r.score)))
    && (!region || r.region === region) && (!type || r.property_type === type)), sort.by, sort.dir), [rows, view, region, type, sort]);

  const onSort = (by) => setSort((s) => s.by === by ? { by, dir: -s.dir } : { by, dir: SORTS[by].dir });
  const page = filtered.slice(0, shown);
  const anyFilter = view !== "all" || region || type;

  return html`<div class="stack gap-4">
    <div class="lenders-filters">
      <div class="field"><span class="field-label">Show</span>
        <${Segmented} ariaLabel="Show" value=${view} onChange=${setView}
          options=${[{ value: "all", label: "All homes" }, { value: "poor", label: "Poor or very poor" }, { value: "unscored", label: "Not scored" }]} /></div>
      ${regions.length > 1 && html`<${Field} label="Region"><${Select} value=${region} onChange=${setRegion} options=${regions} placeholder="All regions" /><//>`}
      ${types.length > 1 && html`<${Field} label="Type of home"><${Select} value=${type} onChange=${setType} options=${types} placeholder="All types" /><//>`}
    </div>
    ${filtered.length === 0
      ? html`<${EmptyState} title="No homes match" body="Try a different region, type or view."
          action=${anyFilter && html`<${Button} variant="secondary" size="sm" onClick=${() => { setView("all"); setRegion(null); setType(null); }}>Clear filters<//>`} />`
      : html`<div class="lenders-table-wrap card">
        <table class="lenders-table">
          <caption class="sr-only">Homes ranked by improvement potential${catalogue ? ". Homes with a name can be opened." : ""}</caption>
          <thead><tr>
            <${SortHeader} id="rank" sort=${sort} onSort=${onSort} className="lenders-rank" />
            <th scope="col">Home</th>
            <${SortHeader} id="score" sort=${sort} onSort=${onSort} />
            <th scope="col">Score after works</th>
            <${SortHeader} id="potential" sort=${sort} onSort=${onSort} />
            <th scope="col">Main issues</th>
            <th scope="col"><span class="sr-only">Open</span></th>
          </tr></thead>
          <tbody>${page.map((r) => html`<${Row} key=${r.property_id} row=${r} cat=${catalogue?.get(r.property_id)} />`)}</tbody>
        </table>
      </div>`}
    ${filtered.length > 0 && html`<div class="row between wrap gap-3">
      <span class="muted small">Showing ${page.length} of ${filtered.length} ${filtered.length === 1 ? "home" : "homes"}</span>
      ${filtered.length > shown && html`<${Button} variant="secondary" size="sm" icon="plus" onClick=${() => setShown(shown + PAGE)}>Show more<//>`}
    </div>`}
  </div>`;
}

// ---------- screen ----------
export function LendersScreen() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [catalogue, setCatalogue] = useState(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setErr(null); setData(null);
    api.portfolio().then((d) => live && setData(d)).catch((e) => live && setErr(e));
    return () => { live = false; };
  }, [attempt]);
  useEffect(() => {
    let live = true;
    // Only used to make known homes openable; if it fails, rows simply stay read-only.
    api.catalogue().then((list) => live && setCatalogue(new Map((list || []).map((h) => [h.id, h])))).catch(() => {});
    return () => { live = false; };
  }, []);

  return html`<div class="container page lenders">
    <header class="stack gap-3 lenders-intro">
      <span class="eyebrow">For lenders</span>
      <h1>Where a portfolio can improve most</h1>
      <p class="lead">Every home is scored by the same models and ranked by improvement potential: the share of the energy it buys
        that all suitable retrofits together could save. Start with the homes at the top.</p>
    </header>

    ${err ? html`<${LoadError} err=${err} onRetry=${() => setAttempt(attempt + 1)} />`
      : !data ? html`<${Loading} />`
      : data.rows.length === 0 ? html`<${EmptyState} title="No homes in this portfolio yet" body="Once homes have been scored, they will be ranked here." />`
      : html`
        <section class="lenders-block" aria-labelledby="lenders-overview">
          <h2 id="lenders-overview" class="sr-only">Overview</h2>
          <${Headline} data=${data} />
          <p class="muted small lenders-quiet">Estimates from documented models, worked out in advance for the whole portfolio.</p>
        </section>
        <section class="lenders-block">
          <${SectionHeader} eyebrow="Spread" title="Homes by score class" intro="How the listed homes split across the five score classes." />
          <${Distribution} rows=${data.rows} />
        </section>
        <section class="lenders-block">
          <${SectionHeader} eyebrow="Ranking" title="Homes to look at first"
            intro="Sort by any column or narrow the list. Named homes open their full profile." />
          <${Table} rows=${data.rows} catalogue=${catalogue} />
          <p class="muted small lenders-quiet">Improvement potential and scores after works are estimates, not guarantees or financial advice.</p>
        </section>`}
  </div>`;
}
