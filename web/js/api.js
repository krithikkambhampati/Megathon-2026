// The only place the app talks to the API (/v1/*). Every error becomes an ApiError with a readable message.
export class ApiError extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}

const FRIENDLY = {
  0: "We couldn't reach the Green Home Score service. Check that it's running and try again.",
  503: "This part of the service isn't available right now.",
  500: "Something went wrong on our side. Please try again.",
};

let onUnauthorized = null;
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

async function request(method, path, body, { timeoutMs = 20000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(`/v1${path}`, {
      method, signal: ctrl.signal,
      headers: body ? { "content-type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new ApiError(0, e.name === "AbortError" ? "timeout" : "unreachable",
      e.name === "AbortError" ? "This is taking longer than expected. Please try again." : FRIENDLY[0]);
  } finally { clearTimeout(timer); }
  if (res.status === 204) return null;
  if (res.ok) return res.json();
  let code = `http_${res.status}`, message = FRIENDLY[res.status] || FRIENDLY[500];
  try {
    const err = (await res.json()).error;
    code = err.code;
    if (path.startsWith("/auth/")) message = res.status === 422
      ? "Please check your details: a valid email, and a password of at least 8 characters." : err.message;
    else if (res.status === 422) message = "Some of the details don't look right. Please check them and try again.";
    else if (res.status === 404) message = err.message;
    else if (res.status === 401) { message = "Your session has ended. Please log in again."; onUnauthorized?.(); }
  } catch { /* keep the friendly default */ }
  throw new ApiError(res.status, code, message);
}

export const api = {
  me: () => request("GET", "/auth/me"),
  login: (email, password) => request("POST", "/auth/login", { email, password }),
  signup: (name, email, password) => request("POST", "/auth/signup", { name, email, password }),
  logout: () => request("POST", "/auth/logout"),
  labels: () => request("GET", "/labels"),
  catalogue: () => request("GET", "/catalogue", null, { timeoutMs: 60000 }),
  example: (id) => request("GET", `/examples/${encodeURIComponent(id)}`),
  analyse: (home) => request("POST", "/analyse", { home }),
  scenario: (home, scenario) => request("POST", "/scenario", { home, scenario }),
  diff: (baseId, newId) => request("POST", "/diff", { base_analysis_id: baseId, new_analysis_id: newId }),
  explain: (analysisId, section) => request("POST", "/explain", { analysis_id: analysisId, section }, { timeoutMs: 32000 }),
  chat: (req) => request("POST", "/chat", req, { timeoutMs: 32000 }),
  portfolio: (params = {}) => request("GET", `/portfolio?${new URLSearchParams({ limit: 500, ...params })}`),
  methodology: () => request("GET", "/methodology"),
};
