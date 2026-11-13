// Einstellungen als Zahnrad neben dem Seitenmenue, auf allen Seiten gleich (PD-Filter, Statistik, PAW).
// Oeffnet ein Dialogfeld; Werte kommen von /api/settings, gespeichert wird in config.env.
(() => {
  const css = `
  .navrow { display: flex; gap: 6px; align-items: stretch; }
  .navrow .switch { flex: 1; min-width: 0; }
  .gear { flex: none; width: 38px; border: 0; border-radius: 9px; cursor: pointer; display: grid; place-items: center;
          background: var(--side-tile); color: var(--side-muted); }
  .gear:hover, .gear[aria-expanded="true"] { color: var(--side-accent); background: var(--side-hi); }
  .gear svg { width: 18px; height: 18px; }
  dialog.settings { border: 1px solid var(--line); border-radius: 12px; padding: 0; width: min(560px, calc(100% - 24px));
                    max-height: calc(100vh - 48px); background: var(--panel); color: var(--text);
                    box-shadow: 0 12px 40px rgba(0,0,0,.25); font: inherit; }
  dialog.settings::backdrop { background: rgba(10, 16, 18, .45); }
  .settings .s-head { display: flex; align-items: center; gap: 10px; padding: 14px 18px; border-bottom: 1px solid var(--line);
                      position: sticky; top: 0; background: var(--panel); z-index: 1; }
  .settings .s-head h2 { margin: 0; font-size: 16px; flex: 1; }
  .settings .s-x { border: 0; background: none; color: var(--muted); font-size: 22px; line-height: 1; cursor: pointer;
                   width: 30px; height: 30px; border-radius: 6px; }
  .settings .s-x:hover { background: var(--line-soft); color: var(--text); }
  .settings form { display: grid; gap: 12px; padding: 14px 18px 18px; }
  .settings label { display: grid; gap: 4px; font-size: 13px; color: var(--muted); }
  .settings label.check { display: flex; align-items: center; gap: 8px; color: var(--text); }
  .settings .row { display: flex; gap: 12px; align-items: end; flex-wrap: wrap; }
  .settings input:not([type=checkbox]), .settings select {
    font: inherit; padding: 5px 8px; border-radius: 6px; border: 1px solid var(--line);
    background: var(--panel); color: var(--text); }
  .settings input[type=checkbox] { accent-color: var(--accent); }
  .settings input[type=number] { width: 90px; }
  .settings fieldset { border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px; margin: 0; display: grid; gap: 6px; }
  .settings h3 { font-size: 13px; margin: 8px 0 0; padding-top: 10px; border-top: 1px solid var(--line); }
  .settings h3:first-child { border-top: 0; padding-top: 0; margin-top: 0; }
  .settings legend { font-size: 13px; color: var(--muted); padding: 0 4px; }
  .settings .hint { color: var(--muted); font-size: 12px; }
  .settings .s-foot { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
  .settings .s-save { font: inherit; font-size: 13px; padding: 6px 14px; border-radius: 7px; cursor: pointer; font-weight: 600;
                      border: 1px solid var(--accent); background: var(--accent); color: var(--accent-text); }
  .settings .s-save:hover { filter: brightness(1.08); }
  .settings .s-save:disabled { opacity: .5; cursor: wait; }
  .settings .s-msg { font-size: 13px; color: var(--accent); }
  .settings .s-msg.err { color: var(--err, var(--alarm)); }`;

  const html = `
  <div class="s-head"><h2>Einstellungen</h2><button class="s-x" type="button" aria-label="Schließen">×</button></div>
  <form method="dialog" novalidate>
    <h3>Filter &amp; ntfy</h3>
    <label>Ton nur bei Service (mehrere mit ;, leer = alle)
      <input name="SERVICE_FILTER" placeholder="z. B. CSOC (High)">
    </label>
    <label>Mitteilung ohne Ton bei
      <select name="SILENT_FOR">
        <option value="kunden">meinen Kunden, wenn der Service nicht passt</option>
        <option value="alle">allen Incidents ohne Ton</option>
        <option value="keine">nie (nur Mitteilungen mit Ton)</option>
      </select>
    </label>
    <label class="check"><input type="checkbox" name="ONLY_IN_WINDOW"> Filter nur zu bestimmten Zeiten</label>
    <div class="row">
      <label>von (Uhr) <input type="number" name="START_HOUR" min="0" max="24"></label>
      <label>bis (Uhr) <input type="number" name="END_HOUR" min="0" max="24"></label>
      <label class="check"><input type="checkbox" name="WEEKDAYS_ONLY"> nur Mo–Fr</label>
    </div>
    <label>PagerDuty abfragen alle (Sekunden) <input type="number" name="POLL_SECONDS" min="5" max="3600"></label>

    <h3>On-Call</h3>
    <label class="check"><input type="checkbox" name="ONLY_ON_CALL"> Filter nur, wenn ich On-Call bin</label>
    <label>On-Call übergeben an (PagerDuty-Name oder E-Mail)
      <input name="OVERRIDE_USER">
    </label>

    <h3>PagerDuty-Benachrichtigung (LAS)</h3>
    <label>LAS bis (Uhr) <input type="number" name="LAS_END_HOUR" min="0" max="24"></label>
    <label>Für Incidents mit Dringlichkeit
      <select name="LAS_URGENCY">
        <option value="hoch">hoch</option>
        <option value="niedrig">niedrig</option>
        <option value="beide">hoch und niedrig</option>
      </select>
    </label>
    <fieldset>
      <legend>Benachrichtigen über (nichts gewählt = alle Geräte mit PagerDuty-App)</legend>
      <input type="hidden" name="LAS_CONTACTS">
      <div class="s-contacts hint">lädt…</div>
    </fieldset>

    <h3>Statistik</h3>
    <label>Team in PagerDuty <input name="STATS_TEAM" placeholder="CSOC Team"></label>
    <div class="row">
      <label>Geschäftszeit <input name="STATS_BUSINESS_HOURS" placeholder="07:30-18:00" pattern="\\d{1,2}:\\d{2}-\\d{1,2}:\\d{2}"></label>
      <label>LAS-Fenster Mo–Fr <input name="STATS_LAS_WINDOW" placeholder="16:30-18:00" pattern="\\d{1,2}:\\d{2}-\\d{1,2}:\\d{2}"></label>
    </div>
    <span class="hint">Datenschutz ist immer an: keine Incident-Titel ins Log, keine Kundendaten an ntfy.</span>
    <div class="s-foot">
      <button class="s-save" type="submit">Speichern</button>
      <span class="s-msg" role="status"></span>
      <span class="hint">Gilt sofort, wird in config.env gespeichert.</span>
    </div>
  </form>`;

  const gearSvg = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`;

  const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  const style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  // Zahnrad rechts neben das Seitenmenue setzen
  const nav = document.querySelector("nav.switch");
  if (!nav) return;
  const row = document.createElement("div");
  row.className = "navrow";
  nav.replaceWith(row);
  row.appendChild(nav);
  const gear = document.createElement("button");
  gear.className = "gear";
  gear.type = "button";
  gear.title = "Einstellungen";
  gear.setAttribute("aria-label", "Einstellungen");
  gear.setAttribute("aria-expanded", "false");
  gear.innerHTML = gearSvg;
  row.appendChild(gear);

  const dlg = document.createElement("dialog");
  dlg.className = "settings";
  dlg.innerHTML = html;
  document.body.appendChild(dlg);
  const form = dlg.querySelector("form");
  const msg = dlg.querySelector(".s-msg");
  const contactsInput = form.elements.LAS_CONTACTS;
  const contactList = dlg.querySelector(".s-contacts");
  let dirty = false;

  function fill(s) {
    for (const [key, value] of Object.entries(s || {})) {
      const el = form.elements[key];
      if (!el) continue;
      if (el.type === "checkbox") el.checked = value;
      else el.value = value;
    }
    markContacts();
  }
  function markContacts() {
    const ids = contactsInput.value.split(",").filter(Boolean);
    contactList.querySelectorAll("input[data-contact]").forEach(cb => { cb.checked = ids.includes(cb.dataset.contact); });
  }
  async function loadSettings() {
    try {
      const r = await fetch("/api/settings", { cache: "no-store" });
      const res = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(res.error || "HTTP " + r.status);
      if (!dirty) fill(res.settings);
    } catch (e) {
      msg.className = "s-msg err"; msg.textContent = "Einstellungen nicht geladen: " + e.message;
    }
  }
  async function loadContacts() {
    try {
      const r = await fetch("/api/contacts", { cache: "no-store" });
      const res = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(res.error || "HTTP " + r.status);
      contactList.classList.toggle("hint", !res.contacts.length);
      contactList.innerHTML = res.contacts.map(c => `<label class="check"><input type="checkbox" data-contact="${esc(c.id)}">
        ${esc(c.kind)}: ${esc(c.label)}${c.address && c.kind !== "Push" ? ` (${esc(c.address)})` : ""}</label>`).join("")
        || "Keine Kontakte in PagerDuty gefunden";
      markContacts();
    } catch (e) {
      contactList.textContent = "Kontakte nicht geladen: " + e.message;
    }
  }
  contactList.addEventListener("change", () => {
    contactsInput.value = [...contactList.querySelectorAll("input[data-contact]:checked")]
      .map(cb => cb.dataset.contact).join(",");
    dirty = true;
  });

  function open() {
    msg.textContent = ""; msg.className = "s-msg";
    dirty = false;
    loadSettings().then(loadContacts);
    dlg.showModal();
    gear.setAttribute("aria-expanded", "true");
  }
  gear.addEventListener("click", open);
  dlg.addEventListener("close", () => gear.setAttribute("aria-expanded", "false"));
  dlg.querySelector(".s-x").addEventListener("click", () => dlg.close());
  // Klick neben das Feld schliesst es
  dlg.addEventListener("click", ev => { if (ev.target === dlg) dlg.close(); });
  form.addEventListener("input", () => { dirty = true; });

  form.addEventListener("submit", async ev => {
    ev.preventDefault();
    const bad = [...form.elements].find(el => el.willValidate && !el.checkValidity());
    if (bad) { bad.reportValidity(); return; }
    const body = {};
    for (const el of form.elements) {
      if (!el.name || el.tagName === "FIELDSET") continue;
      body[el.name] = el.type === "checkbox" ? el.checked : el.value;
    }
    const btn = form.querySelector(".s-save");
    btn.disabled = true;
    try {
      const r = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-PD-Filter": "1" },
        body: JSON.stringify(body),
      });
      const res = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(res.error || "HTTP " + r.status);
      dirty = false;
      msg.className = "s-msg"; msg.textContent = "✓ Gespeichert";
      window.dispatchEvent(new Event("pd-settings-saved"));
    } catch (e) {
      msg.className = "s-msg err"; msg.textContent = "Speichern fehlgeschlagen: " + e.message;
    } finally {
      btn.disabled = false;
    }
  });
})();
