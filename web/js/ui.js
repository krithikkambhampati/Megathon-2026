// Shared components (DESIGN.md). Presentational only: no API calls, no number formatting beyond format.js.
import { html, useState, useEffect } from "./lib.js";
import { label } from "./labels.js";

// ---------- icons (24×24, stroke) ----------
const PATHS = {
  "arrow-right": "M5 12h14M13 6l6 6-6 6", "arrow-left": "M19 12H5M11 18l-6-6 6-6", check: "M5 12.5l4.5 4.5L19 7",
  info: "M12 16v-5M12 8h.01M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z", close: "M6 6l12 12M18 6 6 18",
  "chevron-down": "m6 9 6 6 6-6", "chevron-right": "m9 6 6 6-6 6", plus: "M12 5v14M5 12h14", minus: "M5 12h14",
  bolt: "M13 2 4 14h7l-1 8 9-12h-7l1-8Z", flame: "M12 22c4 0 7-3 7-7 0-4.5-4-7-4-11-3 2-5 5-5 8-1.5-1-2-2.5-2-4C5 10 5 12.5 5 15c0 4 3 7 7 7Z",
  leaf: "M5 19c0-8 6-14 15-14 0 9-6 15-14 15M5 19l7-7", home: "M3 11.5 12 4l9 7.5M5.5 10v9.5h13V10",
  pound: "M17 19H7c2-1.5 2.5-3.5 2-6.5H7M14 12.5H9M16.5 6.5A3.5 3.5 0 0 0 9.5 7c0 2 .5 3.5.5 5.5",
  message: "M4 5h16v11H9l-5 4V5Z", edit: "M4 20h4L19 9l-4-4L4 16v4ZM13.5 6.5l4 4", refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  warning: "M12 9v4M12 17h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z",
  sliders: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4", building: "M5 21V4h10v17M15 9h4v12M8 8h2M8 12h2M8 16h2",
  spark: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18",
  shield: "M12 3 5 6v6c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6l-7-3ZM9 12l2 2 4-4", send: "M4 12 20 4l-6 16-3-7-7-1Z",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14ZM20 20l-4-4", map: "M12 21s-6-5.5-6-11a6 6 0 0 1 12 0c0 5.5-6 11-6 11ZM12 12a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z",
};
export function Icon({ name, size = 18, stroke = 1.8, className = "" }) {
  return html`<svg width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width=${stroke}
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class=${className}><path d=${PATHS[name] || ""} /></svg>`;
}

// ---------- buttons ----------
export function Button({ variant = "primary", size = "md", icon, iconRight, loading, children, className = "", ...rest }) {
  const cls = `btn btn-${variant} ${size !== "md" ? `btn-${size}` : ""} ${className}`;
  return html`<button type="button" class=${cls} disabled=${rest.disabled || loading} ...${rest}>
    ${loading ? html`<span class="spin" aria-hidden="true"></span>` : icon && html`<${Icon} name=${icon} size=${16} />`}
    ${children}
    ${iconRight && !loading && html`<${Icon} name=${iconRight} size=${16} />`}
  </button>`;
}
export const LinkButton = ({ href, variant = "primary", size = "md", children, iconRight, className = "" }) =>
  html`<a href=${href} class=${`btn btn-${variant} ${size !== "md" ? `btn-${size}` : ""} ${className}`}>${children}${iconRight && html`<${Icon} name=${iconRight} size=${16} />`}</a>`;

// ---------- badges ----------
export function EpcBadge({ rating, size = "md", title }) {
  const cls = `epc ${size === "sm" ? "epc-sm" : size === "lg" ? "epc-lg" : ""}`;
  return html`<span class=${cls} data-band=${rating || ""} title=${title || (rating ? `EPC rating ${rating}` : "EPC rating not known")}>${rating || "?"}</span>`;
}
const BANDS = [["A", "92+"], ["B", "81–91"], ["C", "69–80"], ["D", "55–68"], ["E", "39–54"], ["F", "21–38"], ["G", "1–20"]];
export function EpcLadder({ rating, after }) {
  return html`<div class="ladder" role="img" aria-label=${`EPC rating ${rating || "unknown"}${after ? `, ${after} after improvements` : ""}`}>
    ${BANDS.map(([b, range], i) => {
      const on = b === rating || b === after;
      const tag = b === rating && b === after ? "Now and after" : b === rating ? "Now" : b === after ? "After" : "";
      return html`<div class=${`ladder-row ${on ? "is-on" : ""}`} key=${b}>
        <div class="ladder-bar" style=${{ width: `${44 + i * 9}%`, background: `var(--epc-${b.toLowerCase()})`, color: "CDE".includes(b) ? "#3a3000" : "#fff" }}>
          ${b} <span style=${{ fontWeight: 500, marginLeft: 6, opacity: .85 }}>${range}</span></div>
        <span class="ladder-tag">${tag}</span></div>`;
    })}</div>`;
}
export const ClassPill = ({ cls }) => cls
  ? html`<span class="class-pill" style=${{ "--dot": `var(--cls-${cls})` }}>${label("ScoreClass", cls)}</span>`
  : html`<span class="class-pill">Not enough information</span>`;
