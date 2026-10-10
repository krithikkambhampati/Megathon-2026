// Port of greenhome/format.py: the ONLY number formatting in the app. Keep in step with the Python
// (tests/unit/p5/test_web_format.py compares them value by value).
export const UNKNOWN = "—";
export const MINUS = "−";

// Round half away from zero to a multiple of `step`, without binary float surprises (29.5 → 30, 0.15 → 0.2).
export function roundHalfUp(x, step = 1) {
  const q = x / step;
  const r = Math.sign(q) * Math.floor(Math.abs(q) + 0.5 + 1e-9);
  return Number((r * step).toFixed(10));
}
function num(x, step, decimals = 0) {
  let v = roundHalfUp(x, step);
  if (Object.is(v, -0) || v === 0) v = 0;
  const s = Math.abs(v).toLocaleString("en-GB", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  return v < 0 ? `-${s}` : s;
}
const nil = (x) => x === null || x === undefined || Number.isNaN(x);

export const fmtKwh = (x) => nil(x) ? UNKNOWN : `${num(x, 10)} kWh/year`;
export const fmtKwhSaving = (x) => nil(x) ? UNKNOWN : (roundHalfUp(x, 10) < 0 ? `${fmtKwh(-x)} increase` : fmtKwh(x));
export const fmtKg = (x) => nil(x) ? UNKNOWN : `${num(x, 10)} kg CO2e/year`;
export const fmtKgSaving = (x) => nil(x) ? UNKNOWN : (roundHalfUp(x, 10) < 0 ? `${fmtKg(-x)} increase` : fmtKg(x));
export const fmtTonnes = (kg) => nil(kg) ? UNKNOWN : `${num(kg / 1000, 0.1, 1)} t CO2e/year`;
function signedGbp(x, step) { const s = num(Math.abs(x), step); return roundHalfUp(x, step) < 0 ? `${MINUS}£${s}` : `£${s}`; }
export const fmtGbpValue = (x) => nil(x) ? UNKNOWN : signedGbp(x, 500);
export const fmtGbpCost = (x) => nil(x) ? UNKNOWN : signedGbp(x, 10);
export const fmtPct = (x) => nil(x) ? UNKNOWN : `${num(x, 0.1, 1)}%`;
export const fmtScore = (x) => nil(x) ? UNKNOWN : String(roundHalfUp(x));
export const fmtSap = (x) => nil(x) ? UNKNOWN : String(roundHalfUp(x));
export const fmtPoints = (x) => nil(x) ? UNKNOWN : num(x, 0.1, 1);
export const fmtIntensity = (x) => nil(x) ? UNKNOWN : `${num(x, 1)} kWh/m²/year`;
export const fmtArea = (x) => nil(x) ? UNKNOWN : `${num(x, 1)} m²`;
export function fmtRange(lo, hi, fn = fmtPct) {
  if (nil(lo) || nil(hi)) return UNKNOWN;
  const a = fn(lo), b = fn(hi);
  return a === b ? a : `${a} – ${b}`;
}
const DELTA = { score: [1, 0, ""], sap: [1, 0, ""], kwh_per_year: [10, 0, " kWh/year"], kg_per_year: [10, 0, " kg CO2e/year"], pct: [0.1, 1, " pp"] };
export function fmtDelta(x, unit) {
  if (nil(x)) return UNKNOWN;
  const [step, d, suffix] = DELTA[unit];
  const v = roundHalfUp(x, step);
  const sign = v > 0 ? "+" : v < 0 ? MINUS : "";
  return `${sign}${num(Math.abs(x), step, d)}${suffix}`;
}
// True when a saving is really an increase (shown in the --bad colour). Mirrors the formatters' rule.
export const isIncrease = (x) => !nil(x) && roundHalfUp(x, 10) < 0;
