// Help and answers - the same file in each of Clahen86's integrations (keep the copies alike).
// defineSupport("replace_device") defines <ha-support-replace-device>: give it .hass and put it in the panel.
// Outside Home Assistant (an add-on's own page): give it .api = (action, data) => Promise and .lang instead.
// Get help (message, up to 3 pictures, a short diagnosis), answers from the developer (write back, Close), and the
// switch for sending errors anonymously. Talks to the integration over the websocket "<domain>/support".

const T = {
  da: { help: "Hjælp", title: "Få hjælp", sub: "Skriv hvad der er galt, og vedhæft gerne billeder. Udvikleren får også en kort diagnose.", ph: "Hvad er der galt? (valgfrit)", attach: "Vedhæft billeder", max3: "Højst 3 billeder", whatq: "Hvad bliver sendt?", what: ["Din besked og dine billeder", "Version, Home Assistant-version, land og sprog", "Dine valg (kun tal og til/fra)", "Antal og fejl i appen"], no: "Ingen navne på enheder, rum eller personer, ingen adresser eller koder. Kun udvikleren ser det.", send: "Send", sending: "Sender …", sent: "Sendt ✓ – dit nummer er {id}. Du får en besked i Home Assistant, når udvikleren svarer.", fail: "Kunne ikke sende lige nu. Prøv igen om lidt.", newOne: "Skriv en ny", answer: "Svar fra udvikleren", note: "Besked fra udvikleren om en fejl", dev: "Udvikleren", you: "Dig", wait: "Venter på svar – du får en besked i Home Assistant.", back: "Skriv tilbage …", sendBack: "Send svar", sentBack: "Sendt ✓", close: "Luk", share: "Send fejl anonymt", shareH: "Fejl i appen sendes uden navne, så de kan blive rettet – og udvikleren kan skrive til dig om dem." },
  en: { help: "Help", title: "Get help", sub: "Tell what's wrong and attach pictures if you like. The developer also gets a short diagnosis.", ph: "What's wrong? (optional)", attach: "Attach pictures", max3: "At most 3 pictures", whatq: "What is sent?", what: ["Your message and pictures", "Version, Home Assistant version, country and language", "Your choices (numbers and on/off only)", "Counts and errors in the app"], no: "No names of devices, rooms or people, no addresses or passwords. Only the developer sees it.", send: "Send", sending: "Sending …", sent: "Sent ✓ – your number is {id}. You'll get a notification in Home Assistant when the developer answers.", fail: "Couldn't send right now. Try again in a moment.", newOne: "Write a new one", answer: "Answer from the developer", note: "Message from the developer about an error", dev: "Developer", you: "You", wait: "Waiting for an answer – you'll get a notification in Home Assistant.", back: "Write back …", sendBack: "Send reply", sentBack: "Sent ✓", close: "Close", share: "Send errors anonymously", shareH: "Errors in the app are sent without names so they can be fixed – and the developer can write to you about them." },
  de: { help: "Hilfe", title: "Hilfe holen", sub: "Beschreibe, was nicht stimmt, und hänge gern Bilder an. Der Entwickler bekommt auch eine kurze Diagnose.", ph: "Was ist falsch? (optional)", attach: "Bilder anhängen", max3: "Höchstens 3 Bilder", whatq: "Was wird gesendet?", what: ["Deine Nachricht und Bilder", "Version, Home-Assistant-Version, Land und Sprache", "Deine Einstellungen (nur Zahlen und ein/aus)", "Anzahlen und Fehler in der App"], no: "Keine Namen von Geräten, Räumen oder Personen, keine Adressen oder Passwörter. Nur der Entwickler sieht es.", send: "Senden", sending: "Sende …", sent: "Gesendet ✓ – deine Nummer ist {id}. Du bekommst eine Meldung in Home Assistant, wenn der Entwickler antwortet.", fail: "Senden geht gerade nicht. Versuche es gleich noch einmal.", newOne: "Neue schreiben", answer: "Antwort vom Entwickler", note: "Nachricht vom Entwickler zu einem Fehler", dev: "Entwickler", you: "Du", wait: "Warte auf Antwort – du bekommst eine Meldung in Home Assistant.", back: "Antworten …", sendBack: "Antwort senden", sentBack: "Gesendet ✓", close: "Schließen", share: "Fehler anonym senden", shareH: "Fehler in der App werden ohne Namen gesendet, damit sie behoben werden – und der Entwickler kann dir dazu schreiben." },
  fr: { help: "Aide", title: "Obtenir de l'aide", sub: "Décrivez le problème et joignez des images si vous voulez. Le développeur reçoit aussi un court diagnostic.", ph: "Quel est le problème ? (facultatif)", attach: "Joindre des images", max3: "3 images maximum", whatq: "Qu'est-ce qui est envoyé ?", what: ["Votre message et vos images", "Version, version de Home Assistant, pays et langue", "Vos choix (nombres et oui/non seulement)", "Comptes et erreurs de l'app"], no: "Aucun nom d'appareil, de pièce ou de personne, aucune adresse ni mot de passe. Seul le développeur le voit.", send: "Envoyer", sending: "Envoi …", sent: "Envoyé ✓ – votre numéro est {id}. Vous serez prévenu dans Home Assistant quand le développeur répondra.", fail: "Envoi impossible pour l'instant. Réessayez dans un moment.", newOne: "En écrire un autre", answer: "Réponse du développeur", note: "Message du développeur sur une erreur", dev: "Développeur", you: "Vous", wait: "En attente de réponse – vous serez prévenu dans Home Assistant.", back: "Répondre …", sendBack: "Envoyer", sentBack: "Envoyé ✓", close: "Fermer", share: "Envoyer les erreurs anonymement", shareH: "Les erreurs de l'app sont envoyées sans noms pour être corrigées – et le développeur peut vous écrire à leur sujet." },
  nl: { help: "Hulp", title: "Hulp vragen", sub: "Vertel wat er mis is en voeg gerust afbeeldingen toe. De ontwikkelaar krijgt ook een korte diagnose.", ph: "Wat is er mis? (optioneel)", attach: "Afbeeldingen toevoegen", max3: "Maximaal 3 afbeeldingen", whatq: "Wat wordt verstuurd?", what: ["Je bericht en afbeeldingen", "Versie, Home Assistant-versie, land en taal", "Je keuzes (alleen getallen en aan/uit)", "Aantallen en fouten in de app"], no: "Geen namen van apparaten, ruimtes of personen, geen adressen of wachtwoorden. Alleen de ontwikkelaar ziet het.", send: "Versturen", sending: "Versturen …", sent: "Verstuurd ✓ – je nummer is {id}. Je krijgt een melding in Home Assistant als de ontwikkelaar antwoordt.", fail: "Versturen lukt nu niet. Probeer het zo opnieuw.", newOne: "Nieuw bericht", answer: "Antwoord van de ontwikkelaar", note: "Bericht van de ontwikkelaar over een fout", dev: "Ontwikkelaar", you: "Jij", wait: "Wacht op antwoord – je krijgt een melding in Home Assistant.", back: "Reageren …", sendBack: "Reactie versturen", sentBack: "Verstuurd ✓", close: "Sluiten", share: "Fouten anoniem versturen", shareH: "Fouten in de app worden zonder namen verstuurd zodat ze opgelost worden – en de ontwikkelaar kan je erover schrijven." },
  sv: { help: "Hjälp", title: "Få hjälp", sub: "Skriv vad som är fel och bifoga gärna bilder. Utvecklaren får också en kort diagnos.", ph: "Vad är fel? (valfritt)", attach: "Bifoga bilder", max3: "Högst 3 bilder", whatq: "Vad skickas?", what: ["Ditt meddelande och dina bilder", "Version, Home Assistant-version, land och språk", "Dina val (bara siffror och på/av)", "Antal och fel i appen"], no: "Inga namn på enheter, rum eller personer, inga adresser eller lösenord. Bara utvecklaren ser det.", send: "Skicka", sending: "Skickar …", sent: "Skickat ✓ – ditt nummer är {id}. Du får ett meddelande i Home Assistant när utvecklaren svarar.", fail: "Kunde inte skicka just nu. Försök igen om en stund.", newOne: "Skriv ett nytt", answer: "Svar från utvecklaren", note: "Meddelande från utvecklaren om ett fel", dev: "Utvecklaren", you: "Du", wait: "Väntar på svar – du får ett meddelande i Home Assistant.", back: "Svara …", sendBack: "Skicka svar", sentBack: "Skickat ✓", close: "Stäng", share: "Skicka fel anonymt", shareH: "Fel i appen skickas utan namn så att de kan rättas – och utvecklaren kan skriva till dig om dem." },
  nb: { help: "Hjelp", title: "Få hjelp", sub: "Skriv hva som er galt, og legg gjerne ved bilder. Utvikleren får også en kort diagnose.", ph: "Hva er galt? (valgfritt)", attach: "Legg ved bilder", max3: "Maks 3 bilder", whatq: "Hva blir sendt?", what: ["Meldingen og bildene dine", "Versjon, Home Assistant-versjon, land og språk", "Valgene dine (bare tall og av/på)", "Antall og feil i appen"], no: "Ingen navn på enheter, rom eller personer, ingen adresser eller passord. Bare utvikleren ser det.", send: "Send", sending: "Sender …", sent: "Sendt ✓ – nummeret ditt er {id}. Du får beskjed i Home Assistant når utvikleren svarer.", fail: "Kunne ikke sende nå. Prøv igjen om litt.", newOne: "Skriv en ny", answer: "Svar fra utvikleren", note: "Melding fra utvikleren om en feil", dev: "Utvikleren", you: "Du", wait: "Venter på svar – du får beskjed i Home Assistant.", back: "Svar …", sendBack: "Send svar", sentBack: "Sendt ✓", close: "Lukk", share: "Send feil anonymt", shareH: "Feil i appen sendes uten navn så de kan rettes – og utvikleren kan skrive til deg om dem." },
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function shrink(file) {  // at most 1600 px as JPEG - a phone photo becomes ~300 kB
  return new Promise((ok) => {
    const img = new Image(), url = URL.createObjectURL(file);
    img.onload = () => {
      const k = Math.min(1, 1600 / Math.max(img.width, img.height)), c = document.createElement("canvas");
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(url);
      ok({ name: file.name, url: c.toDataURL("image/jpeg", 0.8) });
    };
    img.onerror = () => { URL.revokeObjectURL(url); ok(null); };
    img.src = url;
  });
}

export function supportText(hass, key) {
  const l = (hass?.language || "en").split("-")[0];
  return (T[l] || T.en)[key];
}

export function defineSupport(domain) {
  const name = `ha-support-${domain.replaceAll("_", "-")}`;
  if (customElements.get(name)) return name;
  customElements.define(name, class extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this.s = null; this.state = null; this.note = ""; this.imgs = []; this.back = ""; this.backState = null;
      this.shadowRoot.addEventListener("click", (e) => this.click(e));
      this.shadowRoot.addEventListener("input", (e) => {
        if (e.target.name === "note") this.note = e.target.value;
        if (e.target.name === "back") this.back = e.target.value;
      });
      this.shadowRoot.addEventListener("change", (e) => this.files(e));
    }
    set hass(h) { const first = !this._hass; this._hass = h; if (first) this.start(); }
    connectedCallback() { if (this.api) this.start(); }
    start() { if (this._started) return; this._started = true; this.render(); this.call("status"); }
    get t() { const l = (this.lang || this._hass?.language || "en").split("-")[0]; return T[l] || T.en; }
    async call(action, data = {}) {
      try { this.s = this.api ? await this.api(action, data) : await this._hass.callWS({ type: `${domain}/support`, action, ...data }); } catch (e) { this.s = { ...(this.s || {}), error: true }; }
      this.render();
      return this.s;
    }
    async files(e) {
      if (!e.target.matches("[data-file]")) return;
      for (const f of [...e.target.files].slice(0, 3 - this.imgs.length)) { const x = await shrink(f); if (x) this.imgs.push(x); }
      this.render();
    }
    async click(e) {
      const b = e.target.closest("[data-a]");
      if (!b) return;
      const a = b.dataset.a;
      if (a === "send") {
        this.state = "sending"; this.render();
        const r = await this.call("send", { note: this.note, images: this.imgs.map((x) => ({ name: x.name, data: x.url.split(",")[1] })) });
        this.state = r?.ok ? { id: r.id } : "fail";
        if (r?.ok) { this.note = ""; this.imgs = []; }
      } else if (a === "new") this.state = null;
      else if (a === "rm") this.imgs.splice(Number(b.dataset.i), 1);
      else if (a === "hide") await this.call("hide", { key: b.dataset.key });
      else if (a === "share") await this.call("share", { on: !(this.s?.share ?? true) });
      else if (a === "back" && this.back.trim()) {
        this.backState = "sending"; this.render();
        const r = await this.call("reply", { id: b.dataset.id, text: this.back.trim() });
        this.backState = r?.ok ? "sent" : "fail";
        if (r?.ok) this.back = "";
      }
      this.render();
    }
    render() {
      const t = this.t, s = this.s || {}, ans = s.answers || {}, last = s.last_help?.id;
      const closeBtn = (k) => `<button class="link close" data-a="hide" data-key="${esc(k)}">${t.close}</button>`;
      const notes = (ans.notes || []).filter((x) => x.msgs?.length).map((x) => `<div class="card">${closeBtn(x.key)}<b>💬 ${t.note}</b>
        ${x.msgs.map((m) => `<p class="msg dev">${esc(m.text)}</p>`).join("")}</div>`).join("");
      const reps = (ans.reports || []).filter((r) => r.msgs?.length || r.id === last).map((r, n) => `<div class="card">${r.msgs?.length ? closeBtn(r.key) : ""}<b>💬 ${t.answer}</b> <span class="muted">${esc(r.id)}</span>
        ${r.msgs?.length ? r.msgs.map((m) => `<p class="msg ${m.from}"><b>${m.from === "dev" ? t.dev : t.you}:</b> ${esc(m.text)}</p>`).join("") : `<p class="muted">${t.wait}</p>`}
        ${n === 0 && r.msgs?.some((m) => m.from === "dev") ? `<textarea name="back" placeholder="${esc(t.back)}">${esc(this.back)}</textarea>
          ${this.backState === "sent" ? `<p class="ok">${t.sentBack}</p>` : this.backState === "fail" ? `<p class="bad">${t.fail}</p>` : ""}
          <button class="btn" data-a="back" data-id="${esc(r.id)}" ${this.backState === "sending" ? "disabled" : ""}>${this.backState === "sending" ? t.sending : t.sendBack}</button>` : ""}</div>`).join("");
      const form = this.state && this.state.id
        ? `<p class="ok">${t.sent.replace("{id}", esc(this.state.id))}</p><button class="btn ghost" data-a="new">${t.newOne}</button>`
        : `<p class="muted">${t.sub}</p><textarea name="note" placeholder="${esc(t.ph)}">${esc(this.note)}</textarea>
          <div class="imgs">${this.imgs.map((x, i) => `<span><img src="${x.url}" alt=""><button data-a="rm" data-i="${i}" aria-label="✕">✕</button></span>`).join("")}</div>
          ${this.imgs.length < 3 ? `<label class="btn ghost">📷 ${t.attach}<input type="file" accept="image/*" multiple data-file hidden></label>` : `<p class="muted">${t.max3}</p>`}
          <details><summary>${t.whatq}</summary><ul>${t.what.map((x) => `<li>${x}</li>`).join("")}</ul><p class="muted">${t.no}</p></details>
          ${this.state === "fail" ? `<p class="bad">${t.fail}</p>` : ""}
          <button class="btn" data-a="send" ${this.state === "sending" ? "disabled" : ""}>${this.state === "sending" ? t.sending : t.send}</button>`;
      const share = s.share ?? true;
      this.shadowRoot.innerHTML = `<style>
        :host{display:block;max-width:720px;margin:0 auto;padding:16px;box-sizing:border-box;color:var(--primary-text-color)}
        .card{background:var(--ha-card-background,var(--card-background-color,#fff));border-radius:var(--ha-card-border-radius,12px);box-shadow:var(--ha-card-box-shadow,0 1px 3px rgba(0,0,0,.12));padding:16px;margin-bottom:16px;overflow:hidden}
        h2{margin:0 0 6px;font-size:18px}.muted{color:var(--secondary-text-color);font-size:14px}.ok{color:var(--success-color,#2e7d32)}.bad{color:var(--error-color,#c62828)}
        textarea{width:100%;min-height:90px;box-sizing:border-box;margin:8px 0;padding:10px;border-radius:8px;border:1px solid var(--divider-color);background:var(--secondary-background-color,transparent);color:inherit;font:inherit}
        .btn{display:block;width:100%;margin-top:8px;padding:12px;border:0;border-radius:10px;background:var(--primary-color);color:var(--text-primary-color,#fff);font:inherit;font-weight:600;cursor:pointer;text-align:center;box-sizing:border-box}
        .btn.ghost{background:transparent;color:var(--primary-color);border:1px solid var(--divider-color)}.btn:disabled{opacity:.6}
        .link{background:none;border:0;color:var(--primary-color);cursor:pointer;font:inherit}.close{float:right}
        .msg{white-space:pre-wrap;margin:8px 0;padding:8px 10px;border-radius:8px;background:var(--secondary-background-color,rgba(0,0,0,.04))}.msg.you{opacity:.8}
        .imgs{display:flex;gap:8px;flex-wrap:wrap}.imgs span{position:relative}.imgs img{width:72px;height:72px;object-fit:cover;border-radius:8px}
        .imgs button{position:absolute;top:-6px;right:-6px;border:0;border-radius:50%;width:22px;height:22px;background:var(--error-color,#c62828);color:#fff;cursor:pointer}
        details{margin-top:10px}summary{cursor:pointer;color:var(--primary-color)}
        .row{display:flex;gap:12px;align-items:center}.row div{flex:1}.row small{display:block;color:var(--secondary-text-color)}
        .sw{width:44px;height:26px;border-radius:13px;border:0;background:var(--disabled-color,#bbb);position:relative;cursor:pointer;flex:none}
        .sw::after{content:"";position:absolute;top:3px;left:3px;width:20px;height:20px;border-radius:50%;background:#fff;transition:left .15s}
        .sw.on{background:var(--primary-color)}.sw.on::after{left:21px}
      </style>${notes}${reps}
      <div class="card"><h2>🛟 ${t.title}</h2>${form}</div>
      <div class="card"><div class="row"><div><b>${t.share}</b><small>${t.shareH}</small></div><button class="sw ${share ? "on" : ""}" data-a="share" role="switch" aria-checked="${share}" aria-label="${esc(t.share)}"></button></div></div>`;
    }
  });
  return name;
}