export const Chip = ({ tone = "", children, icon }) =>
  html`<span class=${`chip ${tone ? `chip-${tone}` : ""}`}>${icon && html`<${Icon} name=${icon} size=${13} />`}${children}</span>`;

// ---------- score ring ----------
export function ScoreRing({ score, cls, size = 168, stroke = 12, label: lbl = "out of 100" }) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r;
  const frac = score === null || score === undefined ? 0 : Math.max(0, Math.min(1, score / 100));
  return html`<div class="ring" style=${{ width: size, height: size }}>
    <svg width=${size} height=${size} aria-hidden="true">
      <circle cx=${size / 2} cy=${size / 2} r=${r} fill="none" stroke="var(--surface-3)" stroke-width=${stroke} />
      <circle cx=${size / 2} cy=${size / 2} r=${r} fill="none" stroke=${cls ? `var(--cls-${cls})` : "var(--line-strong)"}
        stroke-width=${stroke} stroke-linecap="round" stroke-dasharray=${`${c * frac} ${c}`} style=${{ transition: "stroke-dasharray .6s var(--ease)" }} />
    </svg>
    <div class="ring-label"><div><div class="ring-score" style=${{ "--fs": `${Math.round(size * .27)}px` }}>${score ?? "—"}</div><div class="ring-of">${lbl}</div></div></div>
  </div>`;
}

// ---------- stats & layout ----------
export const Stat = ({ label: lbl, value, hint, tone }) => html`<div class=${`stat ${tone ? `tone-${tone}` : ""}`}>
  <span class="stat-label">${lbl}</span><span class="stat-value">${value}</span>${hint && html`<span class="stat-hint">${hint}</span>`}</div>`;
export const SectionHeader = ({ eyebrow, title, intro, actions }) => html`<div class="row between wrap gap-4" style=${{ alignItems: "flex-end", marginBottom: 24 }}>
  <div class="stack gap-2" style=${{ maxWidth: 680 }}>${eyebrow && html`<span class="eyebrow">${eyebrow}</span>`}<h2>${title}</h2>${intro && html`<p class="muted">${intro}</p>`}</div>
  ${actions && html`<div class="row gap-2">${actions}</div>`}</div>`;

// ---------- form controls ----------
export function Field({ label: lbl, hint, children }) {
  return html`<label class="field"><span class="field-label">${lbl}</span>${children}${hint && html`<span class="field-hint">${hint}</span>`}</label>`;
}
export function Segmented({ options, value, onChange, ariaLabel }) {
  return html`<div class="segmented" role="group" aria-label=${ariaLabel}>
    ${options.map((o) => html`<button type="button" key=${String(o.value)} aria-pressed=${o.value === value} onClick=${() => onChange(o.value)}>${o.label}</button>`)}</div>`;
}
export function Select({ value, options, onChange, placeholder = "Not sure", allowEmpty = true, id }) {
  return html`<select class="select" id=${id} value=${value ?? ""} onChange=${(e) => onChange(e.target.value === "" ? null : e.target.value)}>
    ${allowEmpty && html`<option value="">${placeholder}</option>`}
    ${options.map((o) => html`<option key=${o.value} value=${o.value}>${o.label}</option>`)}</select>`;
}
export function NumberInput({ value, onChange, suffix, min = 0, step = 1, placeholder = "Not sure", id }) {
  return html`<div class="input-wrap"><input class="input num" id=${id} type="number" inputmode="decimal" min=${min} step=${step} placeholder=${placeholder}
    value=${value ?? ""} onInput=${(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />
    ${suffix && html`<span class="input-suffix">${suffix}</span>`}</div>`;
}
export function Toggle({ checked, onChange, label: lbl, disabled }) {
  return html`<label class="toggle" style=${{ opacity: disabled ? .5 : 1 }}><input type="checkbox" checked=${checked} disabled=${disabled}
    onChange=${(e) => onChange(e.target.checked)} /><span class="toggle-track"></span><span>${lbl}</span></label>`;
}

