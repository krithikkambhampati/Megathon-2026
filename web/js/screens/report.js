// The report: summary, then Overview · Plan · Impact · Try it, with "Ask" in a side drawer.
// Sections live in screens/report/*.js and receive { analysis, onAsk }.
import { html, useState, useEffect } from "../lib.js";
import { useStore } from "../store.js";
import { navigate } from "../router.js";
import { Button, Icon, Notice, Skeleton } from "../ui.js";
import { ReportSummary } from "./report/summary.js";
import { ScoreSection } from "./report/score.js";
import { PlanSection } from "./report/plan.js";
import { ImpactSection } from "./report/impact.js";
import { ScenarioSection } from "./report/scenario.js";
import { AskDrawer } from "./report/ask.js";

const TABS = [["overview", "Overview"], ["plan", "Improvement plan"], ["impact", "Savings and value"], ["try", "Make your own plan"]];

function SectionNav() {
  const [active, setActive] = useState("overview");
  useEffect(() => {
    const els = TABS.map(([id]) => document.getElementById(id)).filter(Boolean);
    const obs = new IntersectionObserver((entries) => {
      const vis = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (vis[0]) setActive(vis[0].target.id);
    }, { rootMargin: "-120px 0px -60% 0px" });
    els.forEach((el) => obs.observe(el));
    return () => obs.disconnect();
  }, []);
  const go = (id) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  return html`<div class="report-nav"><div class="container row gap-1">
    ${TABS.map(([id, text]) => html`<button key=${id} type="button" class="report-tab" aria-current=${active === id} onClick=${() => go(id)}>${text}</button>`)}
  </div></div>`;
}

export function ReportScreen() {
  const { home, analysis, analysing, analyseError, homeName } = useStore((s) => s);
  const [askOpen, setAskOpen] = useState(false);
  const [askPrefill, setAskPrefill] = useState("");
  const onAsk = (prefill = "") => { setAskPrefill(prefill); setAskOpen(true); };

  if (!home) return html`<div class="container page"><${Notice} title="No home selected">Choose a home from the catalogue to see its report.<//>
    <div style=${{ marginTop: 16 }}><${Button} onClick=${() => navigate("/")} iconRight="arrow-right">Browse homes<//></div></div>`;
  if (analysing || (!analysis && !analyseError)) return html`<div class="container page stack gap-4" aria-busy="true">
    <${Skeleton} h=${28} w="40%" /><${Skeleton} h=${220} r=${16} /><${Skeleton} h=${160} r=${16} /></div>`;
  if (analyseError) return html`<div class="container page"><${Notice} tone="bad" title="We couldn't analyse this home">${analyseError}<//>
    <div style=${{ marginTop: 16 }}><${Button} variant="secondary" onClick=${() => history.back()} icon="arrow-left">Back to the details<//></div></div>`;

  return html`<div class="report">
    <${ReportSummary} analysis=${analysis} homeName=${homeName} onAsk=${onAsk} />
    <${SectionNav} />
    <div class="container">
      <section id="overview" class="report-section"><${ScoreSection} analysis=${analysis} onAsk=${onAsk} /></section>
      <section id="plan" class="report-section"><${PlanSection} analysis=${analysis} onAsk=${onAsk} /></section>
      <section id="impact" class="report-section"><${ImpactSection} analysis=${analysis} onAsk=${onAsk} /></section>
      <section id="try" class="report-section"><${ScenarioSection} analysis=${analysis} onAsk=${onAsk} /></section>
    </div>
    <button type="button" class="ask-fab" onClick=${() => onAsk("")}><${Icon} name="message" size=${18} />Ask about this home</button>
    <${AskDrawer} open=${askOpen} prefill=${askPrefill} onClose=${() => setAskOpen(false)} />
  </div>`;
}
