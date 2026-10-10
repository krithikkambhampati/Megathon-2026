// Home profile: the details we hold for a home (catalogue example or a blank one), editable, then "See the report".
// Route: #/home/:id and #/home/new. "Not sure" is always null.
import { html, useState, useEffect, useRef } from "../lib.js";
import { useStore, getState, openCatalogueHome, startBlankHome, updateHome, setEnergy, resetHome, analyse } from "../store.js";
import { api } from "../api.js";
import { navigate } from "../router.js";
import { label, options, fieldText, NOT_SURE } from "../labels.js";
import { fmtArea } from "../format.js";
import { Button, Icon, EpcBadge, Segmented, Select, NumberInput, Notice, Skeleton, HouseGlyph, LinkButton } from "../ui.js";

// Fields counted as "details" for the progress line (ids and energy handled separately).
const DETAIL_FIELDS = ["property_type", "age_band", "floor_area_m2", "bedrooms", "region", "current_value_gbp", "energy_rating",
  "roof_type", "roof_insulation", "wall_type", "wall_insulation", "glazing", "heating_system", "main_fuel", "renewables",
  "smart_controls", "listed_or_conservation", "outdoor_space"];
const BANDS = ["A", "B", "C", "D", "E", "F", "G"];

const hasEnergy = (e) => !!e && (e.annual_electricity_kwh != null || e.annual_gas_kwh != null || (e.monthly && e.monthly.length > 0));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const yesNoOptions = () => [{ value: "yes", label: "Yes" }, { value: "no", label: "No" }, { value: null, label: NOT_SURE() }];

// ---------- loading a home ----------
let pending = null;  // id currently being opened (guards double effects)
async function loadCatalogueHome(id) {
  let name = null;
  try { name = (await api.catalogue()).find((h) => h.id === id)?.name || null; } catch { /* name is optional */ }
  if (!name) {
    const h = await api.example(id);
    name = h.property_type ? `${label("PropertyType", h.property_type)}${h.region ? ` in ${label("Region", h.region)}` : ""}` : "Example home";
  }
  return openCatalogueHome(id, name);
}

function useHomeFor(id) {
  const homeId = useStore((s) => s.homeId);
  const home = useStore((s) => s.home);
  const [error, setError] = useState(null);
  const isNew = id === "new";
  const ready = isNew ? (home && homeId === null) : (home && homeId === id);
  useEffect(() => {
    setError(null);
    const s = getState();
    if (isNew) { if (!(s.home && s.homeId === null)) startBlankHome(); return; }
    if (s.homeId === id && s.home) return;
    if (pending === id) return;
    pending = id;
    loadCatalogueHome(id).catch((err) => setError(err.message)).finally(() => { pending = null; });
  }, [id]);
  return { ready, error, isNew };
}

// ---------- field building blocks ----------
function Changed({ k }) {
  const changed = useStore((s) => s.original && s.home && !same(s.home[k], s.original[k]));
  return changed ? html`<span class="hm-changed">Changed</span>` : null;
}
function FieldLabel({ k, text, htmlFor }) {
  return html`<span class="field-label hm-label">${htmlFor ? html`<label for=${htmlFor}>${text}</label>` : html`<span>${text}</span>`}<${Changed} k=${k} /></span>`;
}
function SelectField({ k, enumName, hint, text }) {
  const value = useStore((s) => s.home[k]);
  const id = `hm-${k}`;
  return html`<div class="field">
    <${FieldLabel} k=${k} text=${text || fieldText(k)} htmlFor=${id} />
    <${Select} id=${id} value=${value} options=${options(enumName)} onChange=${(v) => updateHome({ [k]: v })} />
    ${hint && html`<span class="field-hint">${hint}</span>`}</div>`;
}
function NumberField({ k, suffix, hint, step = 1, integer, text }) {
  const value = useStore((s) => s.home[k]);
  const id = `hm-${k}`;
  const onChange = (v) => updateHome({ [k]: v === null || Number.isNaN(v) ? null : integer ? Math.round(v) : v });
  return html`<div class="field">
    <${FieldLabel} k=${k} text=${text || fieldText(k)} htmlFor=${id} />
    <${NumberInput} id=${id} value=${value} suffix=${suffix} step=${step} onChange=${onChange} />
    ${hint && html`<span class="field-hint">${hint}</span>`}</div>`;
}
function ChoiceField({ k, opts, hint, text, wide }) {
  const value = useStore((s) => s.home[k]);
  const name = text || fieldText(k);
  return html`<div class=${`field ${wide ? "hm-wide" : ""}`}>
    <${FieldLabel} k=${k} text=${name} />
    <${Segmented} ariaLabel=${name} options=${opts} value=${value ?? null} onChange=${(v) => updateHome({ [k]: v })} />
    ${hint && html`<span class="field-hint">${hint}</span>`}</div>`;
}
function TypeField() {
  const value = useStore((s) => s.home.property_type);
  const opts = options("PropertyType");
  return html`<div class="field hm-wide">
    <${FieldLabel} k="property_type" text=${fieldText("property_type")} />
    <div class="hm-types" role="group" aria-label=${fieldText("property_type")}>
      ${opts.map((o) => html`<button type="button" key=${o.value} class="hm-type" aria-pressed=${value === o.value}
        onClick=${() => updateHome({ property_type: value === o.value ? null : o.value })}>
        <${HouseGlyph} type=${o.value} size=${36} /><span>${o.label}</span></button>`)}
    </div>
    <span class="field-hint">Pick one, or leave it unselected if you're not sure.</span></div>`;
}

