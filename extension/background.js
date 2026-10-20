// Icon und Badge: Zahl offener Incidents deiner Kunden; blinkt rot, solange ein lauter
// Alarm (Kunde + passender Service) offen und nicht acknowledged ist.
// Port anpassen, wenn WEB_PORT in config.env geaendert wurde (auch in manifest.json und popup.html).
const STATE_URL = "http://localhost:8790/api/state";
const COLORS = { ok: "#1e8e3e", alarm: "#d93025", idle: "#8b949e" };

let blinkTimer = null;
let blinkOn = false;
let blinkTicks = 0;

function drawIcon(color, ring) {
  const imageData = {};
  for (const size of [16, 32]) {
    const c = new OffscreenCanvas(size, size), g = c.getContext("2d"), r = size / 2;
    g.beginPath();
    g.arc(r, r, r - size * 0.06, 0, Math.PI * 2);
    g.fillStyle = color;
    g.fill();
    if (ring) {
      g.lineWidth = size * 0.12;
      g.strokeStyle = "#ffffff";
      g.stroke();
    }
    // Glocke angedeutet: weisser Punkt in der Mitte
    g.beginPath();
    g.arc(r, r, size * 0.16, 0, Math.PI * 2);
    g.fillStyle = "#ffffff";
    g.fill();
    imageData[size] = g.getImageData(0, 0, size, size);
  }
  return chrome.action.setIcon({ imageData });
}

function startBlink() {
  if (blinkTimer) return;
  // Jeder Extension-API-Aufruf haelt den Service Worker wach, solange es blinkt
  blinkTimer = setInterval(() => {
    blinkOn = !blinkOn;
    drawIcon(blinkOn ? COLORS.alarm : COLORS.idle, blinkOn);
    chrome.action.setBadgeBackgroundColor({ color: blinkOn ? COLORS.alarm : COLORS.idle });
    // Waehrend eines Alarms oefter nachsehen, damit das Blinken nach dem Ack schnell aufhoert
    if (++blinkTicks % 10 === 0) update();
  }, 600);
}

function stopBlink() {
  if (!blinkTimer) return;
  clearInterval(blinkTimer);
  blinkTimer = null;
}

async function update() {
  let d = null;
  try {
    const r = await fetch(STATE_URL, { cache: "no-store" });
    d = await r.json();
  } catch {
    stopBlink();
    await drawIcon(COLORS.idle);
    await chrome.action.setBadgeText({ text: "aus" });
    await chrome.action.setBadgeBackgroundColor({ color: COLORS.idle });
    await chrome.action.setTitle({ title: "PD-Filter läuft nicht" });
    return;
  }
  const mine = (d.incidents || []).filter(i => i.customer);
  const alarms = mine.filter(i => i.decision === "alarm");
  let title;
  if (d.paused) {
    title = `PD-Filter: pausiert (${d.paused})`;
  } else if (d.last_error) {
    title = "PD-Filter: Fehler – " + d.last_error;
  } else {
    title = `PD-Filter: ${mine.length} offen bei deinen Kunden` + (alarms.length ? `, ${alarms.length} laut` : "");
  }
  await chrome.action.setTitle({ title });
  await chrome.action.setBadgeText({ text: d.paused ? "II" : d.last_error ? "!" : mine.length ? String(mine.length) : "" });

  if (alarms.length && !d.paused) {
    startBlink();
    return;
  }
  stopBlink();
  const color = d.paused ? COLORS.idle : d.last_error || mine.length ? COLORS.alarm : COLORS.ok;
  await drawIcon(color);
  await chrome.action.setBadgeBackgroundColor({ color });
}

function schedule() {
  chrome.alarms.create("poll", { periodInMinutes: 0.5 });
  update();
}
chrome.runtime.onInstalled.addListener(schedule);
chrome.runtime.onStartup.addListener(schedule);
chrome.alarms.onAlarm.addListener(update);
update();
