// App shell: loads labels, then renders the top bar, the current route and the footer.
import { html, ReactDOM, useEffect, useState } from "./lib.js";
import { api } from "./api.js";
import { setLabels } from "./labels.js";
import { useRoute, href } from "./router.js";
import { LinkButton, Notice } from "./ui.js";
import { CatalogueScreen } from "./screens/catalogue.js";
import { HomeScreen } from "./screens/home.js";
import { ReportScreen } from "./screens/report.js";
import { LendersScreen } from "./screens/lenders.js";
import { MethodScreen } from "./screens/method.js";

const NAV = [["/", "Homes"], ["/lenders", "For lenders"], ["/how-it-works", "How it works"]];

function Brand() {
  return html`<a class="brand" href="#/" aria-label="Green Home Score, home">
    <span class="brand-mark" aria-hidden="true">
      <i style=${{ width: 13, background: "var(--epc-a)" }}></i><i style=${{ width: 17, background: "var(--epc-c)" }}></i><i style=${{ width: 21, background: "var(--epc-e)" }}></i>
    </span>Green Home Score</a>`;
}

function TopBar({ path }) {
  const section = path === "/" || path.startsWith("/home") || path.startsWith("/report") ? "/" : path;
  return html`<header class="topbar"><div class="container topbar-inner">
    <${Brand} />
    <nav class="nav" aria-label="Main">${NAV.map(([to, text]) => html`<a key=${to} href=${href(to)} aria-current=${section === to ? "page" : undefined}>${text}</a>`)}</nav>
    <div class="topbar-cta"><${LinkButton} href="#/home/new" variant="secondary" size="sm">Assess your home<//></div>
  </div></header>`;
}

function Footer() {
  return html`<footer class="footer"><div class="container footer-inner">
    <span>Green Home Score · estimates from documented models, not guarantees or financial advice.</span>
    <span>England and Wales · public EPC, Land Registry and NEED data</span>
  </div></footer>`;
}

function Route({ route }) {
  const [first, second] = route.parts;
  if (!first) return html`<${CatalogueScreen} />`;
  if (first === "home") return html`<${HomeScreen} id=${second || "new"} />`;
  if (first === "report") return html`<${ReportScreen} />`;
  if (first === "lenders") return html`<${LendersScreen} />`;
  if (first === "how-it-works") return html`<${MethodScreen} />`;
  return html`<div class="container page"><${Notice} title="Page not found">This page doesn't exist. <a href="#/">Browse homes</a>.<//></div>`;
}

function App() {
  const route = useRoute();
  return html`<${TopBar} path=${route.path} /><main id="main"><${Route} route=${route} /></main><${Footer} />`;
}

function BootError({ message }) {
  return html`<div class="container page"><${Notice} tone="bad" title="Green Home Score can't start">${message}<//></div>`;
}

const root = ReactDOM.createRoot(document.getElementById("root"));
api.labels()
  .then((data) => { setLabels(data); root.render(html`<${App} />`); })
  .catch((err) => root.render(html`<${BootError} message=${err.message} />`));