function Section({ id, title, intro, children }) {
  return html`<section class="hm-section" aria-labelledby=${id}>
    <div class="hm-section-head"><h2 id=${id}>${title}</h2>${intro && html`<p class="muted">${intro}</p>`}</div>
    <div class="hm-grid">${children}</div></section>`;
}

// ---------- energy readings ----------
function monthKey(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; }
function lastTwelveMonths() {
  const now = new Date();
  return Array.from({ length: 12 }, (_, i) => monthKey(new Date(now.getFullYear(), now.getMonth() - 12 + i, 1)));
}
function monthName(key) {
  const [y, m] = key.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-GB", { month: "short", year: "numeric" });
}

function EnergySection() {
  const energy = useStore((s) => s.home.energy) || {};
  const monthly = energy.monthly || null;
  const [mode, setMode] = useState(monthly && monthly.length ? "monthly" : "annual");
  const stash = useRef(null);
  const [window_, setWindow] = useState(() => (monthly && monthly.length ? monthly.map((r) => r.month).sort() : lastTwelveMonths()));
  useEffect(() => {  // keep the table and mode in step when readings change from outside (e.g. undo)
    if (monthly && monthly.length) {
      if (mode !== "monthly") setMode("monthly");
      const extra = monthly.map((r) => r.month).filter((m) => !window_.includes(m));
      if (extra.length) setWindow([...window_, ...extra].sort());
    }
  }, [monthly]);
  const switchMode = (m) => {
    if (m === mode) return;
    if (m === "annual") { stash.current = monthly; setEnergy({ ...energy, monthly: null }); }
    else {
      const back = stash.current;
      if (back && back.length) { setEnergy({ ...energy, monthly: back }); setWindow([...new Set(back.map((r) => r.month))].sort()); }
      else setWindow(lastTwelveMonths());
    }
    setMode(m);
  };
  const setAnnual = (k, v) => setEnergy({ ...energy, [k]: v });
  const setMonth = (month, k, v) => {
    const byMonth = Object.fromEntries((monthly || []).map((r) => [r.month, r]));
    const row = { month, electricity_kwh: null, gas_kwh: null, ...byMonth[month], [k]: v };
    byMonth[month] = row;
    const rows = Object.values(byMonth).filter((r) => r.electricity_kwh != null || r.gas_kwh != null)
      .sort((a, b) => (a.month < b.month ? -1 : 1));
    setEnergy({ ...energy, monthly: rows.length ? rows : null });
  };
  const rowFor = (m) => (monthly || []).find((r) => r.month === m) || {};

  return html`<section class="hm-section" aria-labelledby="hm-energy">
    <div class="hm-section-head"><h2 id="hm-energy">Energy use <${Changed} k="energy" /></h2>
      <p class="muted">Your meter readings or bills make the biggest difference to accuracy. Leave them empty if you don't have them; we'll estimate from similar homes.</p></div>
    <div class="stack gap-4">
      <${Segmented} ariaLabel="How you'd like to enter energy use" value=${mode} onChange=${switchMode}
        options=${[{ value: "annual", label: "Yearly totals" }, { value: "monthly", label: "Month by month" }]} />
      ${mode === "annual" ? html`<div class="hm-grid">
        <div class="field"><span class="field-label hm-label"><label for="hm-elec"><span class="hm-fuel hm-fuel-elec"><${Icon} name="bolt" size=${14} /></span>${fieldText("electricity_kwh")}</label></span>
          <${NumberInput} id="hm-elec" value=${energy.annual_electricity_kwh ?? null} suffix="kWh/year" step=${10} onChange=${(v) => setAnnual("annual_electricity_kwh", v)} />
          <span class="field-hint">On your annual statement or supplier app.</span></div>
        <div class="field"><span class="field-label hm-label"><label for="hm-gas"><span class="hm-fuel hm-fuel-gas"><${Icon} name="flame" size=${14} /></span>${fieldText("gas_kwh")}</label></span>
          <${NumberInput} id="hm-gas" value=${energy.annual_gas_kwh ?? null} suffix="kWh/year" step=${10} onChange=${(v) => setAnnual("annual_gas_kwh", v)} />
          <span class="field-hint">Enter 0 if the home has no gas supply.</span></div>
      </div>` : html`<div class="hm-monthly">
        <p class="small muted">Fill in the months you have; gaps are fine. Readings in kWh.</p>
        <table>
          <thead><tr><th scope="col">Month</th><th scope="col"><span class="hm-th"><span class="hm-fuel hm-fuel-elec"><${Icon} name="bolt" size=${13} /></span>Electricity</span></th>
            <th scope="col"><span class="hm-th"><span class="hm-fuel hm-fuel-gas"><${Icon} name="flame" size=${13} /></span>Gas</span></th></tr></thead>
          <tbody>${window_.map((m) => {
            const r = rowFor(m);
            return html`<tr key=${m}><th scope="row">${monthName(m)}</th>
              <td><label class="sr-only" for=${`e-${m}`}>Electricity, ${monthName(m)}</label><${NumberInput} id=${`e-${m}`} value=${r.electricity_kwh ?? null} placeholder="—" onChange=${(v) => setMonth(m, "electricity_kwh", v)} /></td>
              <td><label class="sr-only" for=${`g-${m}`}>Gas, ${monthName(m)}</label><${NumberInput} id=${`g-${m}`} value=${r.gas_kwh ?? null} placeholder="—" onChange=${(v) => setMonth(m, "gas_kwh", v)} /></td></tr>`;
          })}</tbody>
        </table>
        <p class="small muted">Switching back to yearly totals keeps these readings aside until you return.</p>
      </div>`}
    </div></section>`;
}