// ---------- disclosure & drawer ----------
export function Disclosure({ title, children, defaultOpen = false, meta }) {
  const [open, setOpen] = useState(defaultOpen);
  return html`<div class="disclosure" data-open=${open}>
    <button type="button" aria-expanded=${open} onClick=${() => setOpen(!open)}><span>${title}</span>
      <span class="row gap-3">${meta && html`<span class="muted small">${meta}</span>`}<${Icon} name="chevron-down" /></span></button>
    ${open && html`<div class="disclosure-body">${children}</div>`}</div>`;
}
export function Drawer({ open, onClose, title, children, footer, width = 460 }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow; document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [open]);
  if (!open) return null;
  return html`<div class="scrim" onClick=${onClose}></div>
    <aside class="drawer" role="dialog" aria-modal="true" aria-label=${title} style=${{ "--w": `${width}px` }}>
      <div class="drawer-head"><h3>${title}</h3><button class="btn btn-ghost btn-sm" onClick=${onClose} aria-label="Close"><${Icon} name="close" /></button></div>
      <div class="drawer-body">${children}</div>${footer && html`<div class="drawer-foot">${footer}</div>`}</aside>`;
}

// ---------- feedback ----------
export const Skeleton = ({ h = 16, w = "100%", r }) => html`<div class="skeleton" style=${{ height: h, width: w, borderRadius: r }}></div>`;
export const Spinner = () => html`<span class="spinner" role="status" aria-label="Loading"></span>`;
const TONE_ICON = { info: "info", warn: "warning", bad: "warning", good: "check" };
export const Notice = ({ tone = "info", title, children }) => html`<div class=${`notice notice-${tone}`} role=${tone === "bad" ? "alert" : "status"}>
  <${Icon} name=${TONE_ICON[tone] || "info"} /><div class="stack gap-1">${title && html`<span class="notice-title">${title}</span>`}${children && html`<div>${children}</div>`}</div></div>`;
export const EmptyState = ({ title, body, action }) => html`<div class="empty stack gap-3" style=${{ alignItems: "center" }}>
  <strong style=${{ color: "var(--ink)" }}>${title}</strong>${body && html`<p>${body}</p>`}${action}</div>`;

// ---------- AI answer ----------
export function AiAnswer({ text, check }) {
  const verified = check && !check.fallback_used;
  return html`<div class="ai"><div class="ai-text">${text}</div>
    <div class="ai-meta"><${Icon} name=${verified ? "shield" : "check"} size=${14} />
      ${verified ? "Every figure checked against your report" : "Standard summary of your report"}</div></div>`;
}

// ---------- house glyph ----------
const ROOFS = {
  detached: "M8 26 24 13l16 13", semi_detached: "M6 26 18 15l12 11M18 15l12-2 12 13", terraced: "M4 26l10-9h20l10 9",
  bungalow: "M5 27 24 17l19 10", flat: "M12 10h24", maisonette: "M10 14h28",
};
export function HouseGlyph({ type, size = 48 }) {
  const tall = type === "flat" || type === "maisonette";
  const body = tall ? html`<rect x="12" y="10" width="24" height="30" rx="2" /><path d="M18 17h4M26 17h4M18 24h4M26 24h4M21 40v-6h6v6" />`
    : type === "bungalow" ? html`<path d="M9 27v13h30V27M21 40v-7h6v7M14 31h4M30 31h4" />`
    : type === "terraced" ? html`<path d="M6 26v14h36V26M18 26v14M30 26v14M10 31h4M22 31h4M34 31h4" />`
    : html`<path d="M10 26v14h28V26M21 40v-7h6v7M14 30h4M30 30h4" />`;
  return html`<svg class="glyph" width=${size} height=${size} viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.8"
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d=${ROOFS[type] || ROOFS.detached} />${body}</svg>`;
}
