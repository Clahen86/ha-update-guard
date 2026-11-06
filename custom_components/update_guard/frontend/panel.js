// Update Guard panel: one card per pending update with the verdict, why, and a safe update button.
const T = {
  en: {
    title: "Update Guard", check: "Check now", checked: "Checked", none: "No pending updates", allGood: "Everything is up to date",
    wait: "Wait", check_: "Check first", unknown: "Unknown", safe: "Safe",
    sum: { wait: "to wait with", check: "to check first", unknown: "unknown", safe: "safe" },
    update: "Update safely", tonight: "Tonight", force: "Update anyway", notes: "Release notes",
    why: "Why", news: "New for you", security: "Security fix", versions: "versions in one",
    dead: "Projects that may be dead", deadHint: "Archived or unchanged for years. Look for a replacement.",
    planned: "Planned for tonight", disk: "Free disk space", done: { installed: "Installing…", planned: "Planned for tonight", waiting: "Waiting until the chosen devices are off" },
    menu: "Menu", reports: "reports", forceAsk: "Update Guard says to wait. Install anyway?",
  },
  da: {
    title: "Opdateringsvagt", check: "Tjek nu", checked: "Tjekket", none: "Ingen ventende opdateringer", allGood: "Alt er opdateret",
    wait: "Vent", check_: "Tjek først", unknown: "Ukendt", safe: "Sikker",
    sum: { wait: "at vente med", check: "at tjekke først", unknown: "ukendte", safe: "sikre" },
    update: "Opdater sikkert", tonight: "I nat", force: "Opdater alligevel", notes: "Release notes",
    why: "Hvorfor", news: "Nyt for dig", security: "Sikkerhedsrettelse", versions: "versioner i én",
    dead: "Projekter, der måske er døde", deadHint: "Arkiveret eller uændret i årevis. Kig efter en afløser.",
    planned: "Planlagt i nat", disk: "Ledig diskplads", done: { installed: "Installerer…", planned: "Planlagt i nat", waiting: "Venter, til de valgte enheder er slukket" },
    menu: "Menu", reports: "fejlmeldinger", forceAsk: "Update Guard siger vent. Installer alligevel?",
  },
};
const COLOR = { wait: "#e5484d", check: "#f5a524", unknown: "#8b8d98", safe: "#30a46c", none: "#30a46c" };
const ICON = { wait: "⏸", check: "!", unknown: "?", safe: "✓", none: "✓" };
const KIND = { core: "🏠", app: "🧩", hacs: "🛍️", other: "📟" };

class UpdateGuardPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._open = new Set();
    this._msg = "";
  }
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const sensor = this._sensor();
    const key = sensor ? sensor.last_updated + JSON.stringify(sensor.attributes.planned || []) : "";
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

  _render() {
    const t = this.t;
    const s = this._sensor();
    const a = s?.attributes || {};
    const updates = a.updates || [];
    const level = s?.state && COLOR[s.state] ? s.state : "none";
    const counts = {};
    for (const u of updates) counts[u.level] = (counts[u.level] || 0) + 1;
    const sum = ["wait", "check", "unknown", "safe"].filter((l) => counts[l])
      .map((l) => `<span class="pill" style="--c:${COLOR[l]}"><b>${counts[l]}</b> ${t.sum[l]}</span>`).join("");
    const headline = updates.length ? (level === "safe" ? t.safe : t[level === "check" ? "check_" : level] || "") : t.allGood;
    const checked = a.checked ? new Date(a.checked).toLocaleString(this._hass.language, { dateStyle: "short", timeStyle: "short" }) : "";
    const dead = (a.dead || []).map((d) => `<li><a href="${this._esc(d.url)}" target="_blank" rel="noopener">${this._esc(d.name)}</a> <span class="muted">– ${this._esc(d.why)}</span></li>`).join("");
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; min-height:100vh; background:var(--primary-background-color); color:var(--primary-text-color);
          font-family:var(--paper-font-body1_-_font-family, system-ui, sans-serif); }
        .bar { display:flex; align-items:center; gap:8px; height:56px; padding:0 12px; background:var(--app-header-background-color, var(--primary-color));
          color:var(--app-header-text-color, #fff); position:sticky; top:0; z-index:2; }
        .bar h1 { font-size:20px; font-weight:500; margin:0; flex:1; }
        .bar button { background:transparent; color:inherit; border:1px solid currentColor; border-radius:18px; padding:6px 14px; font:inherit; cursor:pointer; }
        .menu { background:none; border:0; color:inherit; font-size:22px; cursor:pointer; padding:4px 8px; }
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
        .lvl-wait { --c:${COLOR.wait}; } .lvl-check { --c:${COLOR.check}; } .lvl-unknown { --c:${COLOR.unknown}; } .lvl-safe { --c:${COLOR.safe}; }
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
      </style>
      <div class="bar">
        ${this._narrow ? `<button class="menu" data-act="menu" title="${t.menu}">☰</button>` : ""}
        <h1>🛡️ ${t.title}</h1>
        <button data-act="checknow">${t.check}</button>
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
        ${dead ? `<section class="dead card" style="--c:${COLOR.unknown}"><h3>🪦 ${t.dead}</h3><div class="muted">${t.deadHint}</div><ul>${dead}</ul></section>` : ""}
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
      else if (act === "force") { if (confirm(t.forceAsk)) this._install(id, "now", true); }
      else this._install(id, act);
    }));
  }
}
customElements.define("update-guard-panel", UpdateGuardPanel);