// ---------- summary aside ----------
function problemsOf(home) {
  const out = [];
  if (home.floor_area_m2 != null && !(home.floor_area_m2 > 0)) out.push("Floor area needs to be more than zero.");
  if (home.current_value_gbp != null && !(home.current_value_gbp > 0)) out.push("Property value needs to be more than zero.");
  if (home.bedrooms != null && (home.bedrooms < 0 || home.bedrooms > 20)) out.push("Bedrooms should be between 0 and 20.");
  const e = home.energy || {};
  const neg = (x) => x != null && x < 0;
  if (neg(e.annual_electricity_kwh) || neg(e.annual_gas_kwh) || (e.monthly || []).some((r) => neg(r.electricity_kwh) || neg(r.gas_kwh)))
    out.push("Energy readings can't be negative.");
  return out;
}

function Summary({ isNew }) {
  const home = useStore((s) => s.home);
  const original = useStore((s) => s.original);
  const homeName = useStore((s) => s.homeName);
  const analysing = useStore((s) => s.analysing);
  const analyseError = useStore((s) => s.analyseError);
  const changed = !same(home, original);
  const filled = DETAIL_FIELDS.filter((k) => home[k] !== null && home[k] !== undefined).length + (hasEnergy(home.energy) ? 1 : 0);
  const total = DETAIL_FIELDS.length + 1;
  const problems = problemsOf(home);
  const facts = [home.property_type && label("PropertyType", home.property_type), home.floor_area_m2 > 0 && fmtArea(home.floor_area_m2),
    home.bedrooms != null && `${home.bedrooms} bedroom${home.bedrooms === 1 ? "" : "s"}`].filter(Boolean);

  const go = async () => {
    try { await analyse(); navigate("/report"); } catch { /* analyseError is shown below */ }
  };

  return html`<aside class="hm-aside" aria-label="Summary">
    <div class="hm-card">
      <div class="row gap-3 hm-card-top">
        <div class="hm-glyph"><${HouseGlyph} type=${home.property_type} size=${40} /></div>
        <div class="stack gap-1 grow"><strong class="hm-name">${homeName || "Your home"}</strong>
          <span class="small muted">${facts.length ? facts.join(" · ") : "Details to come"}</span></div>
      </div>
      <div class="row between hm-epc"><span class="small muted">EPC rating</span><${EpcBadge} rating=${home.energy_rating} size="sm" /></div>
      <div class="stack gap-2">
        <div class="row between small"><span class="muted">Details filled in</span><span class="num">${filled} of ${total}</span></div>
        <div class="hm-progress" role="progressbar" aria-valuemin="0" aria-valuemax=${total} aria-valuenow=${filled} aria-label="Details filled in">
          <span style=${{ width: `${(filled / total) * 100}%` }}></span></div>
        ${isNew && filled < 4 && html`<span class="small muted">A few details are enough to start. The more you add, the sharper the estimates.</span>`}
      </div>
      ${problems.length > 0 && html`<${Notice} tone="warn" title="Check these details">${problems.map((p) => html`<div key=${p}>${p}</div>`)}<//>`}
      ${analyseError && !analysing && html`<${Notice} tone="bad" title="We couldn't analyse this home">${analyseError}<//>`}
      <${Button} size="lg" className="hm-go" iconRight="arrow-right" loading=${analysing} disabled=${problems.length > 0} onClick=${go}>
        ${analysing ? "Working out your report" : "See the report"}<//>
      ${changed && !analysing && html`<${Button} variant="ghost" size="sm" icon="refresh" className="hm-undo" onClick=${resetHome}>
        ${isNew ? "Clear my answers" : "Undo my changes"}<//>`}
      <p class="small faint">Scores, savings and values are estimates from documented models, not guarantees.</p>
    </div>
  </aside>`;
}

// ---------- screen ----------
export function HomeScreen({ id }) {
  const { ready, error, isNew } = useHomeFor(id);
  const homeName = useStore((s) => s.homeName);
  const mainFuel = useStore((s) => s.home?.main_fuel);

  if (error) return html`<div class="container page hm-narrow stack gap-4">
    <${Notice} tone="bad" title="We couldn't open this home">${error}<//>
    <div><${LinkButton} href="#/" variant="secondary">Browse homes<//></div></div>`;
  if (!ready) return html`<div class="container page" aria-busy="true"><div class="hm-layout">
    <div class="stack gap-5"><${Skeleton} h=${14} w="120px" /><${Skeleton} h=${44} w="60%" /><${Skeleton} h=${18} w="80%" />
      <${Skeleton} h=${220} r=${12} /><${Skeleton} h=${220} r=${12} /></div>
    <div><${Skeleton} h=${320} r=${12} /></div></div></div>`;

  const yn = yesNoOptions();
  return html`<div class="container page hm">
    <a class="hm-back" href="#/"><${Icon} name="arrow-left" size=${16} />All homes</a>
    <header class="hm-head stack gap-3">
      <span class="eyebrow">${isNew ? "Assess your home" : "Example home"}</span>
      <h1>${isNew ? "Tell us about your home" : homeName}</h1>
      <p class="lead">${isNew
        ? "Start with what you know. Even a few details give a first estimate, and every answer you add makes it sharper. Anything you're unsure of can stay as “Not sure”."
        : "These are the details we hold for this home. Change anything that's out of date, then see the report."}</p>
    </header>
    <div class="hm-layout">
      <div class="hm-form">
        <${Section} id="hm-property" title="The property" intro="The basics: what kind of home it is, how big and where.">
          <${TypeField} />
          <${SelectField} k="age_band" enumName="AgeBand" text="When it was built" />
          <${SelectField} k="region" enumName="Region" />
          <${NumberField} k="floor_area_m2" suffix="m²" hint="Total internal floor area. Often on the EPC certificate." />
          <${NumberField} k="bedrooms" integer />
          <${NumberField} k="current_value_gbp" suffix="GBP" step=${1000} hint="Your own estimate. Leave empty and we'll estimate it." />
        <//>
        <${Section} id="hm-fabric" title="Fabric" intro="The roof, walls and windows decide how much heat the home keeps.">
          <${SelectField} k="roof_type" enumName="RoofType" />
          <${SelectField} k="roof_insulation" enumName="RoofInsulation" hint="Measure the depth between the loft joists if you can." />
          <${SelectField} k="wall_type" enumName="WallType" hint="Homes built after about 1930 usually have cavity walls." />
          <${SelectField} k="wall_insulation" enumName="WallInsulation" />
          <${SelectField} k="glazing" enumName="Glazing" />
        <//>
        <${Section} id="hm-heating" title="Heating and energy" intro="How the home is heated and controlled.">
          <${SelectField} k="heating_system" enumName="HeatingSystem" />
          <${SelectField} k="main_fuel" enumName="MainFuel"
            hint=${mainFuel === "other" ? "We can score this home, but can't yet estimate bill savings for oil, LPG or solid fuel." : null} />
          <${SelectField} k="smart_controls" enumName="SmartControls" />
          <${SelectField} k="renewables" enumName="Renewables" />
          <${ChoiceField} k="energy_rating" wide hint="From the home's Energy Performance Certificate, if it has one."
            opts=${[...BANDS.map((b) => ({ value: b, label: b })), { value: null, label: NOT_SURE() }]} />
        <//>
        <${Section} id="hm-constraints" title="Constraints" intro="These decide which improvements are possible.">
          <${ChoiceField} k="listed_or_conservation" opts=${yn} hint="Listed buildings and conservation areas limit changes to walls and windows." />
          <${ChoiceField} k="outdoor_space" opts=${yn} hint="A heat pump needs space outside for its unit, about the size of a washing machine." />
        <//>
        <${EnergySection} />
      </div>
      <${Summary} isNew=${isNew} />
    </div>
  </div>`;
}
