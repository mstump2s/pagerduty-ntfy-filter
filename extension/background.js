// Badge am Extension-Icon: Zahl offener, noch nicht acknowledged Incidents deiner Kunden.
// Port anpassen, wenn WEB_PORT in config.env geaendert wurde (auch in manifest.json und popup.html).
const STATE_URL = "http://localhost:8790/api/state";

async function updateBadge() {
  let text = "", color = "#d93025", title = "PD-Filter";
  try {
    const r = await fetch(STATE_URL, { cache: "no-store" });
    const d = await r.json();
    const mine = (d.incidents || []).filter(i => i.customer).length;
    if (d.paused) {
      text = "II"; color = "#69727d"; title = `PD-Filter: pausiert (${d.paused})`;
    } else if (d.last_error) {
      text = "!"; title = "PD-Filter: Fehler – " + d.last_error;
    } else {
      text = mine ? String(mine) : "";
      title = `PD-Filter: ${mine} offen bei deinen Kunden`;
    }
  } catch {
    text = "aus"; color = "#69727d"; title = "PD-Filter läuft nicht";
  }
  await chrome.action.setBadgeText({ text });
  await chrome.action.setBadgeBackgroundColor({ color });
  await chrome.action.setTitle({ title });
}

chrome.runtime.onInstalled.addListener(() => chrome.alarms.create("poll", { periodInMinutes: 0.5 }));
chrome.runtime.onStartup.addListener(() => chrome.alarms.create("poll", { periodInMinutes: 0.5 }));
chrome.alarms.onAlarm.addListener(updateBadge);
updateBadge();
