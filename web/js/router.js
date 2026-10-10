// Tiny hash router: #/path/:param. navigate("/report"), useRoute() → { path, parts, query }.
import { useSyncExternalStore } from "./lib.js";

function current() {
  const raw = (location.hash || "#/").slice(1) || "/";
  const [path, qs] = raw.split("?");
  return { path, parts: path.split("/").filter(Boolean), query: Object.fromEntries(new URLSearchParams(qs || "")) };
}
let snapshot = current();
const listeners = new Set();
window.addEventListener("hashchange", () => { snapshot = current(); listeners.forEach((l) => l()); window.scrollTo(0, 0); });

export function navigate(path) { if (location.hash !== `#${path}`) location.hash = path; }
export function useRoute() { return useSyncExternalStore((cb) => { listeners.add(cb); return () => listeners.delete(cb); }, () => snapshot); }
export const href = (path) => `#${path}`;
