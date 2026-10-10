# Green Home Score web app: design system and conventions

The investor-facing product. A single-page app with no build step: React 18 (UMD) + `htm` tagged templates,
served by FastAPI at `/`. Everything it needs is vendored (`web/vendor`, `web/fonts`), so it works offline.

## Product voice
- A calm, expert advisor. Plain English, short sentences, active voice. No exclamation marks, no emoji.
- Name things the way a homeowner would: "loft insulation", "your energy use", never enum codes or field ids.
- Never show internal identifiers (P10001, analysis ids), model versions, API status or raw JSON.
- Every saving, carbon and value figure is an estimate; say so once per section, quietly ("Estimates").
  Value changes are "indicative". Never "guarantee", never financial advice.
- An increase is an increase: a negative saving is written "… more" / "increase", in the `--bad` colour.

## Visual identity
- **Typeface:** Geist (UI and headings), Geist Mono for figures that line up (tabular numbers). No other faces.
- **Palette** (tokens in `styles.css`, never raw hex in components except the EPC/class scales below):
  paper `--paper` (warm-neutral off-white), surfaces white, ink near-black green, one brand green
  `--brand`. Electricity `--elec` (blue), gas `--gas` (amber). Semantic: `--good`, `--warn`, `--bad`.
- **Signature:** the EPC rating band. Use `EpcBadge` (arrow-shaped, official A–G colours) wherever a band
  appears, and the A–G ladder on the report. Score classes use `ClassPill` (own colour scale).
- **Shape:** 12px radius cards, 8px controls, 999px pills. One soft shadow token (`--shadow`) for raised
  surfaces only. Hairline borders (`--line`) separate; don't box everything.
- **Space:** 4px grid. Page gutter 24px (16px under 640px). Max content width 1180px. Generous whitespace;
  sections separated by 56–72px on the report.
- **Motion:** 150–200ms ease-out for hover/press/open. Respect `prefers-reduced-motion`.
- **Avoid (looks generated):** gradients, glassmorphism, emoji icons, centred everything, a card around
  every block, rainbow charts, stock "AI sparkle" iconography, filler copy.

## Files
| File | Owner | What |
|---|---|---|
| `index.html` | core | Shell, vendored scripts, fonts |
| `styles.css` | core | Tokens, base, all component classes. Screens may append a clearly marked section |
| `js/lib.js` | core | `html`, React hooks re-exported |
| `js/api.js` | core | `api.*` calls to `/v1/*`, throws `ApiError {status, code, message}` |
| `js/format.js` | core | Port of `greenhome/format.py`. **The only number formatting.** |
| `js/labels.js` | core | `label(enum, value)`, `issueText`, `reasonText`, `flagText`, `componentText`, `fieldText` (loaded from `/v1/labels`) |
| `js/store.js` | core | App state + actions (analyse, scenario, explain, ask) and `useStore` |
| `js/router.js` | core | Hash router: `navigate(path)`, `useRoute()` |
| `js/ui.js` | core | Shared components (below) |
| `js/app.js` | core | Top bar, routes, footer |
| `js/screens/*.js` | screens | One file per screen / report section |

## Shared components (`js/ui.js`)
`Button {variant: primary|secondary|ghost|danger, size: md|lg|sm, icon, onClick, disabled, loading}` ·
`Icon {name, size}` (inline SVG set: arrow-right, arrow-left, check, info, spark, bolt, flame, leaf, home,
pound, chevron-down, chevron-right, close, message, edit, refresh, warning, plus, minus, sliders, building) ·
`EpcBadge {rating, size}` · `EpcLadder {rating, after}` · `ClassPill {cls}` · `ScoreRing {score, cls, size}` ·
`Stat {label, value, hint, tone}` · `Chip {children, tone}` · `Segmented {options:[{value,label}], value, onChange}` ·
`Field {label, hint, children}` · `Select {value, options, onChange, placeholder}` · `NumberInput {value, onChange,
suffix, min, step, placeholder}` · `Toggle {checked, onChange, label}` · `Disclosure {title, children, defaultOpen}` ·
`Drawer {open, onClose, title, children, width}` · `Skeleton {h, w}` · `Spinner` · `Notice {tone, title, children}` ·
`EmptyState {title, body, action}` · `HouseGlyph {type, size}` · `SectionHeader {eyebrow, title, intro, actions}` ·
`AiAnswer {text, check}` (renders an explanation; shows "Verified against the figures" or "Standard answer").

## Data rules
- Numbers come from the API. Screens **never** add, subtract, convert or round results: use `format.js`
  (`fmtKwh`, `fmtKwhSaving`, `fmtTonnes`, `fmtGbpValue`, `fmtGbpCost`, `fmtPct`, `fmtScore`, `fmtDelta`, ...).
- "Not sure" is `null`. Never send `""`, `"unknown"` or `0` for an unanswered field.
- Enum values go to the API; `label()` text goes on screen. Never send a label back.
- All requests go through `store.js` actions or `api.js`. Show `Skeleton` while loading and a friendly
  `Notice` on error (`err.message` is already human-readable).

## Routes
`#/` catalogue · `#/home/:id` home profile (catalogue home) · `#/home/new` start from scratch ·
`#/report` the analysis · `#/lenders` portfolio view · `#/how-it-works` methodology.
