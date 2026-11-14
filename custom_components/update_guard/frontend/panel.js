// Update Guard panel: one card per pending update with the verdict, why, and a safe update button.
import { defineSupport, supportText } from "./support.js";
const T = {
  en: {
    title: "Update Guard", check: "Check now", checked: "Checked", none: "No pending updates", allGood: "Everything is up to date",
    wait: "Wait", check_: "Check first", unclear: "Unknown", safe: "Safe",
    sum: { wait: "to wait with", check: "to check first", unclear: "unknown", safe: "safe" },
    update: "Update safely", tonight: "Tonight", force: "Update anyway", notes: "Release notes",
    why: "Why", news: "New for you", security: "Security fix", versions: "versions in one",
    dead: "Projects that may be dead", deadHint: "Archived or unchanged for years. Look for a replacement.",
    planned: "Planned for tonight", disk: "Free disk space", done: { installed: "Installing…", planned: "Planned for tonight", waiting: "Waiting until the chosen devices are off" },
    menu: "Menu", reports: "reports", forceAsk: "Update Guard says to wait. Install anyway?",
    settings: "Settings", back: "Back", saved: "Saved ✓",
    s: {
      phone: "Notifications", phoneHint: "Tap the phones that should get a message when a new update shows up.",
      level: "Tell me about", levels: { safe: "Everything", check: "Needs a look", wait: "Only wait" },
      inHa: "Notification in Home Assistant",
      ai: "AI check", aiHint: "An AI double-checks changelog lines found by keywords and drops false alarms. Only the lines and names are sent – never values.", noAi: "Off",
      safety: "Be careful", waitFix: "Wait for the first fix", waitFixHint: "A new monthly Home Assistant release waits until .1 is out or a week has passed. Most problems are fixed in .1.",
      busy: "Don't update while these are running", busyHint: "Safe update waits until they are off (up to 6 hours).", suggest: "Suggestions", search: "Find a device…", noneChosen: "Nothing chosen",
      auto: "Automatic", autoSafe: "Install safe cards and themes at night", autoSafeHint: "Only cards and themes rated Safe, at 04:30. Integrations, apps and Home Assistant are never installed by themselves.",
    },
  },
  da: {
    title: "Opdateringsvagt", check: "Tjek nu", checked: "Tjekket", none: "Ingen ventende opdateringer", allGood: "Alt er opdateret",
    wait: "Vent", check_: "Tjek først", unclear: "Ukendt", safe: "Sikker",
    sum: { wait: "at vente med", check: "at tjekke først", unclear: "ukendte", safe: "sikre" },
    update: "Opdater sikkert", tonight: "I nat", force: "Opdater alligevel", notes: "Release notes",
    why: "Hvorfor", news: "Nyt for dig", security: "Sikkerhedsrettelse", versions: "versioner i én",
    dead: "Projekter, der måske er døde", deadHint: "Arkiveret eller uændret i årevis. Kig efter en afløser.",
    planned: "Planlagt i nat", disk: "Ledig diskplads", done: { installed: "Installerer…", planned: "Planlagt i nat", waiting: "Venter, til de valgte enheder er slukket" },
    menu: "Menu", reports: "fejlmeldinger", forceAsk: "Update Guard siger vent. Installer alligevel?",
    settings: "Indstillinger", back: "Tilbage", saved: "Gemt ✓",
    s: {
      phone: "Besked på telefonen", phoneHint: "Tryk på de telefoner, der skal have besked, når en ny opdatering dukker op.",
      level: "Fortæl mig om", levels: { safe: "Alt", check: "Det, der skal kigges på", wait: "Kun vent" },
      inHa: "Besked i Home Assistant",
      ai: "AI-kontrol", aiHint: "En AI dobbelttjekker linjer fundet med nøgleord og fjerner falske alarmer. Kun linjerne og navne sendes – aldrig værdier.", noAi: "Fra",
      safety: "Forsigtighed", waitFix: "Vent på første rettelse", waitFixHint: "En ny månedsversion af Home Assistant venter, til .1 er ude, eller der er gået en uge. De fleste fejl rettes i .1.",
      busy: "Opdater ikke, mens disse kører", busyHint: "Opdater sikkert venter, til de er slukket (op til 6 timer).", suggest: "Forslag", search: "Find en enhed…", noneChosen: "Intet valgt",
      auto: "Automatik", autoSafe: "Installer sikre kort og temaer om natten", autoSafeHint: "Kun kort og temaer, der er vurderet Sikker, kl. 04:30. Integrationer, apps og Home Assistant installeres aldrig af sig selv.",
    },
  },
};
const COLOR = { wait: "#e5484d", check: "#f5a524", unclear: "#8b8d98", safe: "#30a46c", none: "#30a46c" };
const ICON = { wait: "⏸", check: "!", unclear: "?", safe: "✓", none: "✓" };
const KIND = { core: "🏠", app: "🧩", hacs: "🛍️", other: "📟" };

class UpdateGuardPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._open = new Set();
    this._view = "list";
    this._settings = null;
  }
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const sensor = this._sensor();
    const key = sensor ? sensor.last_updated + JSON.stringify(sensor.attributes.planned || []) : "";
    // In the settings the page is not drawn again on every state change (it would steal the focus).
    if (this._sup) this._sup.hass = hass;
    if ((this._view === "settings" || this._view === "support") && !first) return;
    if (first || key !== this._key || hass.themes?.darkMode !== this._dark) {
      this._key = key;
      this._dark = hass.themes?.darkMode;
      this._render();
    }
  }
  set narrow(v) { this._narrow = v; }
  get t() { return T[(this._hass?.language || "en").startsWith("da") ? "da" : "en"]; }
  _entities(domain) {
    return Object.values(this._hass.entities || {}).filter((e) => e.platform === "update_guard" && e.entity_id.startsWith(domain + "."));
  }
  _sensor() {
    if (!this._hass) return null;
    for (const e of this._entities("sensor")) {
      const s = this._hass.states[e.entity_id];
      if (s && Array.isArray(s.attributes.updates)) return s;
    }
    return null;
  }
  _esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]); }

  async _install(entityId, when, force = false) {
    try {
      const r = await this._hass.callWS({
        type: "call_service", domain: "update_guard", service: "safe_update",
        service_data: { entity_id: entityId, when, force }, return_response: true,
      });
      this._toast(this.t.done[r?.response?.result] || "✓");
    } catch (err) {
      this._toast(err?.message || String(err), true);
    }
  }
  async _checkNow() {
    const button = this._entities("button")[0];
    if (button) await this._hass.callService("button", "press", { entity_id: button.entity_id });
    this._toast("…");
  }
  _toast(text, bad = false) {
    const el = this.shadowRoot.querySelector(".toast");
    if (!el) return;
    el.textContent = text;
    el.className = "toast show" + (bad ? " bad" : "");
    clearTimeout(this._tt);
    this._tt = setTimeout(() => (el.className = "toast"), 4500);
  }

  _card(u, planned) {
    const t = this.t;
    const open = this._open.has(u.entity_id || "core");
    const findings = (u.findings || []).filter((f) => f.affects !== "no");
    const chips = [];
    if (u.security) chips.push(`<span class="chip sec">🔒 ${t.security}</span>`);
    if (u.skipped?.length > 1) chips.push(`<span class="chip">${u.skipped.length} ${t.versions}</span>`);
    if (findings.some((f) => f.source === "reports")) chips.push(`<span class="chip warn">👥 ${t.reports}</span>`);
    if (u.news?.length) chips.push(`<span class="chip new">✨ ${t.news}</span>`);
    const isPlanned = planned.includes(u.entity_id);
    const why = findings.map((f) => {
      const tag = f.affects === "yes" ? `<span class="tag yes">●</span>` : `<span class="tag maybe">○</span>`;
      const where = f.used_in?.length ? `<div class="where">${this._esc(f.used_in.map((x) => x.split(":").slice(1).join(":").trim()).join(", "))}</div>` : "";
      const ai = f.ai ? `<div class="where">🤖 ${this._esc(f.ai)}</div>` : "";
      return `<li>${tag}<div>${f.title ? `<b>${this._esc(f.title)}</b> ` : ""}${this._esc(f.text)}${where}${ai}</div></li>`;
    }).join("");
    const news = (u.news || []).map((n) => `<li><span class="tag new">✨</span><div>${this._esc(n)}</div></li>`).join("");
    const canInstall = !!u.entity_id;
    const buttons = canInstall ? (u.level === "wait"
      ? `<button class="ghost" data-act="force" data-id="${u.entity_id}">${t.force}</button>`
      : `<button class="primary" data-act="now" data-id="${u.entity_id}">${t.update}</button>
         <button class="ghost" data-act="tonight" data-id="${u.entity_id}" ${isPlanned ? "disabled" : ""}>🌙 ${isPlanned ? t.planned : t.tonight}</button>`) : "";
    return `
      <article class="card lvl-${u.level}">
        <div class="head" data-toggle="${u.entity_id || "core"}">
          <div class="badge" style="--c:${COLOR[u.level]}">${ICON[u.level]}</div>
          <div class="title">
            <div class="name">${KIND[u.kind] || ""} ${this._esc(u.name)}</div>
            <div class="ver">${this._esc(u.installed || "?")} → <b>${this._esc(u.latest || "?")}</b></div>
          </div>
          <div class="chev ${open ? "up" : ""}">⌄</div>
        </div>
        <div class="verdict" style="--c:${COLOR[u.level]}">${this._esc(u.verdict || "")}</div>
        ${chips.length ? `<div class="chips">${chips.join("")}</div>` : ""}
        ${open && (why || news) ? `<div class="more">
          ${why ? `<h4>${t.why}</h4><ul>${why}</ul>` : ""}
          ${news ? `<h4>${t.news}</h4><ul>${news}</ul>` : ""}
        </div>` : ""}
        <div class="actions">${buttons}
          ${u.release_url ? `<a class="link" href="${this._esc(u.release_url)}" target="_blank" rel="noopener">${t.notes} ↗</a>` : ""}
        </div>
      </article>`;
  }

  _css() {
    return `<style>
        :host { display:block; min-height:100vh; background:var(--primary-background-color); color:var(--primary-text-color);
          font-family:var(--paper-font-body1_-_font-family, system-ui, sans-serif); }
        .bar { display:flex; align-items:center; gap:8px; height:56px; padding:0 12px; background:var(--app-header-background-color, var(--primary-color));
          color:var(--app-header-text-color, #fff); position:sticky; top:0; z-index:2; }
        .bar h1 { font-size:20px; font-weight:500; margin:0; flex:1; }
        .bar button { background:transparent; color:inherit; border:1px solid currentColor; border-radius:18px; padding:6px 14px; font:inherit; cursor:pointer; }
        .bar .gear { border:0; font-size:20px; padding:4px 8px; }
        .bar .menu { background:none; border:0; color:inherit; font-size:22px; cursor:pointer; padding:4px 8px; }
        main { max-width:880px; margin:0 auto; padding:16px; box-sizing:border-box; }
        .hero { display:flex; gap:16px; align-items:center; padding:20px; border-radius:16px; margin-bottom:16px;
          background:linear-gradient(135deg, color-mix(in srgb, var(--c) 22%, var(--card-background-color)), var(--card-background-color));
          box-shadow:var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,.12)); }
        .ring { width:64px; height:64px; border-radius:50%; display:grid; place-items:center; font-size:30px; color:#fff; background:var(--c);
          box-shadow:0 0 0 6px color-mix(in srgb, var(--c) 25%, transparent); flex:none; }
        .hero h2 { margin:0 0 6px; font-size:22px; }
        .pills { display:flex; flex-wrap:wrap; gap:6px; }
        .pill { font-size:13px; padding:3px 10px; border-radius:12px; background:color-mix(in srgb, var(--c) 18%, transparent); }
        .muted { color:var(--secondary-text-color); font-size:13px; }
        .grid { display:grid; gap:12px; }
        .card { background:var(--card-background-color); border-radius:14px; padding:14px; box-shadow:var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,.12));
          border-left:4px solid var(--c, transparent); animation:in .25s ease; }
        .lvl-wait { --c:${COLOR.wait}; } .lvl-check { --c:${COLOR.check}; } .lvl-unclear { --c:${COLOR.unclear}; } .lvl-safe { --c:${COLOR.safe}; }
        @keyframes in { from { opacity:0; transform:translateY(4px); } }
        .head { display:flex; align-items:center; gap:12px; cursor:pointer; }
        .badge { width:36px; height:36px; border-radius:50%; background:var(--c); color:#fff; display:grid; place-items:center; font-weight:700; flex:none; }
        .title { flex:1; min-width:0; }
        .name { font-weight:600; font-size:16px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .ver { font-size:13px; color:var(--secondary-text-color); }
        .chev { transition:transform .2s; color:var(--secondary-text-color); font-size:20px; }
        .chev.up { transform:rotate(180deg); }
        .verdict { margin:10px 0 0; padding:8px 10px; border-radius:10px; font-size:14px; background:color-mix(in srgb, var(--c) 12%, transparent); }
        .chips { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
        .chip { font-size:12px; padding:2px 8px; border-radius:10px; background:var(--secondary-background-color); }
        .chip.sec { background:color-mix(in srgb, #3e63dd 20%, transparent); }
        .chip.warn { background:color-mix(in srgb, ${COLOR.check} 22%, transparent); }
        .chip.new { background:color-mix(in srgb, #8e4ec6 20%, transparent); }
        .more h4 { margin:12px 0 6px; font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--secondary-text-color); }
        .more ul { list-style:none; margin:0; padding:0; display:grid; gap:8px; }
        .more li { display:flex; gap:8px; font-size:14px; line-height:1.4; }
        .tag { flex:none; width:16px; text-align:center; }
        .tag.yes { color:${COLOR.wait}; } .tag.maybe { color:${COLOR.check}; }
        .where { font-size:12px; color:var(--secondary-text-color); margin-top:2px; }
        .actions { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:12px; }
        button.primary, button.ghost { font:inherit; font-size:14px; border-radius:18px; padding:7px 14px; cursor:pointer; border:1px solid var(--primary-color); }
        button.primary { background:var(--primary-color); color:var(--text-primary-color, #fff); }
        button.ghost { background:transparent; color:var(--primary-color); }
        button:disabled { opacity:.6; cursor:default; }
        .link { margin-left:auto; font-size:13px; color:var(--primary-color); text-decoration:none; }
        section.dead { margin-top:20px; }
        section.dead h3 { font-size:16px; margin:0 0 4px; }
        section.dead ul { margin:8px 0 0; padding-left:18px; }
        section.dead a { color:var(--primary-color); }
        .empty { text-align:center; padding:48px 16px; color:var(--secondary-text-color); }
        .empty .big { font-size:48px; }
        footer { margin:20px 0 40px; display:flex; flex-wrap:wrap; gap:16px; }
        .toast { position:fixed; left:50%; bottom:24px; transform:translate(-50%, 80px); background:#323232; color:#fff; padding:10px 18px;
          border-radius:10px; font-size:14px; opacity:0; transition:.25s; z-index:9; max-width:90vw; }
        .toast.show { transform:translate(-50%, 0); opacity:1; } .toast.bad { background:${COLOR.wait}; }
        @media (max-width:600px) { main { padding:12px; } .hero { padding:14px; } .ring { width:52px; height:52px; font-size:24px; } }
      </style>`;
  }

  _render() {
    if (this._view === "settings") return this._renderSettings();
    if (this._view === "support") return this._renderSupport();
    const t = this.t;
    const s = this._sensor();
    const a = s?.attributes || {};
    const updates = a.updates || [];
    const level = s?.state && COLOR[s.state] ? s.state : "none";
    const counts = {};
    for (const u of updates) counts[u.level] = (counts[u.level] || 0) + 1;
    const sum = ["wait", "check", "unclear", "safe"].filter((l) => counts[l])
      .map((l) => `<span class="pill" style="--c:${COLOR[l]}"><b>${counts[l]}</b> ${t.sum[l]}</span>`).join("");
    const headline = updates.length ? (level === "safe" ? t.safe : t[level === "check" ? "check_" : level] || "") : t.allGood;
    const checked = a.checked ? new Date(a.checked).toLocaleString(this._hass.language, { dateStyle: "short", timeStyle: "short" }) : "";
    const dead = (a.dead || []).map((d) => `<li><a href="${this._esc(d.url)}" target="_blank" rel="noopener">${this._esc(d.name)}</a> <span class="muted">– ${this._esc(d.why)}</span></li>`).join("");
    this.shadowRoot.innerHTML = `
      ${this._css()}
      <div class="bar">
        ${this._narrow ? `<button class="menu" data-act="menu" title="${t.menu}">☰</button>` : ""}
        <h1>🛡️ ${t.title}</h1>
        <button data-act="help">🛟 ${supportText(this._hass, "help")}</button>
        <button data-act="checknow">${t.check}</button>
        <button class="gear" data-act="settings" title="${t.settings}">⚙️</button>
      </div>
      <main>
        <div class="hero" style="--c:${COLOR[level]}">
          <div class="ring">${ICON[level]}</div>
          <div>
            <h2>${headline}</h2>
            <div class="pills">${sum || `<span class="muted">${t.none}</span>`}</div>
            ${checked ? `<div class="muted" style="margin-top:6px">${t.checked} ${checked}</div>` : ""}
          </div>
        </div>
        ${updates.length ? `<div class="grid">${updates.map((u) => this._card(u, a.planned || [])).join("")}</div>`
          : `<div class="empty"><div class="big">🎉</div>${t.allGood}</div>`}
        ${dead ? `<section class="dead card" style="--c:${COLOR.unclear}"><h3>🪦 ${t.dead}</h3><div class="muted">${t.deadHint}</div><ul>${dead}</ul></section>` : ""}
        <footer class="muted">
          ${a.disk_free != null ? `<span>💾 ${t.disk}: ${Number(a.disk_free).toFixed(1)} GB</span>` : ""}
          ${(a.planned || []).length ? `<span>🌙 ${t.planned}: ${(a.planned || []).length}</span>` : ""}
        </footer>
      </main>
      <div class="toast"></div>`;
    this.shadowRoot.querySelectorAll("[data-toggle]").forEach((el) => el.addEventListener("click", () => {
      const id = el.dataset.toggle;
      this._open.has(id) ? this._open.delete(id) : this._open.add(id);
      this._render();
    }));
    this.shadowRoot.querySelectorAll("[data-act]").forEach((el) => el.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const { act, id } = el.dataset;
      if (act === "menu") this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }));
      else if (act === "checknow") this._checkNow();
      else if (act === "settings") this._openSettings();
      else if (act === "help") { this._view = "support"; this._render(); }
      else if (act === "force") { if (confirm(t.forceAsk)) this._install(id, "now", true); }
      else this._install(id, act);
    }));
  }
}
// Help and answers from the developer (support.js) - one element kept, so a half-written message isn't lost.
UpdateGuardPanel.prototype._renderSupport = function () {
  const t = this.t;
  this.shadowRoot.innerHTML = `${this._css()}
    <div class="bar"><button class="menu" data-act="back" title="${t.back}">←</button><h1>🛟 ${supportText(this._hass, "help")}</h1></div>
    <main id="support-slot"></main>`;
  this._sup = this._sup || document.createElement(defineSupport("update_guard"));
  this._sup.hass = this._hass;
  this.shadowRoot.getElementById("support-slot").appendChild(this._sup);
  this.shadowRoot.querySelector('[data-act="back"]').addEventListener("click", () => { this._view = "list"; this._key = null; this._render(); });
};
UpdateGuardPanel.prototype._openSettings = async function () {
  try {
    this._settings = await this._hass.callWS({ type: "update_guard/settings" });
  } catch (err) {
    this._toast(err?.message || String(err), true);
    return;
  }
  this._view = "settings";
  this._render();
};

