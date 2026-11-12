// Laeuft auf shifts.csoc.gk.rocks. Liest den Entra-Token, den die shifts-App nach
// deinem Login im sessionStorage haelt (MSAL), ruft die shifts-API ab und schickt die
// Rohdaten an den lokalen pd-filter-Server (ueber den Background-Service-Worker).
// Kein Token verlaesst den Rechner: nur die API-Antworten gehen an localhost:8790.

const API_AUDIENCE = "5208db88-3870-46e0-be18-b6947918d4c1"; // shifts-Backend-App
const SCOPE_HINT = "access_as_user";
const POLL_MS = 3 * 60 * 1000; // alle 3 Minuten, solange der Tab offen ist

// --- Token aus dem MSAL-Cache (sessionStorage, Fallback localStorage) holen ---
function findAccessToken() {
  const now = Math.floor(Date.now() / 1000);
  let best = null;
  for (const store of [window.sessionStorage, window.localStorage]) {
    for (let i = 0; i < store.length; i++) {
      const raw = store.getItem(store.key(i));
      if (!raw || raw[0] !== "{") continue;
      let o;
      try { o = JSON.parse(raw); } catch { continue; }
      if (!o || o.credentialType !== "AccessToken" || !o.secret) continue;
      const target = (o.target || "").toLowerCase();
      if (!target.includes(SCOPE_HINT) && !target.includes(API_AUDIENCE)) continue;
      const exp = parseInt(o.expiresOn || "0", 10);
      if (exp && exp < now + 30) continue; // schon (fast) abgelaufen
      if (!best || exp > best.exp) best = { token: o.secret, exp };
    }
  }
  return best;
}

async function apiGet(path, token) {
  const r = await fetch(path, {
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}

async function collect() {
  const found = findAccessToken();
  if (!found) {
    console.log("[pd-filter] kein shifts-Token im Cache gefunden (eingeloggt?)");
    return;
  }
  const token = found.token;
  const now = new Date();
  const start = new Date(now.getTime() - 24 * 3600 * 1000);
  const end = new Date(now.getTime() + 14 * 24 * 3600 * 1000);
  const deputiesQ = `/api/ShiftDeputies?${new URLSearchParams({
    startDate: start.toISOString(), endDate: end.toISOString(),
  })}`;

  const payload = { fetched_at: now.toISOString(), errors: {} };
  const jobs = [
    ["overview", "/api/AnalystStatus/overview"],
    ["users", "/api/ShiftDeputies/users"],
    ["deputies", deputiesQ],
  ];
  await Promise.all(jobs.map(async ([key, path]) => {
    try { payload[key] = await apiGet(path, token); }
    catch (e) { payload.errors[key] = String(e.message || e); }
  }));

  chrome.runtime.sendMessage({ type: "shiftsData", payload }, (resp) => {
    const err = chrome.runtime.lastError;
    if (err) console.log("[pd-filter] Senden fehlgeschlagen:", err.message);
    else console.log("[pd-filter] shifts-Daten uebergeben:", resp && resp.ok ? "ok" : resp);
  });
}

collect();
setInterval(collect, POLL_MS);
