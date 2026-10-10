// App state and actions. Screens read with useStore(selector) and call the exported actions.
// Persisted to sessionStorage (best effort) so a refresh keeps the current home and report.
import { useSyncExternalStore } from "./lib.js";
import { api } from "./api.js";

const KEY = "ghs.v1";
const blankHome = () => ({
  property_id: null, customer_id: null, property_type: null, age_band: null, floor_area_m2: null, bedrooms: null,
  region: null, current_value_gbp: null, energy_rating: null, roof_type: null, roof_insulation: null, wall_type: null,
  wall_insulation: null, glazing: null, heating_system: null, main_fuel: null, renewables: null, smart_controls: null,
  listed_or_conservation: null, outdoor_space: null, energy: {},
});
const initial = () => ({
  sessionId: (crypto.randomUUID?.() || String(Math.random()).slice(2)),
  homeId: null, homeName: null, home: null, original: null,
  analysis: null, analysing: false, analyseError: null,
  scenario: null, scenarioAnalysis: null, scenarioDiff: null, scenarioBusy: false, scenarioError: null,
  explanations: {}, chat: [], chatBusy: false,
});

let state = initial();
try {
  const saved = JSON.parse(sessionStorage.getItem(KEY) || "null");
  if (saved && saved.home) state = { ...state, ...saved, analysing: false, scenarioBusy: false, chatBusy: false };
} catch { /* private mode etc: start fresh */ }

const listeners = new Set();
function set(patch) {
  state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) };
  listeners.forEach((l) => l());
  try {
    const { sessionId, homeId, homeName, home, original, analysis, scenario, scenarioAnalysis, scenarioDiff, chat } = state;
    sessionStorage.setItem(KEY, JSON.stringify({ sessionId, homeId, homeName, home, original, analysis, scenario, scenarioAnalysis, scenarioDiff, chat }));
  } catch { /* storage full or blocked: in-memory only */ }
}
export const getState = () => state;
export function useStore(selector = (s) => s) {
  return useSyncExternalStore((cb) => { listeners.add(cb); return () => listeners.delete(cb); }, () => selector(state));
}

// ---------- home ----------
export async function openCatalogueHome(id, name) {
  const home = await api.example(id);
  set({ ...resetResults(), homeId: id, homeName: name, home, original: home });
  return home;
}
export function startBlankHome() {
  const home = blankHome();
  set({ ...resetResults(), homeId: null, homeName: "Your home", home, original: home });
}
export function updateHome(patch) {
  set((s) => ({ home: { ...s.home, ...patch, energy: patch.energy ? { ...s.home.energy, ...patch.energy } : s.home.energy } }));
}
export function setEnergy(energy) { set((s) => ({ home: { ...s.home, energy } })); }
export function resetHome() { set((s) => ({ home: s.original })); }
const resetResults = () => ({ analysis: null, analyseError: null, scenario: null, scenarioAnalysis: null, scenarioDiff: null, explanations: {}, chat: [] });

// ---------- analysis ----------
export async function analyse() {
  set({ analysing: true, analyseError: null });
  try {
    const analysis = await api.analyse(state.home);
    set({ ...resetResults(), analysis, analysing: false });
    return analysis;
  } catch (err) {
    set({ analysing: false, analyseError: err.message });
    throw err;
  }
}

// ---------- scenarios ----------
export async function runScenario(retrofits) {
  set({ scenarioBusy: true, scenarioError: null });
  try {
    const scenario = { name: "custom", mode: retrofits.length ? "custom" : "none", retrofits, overrides: {} };
    const result = await api.scenario(state.home, scenario);
    const diff = await api.diff(state.analysis.analysis_id, result.analysis_id);
    set({ scenario: result.scenario, scenarioAnalysis: result, scenarioDiff: diff, scenarioBusy: false });
  } catch (err) {
    if (err.code === "analysis_not_found") { await analyse(); return runScenario(retrofits); }
    set({ scenarioBusy: false, scenarioError: err.message });
  }
}
export function clearScenario() { set({ scenario: null, scenarioAnalysis: null, scenarioDiff: null, scenarioError: null }); }

// ---------- explanations ----------
export async function explain(section, result = state.analysis) {
  const key = `${result.analysis_id}:${section}`;
  if (state.explanations[key]?.text || state.explanations[key]?.loading) return;
  const put = (v) => set((s) => ({ explanations: { ...s.explanations, [key]: v } }));
  put({ loading: true });
  try {
    put(await api.explain(result.analysis_id, section));
  } catch (err) {
    if (err.code === "analysis_not_found" && result === state.analysis) {  // API restarted: recompute once
      const fresh = await analyse();
      return explain(section, fresh);
    }
    put({ error: err.message });
  }
}
export const explanationKey = (result, section) => result ? `${result.analysis_id}:${section}` : null;

// ---------- chat ----------
export async function ask(message) {
  const text = message.trim();
  if (!text || state.chatBusy) return;
  set((s) => ({ chat: [...s.chat, { role: "user", text }], chatBusy: true }));
  try {
    const resp = await api.chat({ session_id: state.sessionId, home: state.home, message: text,
      current_scenario: state.scenario, customer_id: null });
    const turn = { role: "assistant", text: resp.answer, check: resp.check, intent: resp.intent, diff: resp.diff || null };
    const patch = { chat: [...state.chat, turn], chatBusy: false };
    if (resp.scenario && resp.result) Object.assign(patch, { scenario: resp.scenario, scenarioAnalysis: resp.result, scenarioDiff: resp.diff || null });
    set(patch);
  } catch (err) {
    set((s) => ({ chat: [...s.chat, { role: "assistant", text: err.message, error: true }], chatBusy: false }));
  }
}
export function clearChat() { set({ chat: [] }); }
