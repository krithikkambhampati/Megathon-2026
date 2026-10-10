// Log in / create account. Shown instead of the app until there is a session (store.restoreSession).
import { html, useState } from "../lib.js";
import { login, signup } from "../store.js";
import { Button, Field, Notice } from "../ui.js";

export function AuthScreen() {
  const [mode, setMode] = useState("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const isSignup = mode === "signup";

  async function submit(e) {
    e.preventDefault();
    if (isSignup && !name.trim()) return setError("Please enter your name.");
    if (isSignup && password.length < 8) return setError("Use a password of at least 8 characters.");
    setBusy(true); setError(null);
    try {
      await (isSignup ? signup(name.trim(), email.trim(), password) : login(email.trim(), password));
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }
  const switchTo = (m) => { setMode(m); setError(null); };

  return html`<div class="container page auth-page">
    <div class="card card-pad auth-card">
      <div class="stack gap-2">
        <span class="eyebrow">Green Home Score</span>
        <h1 class="auth-title">${isSignup ? "Create your account" : "Welcome back"}</h1>
        <p class="muted">${isSignup
          ? "Save your homes, reports and questions, and pick up where you left off."
          : "Log in to see your homes and reports."}</p>
      </div>
      <form class="stack gap-4" onSubmit=${submit} noValidate>
        ${isSignup && html`<${Field} label="Name"><input class="input" autocomplete="name" value=${name}
          onInput=${(e) => setName(e.target.value)} required /><//>`}
        <${Field} label="Email"><input class="input" type="email" autocomplete="email" value=${email}
          onInput=${(e) => setEmail(e.target.value)} required /><//>
        <${Field} label="Password" hint=${isSignup ? "At least 8 characters." : null}><input class="input" type="password"
          autocomplete=${isSignup ? "new-password" : "current-password"} value=${password}
          onInput=${(e) => setPassword(e.target.value)} required /><//>
        ${error && html`<${Notice} tone="bad">${error}<//>`}
        <${Button} type="submit" size="lg" loading=${busy} className="auth-submit">${isSignup ? "Create account" : "Log in"}<//>
      </form>
      <p class="small muted auth-switch">${isSignup
        ? html`Already have an account? <button type="button" class="link-btn" onClick=${() => switchTo("login")}>Log in</button>`
        : html`New here? <button type="button" class="link-btn" onClick=${() => switchTo("signup")}>Create an account</button>`}</p>
    </div>
  </div>`;
}