UpdateGuardPanel.prototype._save = async function (change) {
  Object.assign(this._settings.options, change);
  try {
    await this._hass.callWS({ type: "update_guard/save_settings", ...change });
    this._toast(this.t.saved);
  } catch (err) {
    this._toast(err?.message || String(err), true);
  }
};

UpdateGuardPanel.prototype._name = function (entityId) {
  const st = this._hass.states[entityId];
  return st?.attributes?.friendly_name || entityId;
};

UpdateGuardPanel.prototype._phone = function (service) {
  if (service === "notify.persistent_notification") return "🔔 " + this.t.s.inHa;
  const raw = service.replace(/^notify\./, "").replace(/^mobile_app_/, "");
  return "📱 " + raw.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
};

UpdateGuardPanel.prototype._renderSettings = function () {
  const t = this.t, s = t.s, d = this._settings, o = d.options;
  const toggle = (key, title, hint, icon) => `
    <label class="row">
      <div class="rtext"><div class="rtitle">${icon} ${title}</div><div class="muted">${hint}</div></div>
      <span class="switch"><input type="checkbox" data-bool="${key}" ${o[key] ? "checked" : ""}><span class="knob"></span></span>
    </label>`;
  const phones = d.notify_services.map((svc) => `<button class="pick ${o.notify.includes(svc) ? "on" : ""}" data-notify="${this._esc(svc)}">${this._esc(this._phone(svc))}</button>`).join("");
  const levels = ["safe", "check", "wait"].map((l) => `<button class="${o.notify_level === l ? "on" : ""}" data-level="${l}">${s.levels[l]}</button>`).join("");
  const ai = [`<option value="">${s.noAi}</option>`, ...d.ai_tasks.map((e) => `<option value="${e}" ${o.ai_task === e ? "selected" : ""}>${this._esc(this._name(e))}</option>`)].join("");
  const chosen = o.blockers.map((e) => `<span class="pick on">${this._esc(this._name(e))}<button class="x" data-unblock="${e}" title="✕">✕</button></span>`).join("") || `<span class="muted">${s.noneChosen}</span>`;
  const sugg = d.suggested_blockers.filter((e) => !o.blockers.includes(e)).map((e) => `<button class="pick" data-block="${e}">+ ${this._esc(this._name(e))}</button>`).join("");
  const all = Object.keys(this._hass.states).filter((e) => /^(switch|binary_sensor|sensor|input_boolean|media_player|vacuum)\./.test(e))
    .map((e) => `<option value="${e}">${this._esc(this._name(e))}</option>`).join("");
  this.shadowRoot.innerHTML = `
    ${this._css()}
    <style>
      .sgrid { display:grid; gap:14px; }
      .sec h3 { margin:0 0 4px; font-size:17px; display:flex; gap:8px; align-items:center; }
      .sec > .muted { margin-bottom:12px; }
      .picks { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
      .pick { font:inherit; font-size:14px; padding:7px 12px; border-radius:18px; border:1px solid var(--divider-color, #ccc);
        background:transparent; color:var(--primary-text-color); cursor:pointer; display:inline-flex; align-items:center; gap:6px; transition:.15s; }
      .pick.on { background:color-mix(in srgb, var(--primary-color) 18%, transparent); border-color:var(--primary-color); }
      .x { border:0; background:none; color:inherit; cursor:pointer; padding:0 0 0 4px; font-size:13px; opacity:.7; }
      .seg { display:flex; border:1px solid var(--divider-color, #ccc); border-radius:12px; overflow:hidden; margin-top:10px; }
      .seg button { flex:1; font:inherit; font-size:14px; padding:9px 6px; border:0; background:transparent; color:var(--primary-text-color); cursor:pointer; }
      .seg button.on { background:var(--primary-color); color:var(--text-primary-color, #fff); }
      .row { display:flex; gap:12px; align-items:center; cursor:pointer; padding:4px 0; }
      .row + .row { border-top:1px solid var(--divider-color, #eee); padding-top:12px; margin-top:8px; }
      .rtext { flex:1; } .rtitle { font-weight:600; margin-bottom:2px; }
      .switch { position:relative; width:46px; height:28px; flex:none; }
      .switch input { opacity:0; width:0; height:0; position:absolute; }
      .knob { position:absolute; inset:0; border-radius:14px; background:var(--disabled-color, #bbb); transition:.2s; }
      .knob::after { content:""; position:absolute; width:22px; height:22px; left:3px; top:3px; border-radius:50%; background:#fff; transition:.2s; box-shadow:0 1px 3px rgba(0,0,0,.3); }
      .switch input:checked + .knob { background:var(--primary-color); }
      .switch input:checked + .knob::after { transform:translateX(18px); }
      select, input.search { width:100%; box-sizing:border-box; font:inherit; padding:10px 12px; border-radius:10px; margin-top:10px;
        border:1px solid var(--divider-color, #ccc); background:var(--card-background-color); color:var(--primary-text-color); }
      .sub { font-size:13px; font-weight:600; color:var(--secondary-text-color); margin-top:12px; }
    </style>
    <div class="bar">
      <button class="menu" data-act="back" title="${t.back}">←</button>
      <h1>⚙️ ${t.settings}</h1>
    </div>
    <main><div class="sgrid">
      <section class="card sec">
        <h3>📲 ${s.phone}</h3><div class="muted">${s.phoneHint}</div>
        <div class="picks">${phones}</div>
        <div class="sub">${s.level}</div>
        <div class="seg">${levels}</div>
      </section>
      <section class="card sec">
        <h3>🛡️ ${s.safety}</h3>
        ${toggle("wait_for_fix", s.waitFix, s.waitFixHint, "⏳")}
      </section>
      <section class="card sec">
        <h3>🧺 ${s.busy}</h3><div class="muted">${s.busyHint}</div>
        <div class="picks">${chosen}</div>
        ${sugg ? `<div class="sub">${s.suggest}</div><div class="picks">${sugg}</div>` : ""}
        <input class="search" list="ug-ents" placeholder="${s.search}" data-search>
        <datalist id="ug-ents">${all}</datalist>
      </section>
      <section class="card sec">
        <h3>🌙 ${s.auto}</h3>
        ${toggle("auto_safe", s.autoSafe, s.autoSafeHint, "🎨")}
      </section>
      <section class="card sec">
        <h3>🤖 ${s.ai}</h3><div class="muted">${s.aiHint}</div>
        <select data-ai>${ai}</select>
      </section>
    </div></main>
    <div class="toast"></div>`;
  const root = this.shadowRoot;
  const redraw = () => this._renderSettings();
  root.querySelector('[data-act="back"]').addEventListener("click", () => { this._view = "list"; this._key = null; this._render(); });
  root.querySelectorAll("[data-notify]").forEach((el) => el.addEventListener("click", async () => {
    const svc = el.dataset.notify, cur = o.notify;
    await this._save({ notify: cur.includes(svc) ? cur.filter((x) => x !== svc) : [...cur, svc] });
    redraw();
  }));
  root.querySelectorAll("[data-level]").forEach((el) => el.addEventListener("click", async () => { await this._save({ notify_level: el.dataset.level }); redraw(); }));
  root.querySelectorAll("[data-bool]").forEach((el) => el.addEventListener("change", () => this._save({ [el.dataset.bool]: el.checked })));
  root.querySelector("[data-ai]").addEventListener("change", (ev) => this._save({ ai_task: ev.target.value || null }));
  root.querySelectorAll("[data-block]").forEach((el) => el.addEventListener("click", async () => { await this._save({ blockers: [...o.blockers, el.dataset.block] }); redraw(); }));
  root.querySelectorAll("[data-unblock]").forEach((el) => el.addEventListener("click", async (ev) => {
    ev.preventDefault();
    await this._save({ blockers: o.blockers.filter((x) => x !== el.dataset.unblock) });
    redraw();
  }));
  root.querySelector("[data-search]").addEventListener("change", async (ev) => {
    const id = ev.target.value.trim();
    if (this._hass.states[id] && !o.blockers.includes(id)) { await this._save({ blockers: [...o.blockers, id] }); redraw(); }
  });
};

customElements.define("update-guard-panel", UpdateGuardPanel);
