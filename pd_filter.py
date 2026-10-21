#!/usr/bin/env python3
"""
PagerDuty-Filter: Bimmelt nur fuer Incidents, deren Titel einen deiner Kunden enthaelt.

- Fragt regelmaessig offene (triggered) Incidents per PagerDuty REST API ab
- Prueft den Titel gegen die Kundenliste (Gross-/Kleinschreibung egal, Teilstring)
- Schickt bei Treffer eine Push-Nachricht mit hoechster Prioritaet ueber ntfy
- Merkt sich bereits gemeldete Incidents in seen.json (kein Doppel-Alarm nach Neustart)
- Laeuft, bis du es stoppst. Optional nur im Zeitfenster (ONLY_IN_WINDOW=true).

Kundenliste: Datei customers.txt (wird bei jedem Durchlauf neu gelesen)
oder Variable CUSTOMERS (komma- oder zeilengetrennt).

Konfiguration: Datei config.env im selben Ordner (KEY=wert pro Zeile)
oder Umgebungsvariablen (die haben Vorrang):
  PD_API_TOKEN        persoenlicher PagerDuty REST-API-Key (Pflicht)
  NTFY_TOPIC          dein geheimer ntfy-Topic-Name (Pflicht)
  CUSTOMERS           optional, z.B. "KundeA,KundeB"
  NTFY_SERVER         optional, Standard: https://ntfy.sh
  POLL_SECONDS        optional, Standard: 30
  PD_SERVICE_IDS      optional, kommagetrennt: nur diese Services abfragen
  SERVICE_FILTER      optional, z.B. "CSOC (High)": nur bimmeln, wenn der Service-Name
                      diesen Text enthaelt (Gross-/Kleinschreibung egal, mehrere mit ";").
                      Leer = alle Services.
  SILENT_FOR          optional, wofuer eine leise Mitteilung (ohne Ton) kommt:
                        kunden = deine Kunden, wenn der Service nicht passt (Standard)
                        alle   = zusaetzlich alle anderen Incidents
                        keine  = nur die lauten Alarme
  NTFY_TOPIC_SILENT   optional, eigenes ntfy-Topic fuer die leisen Mitteilungen
  TZ_NAME             optional, Standard: Europe/Berlin
  ONLY_ON_CALL        optional, Standard: false. true = nur aktiv, solange du laut PagerDuty
                      gerade in einem Schedule on-call bist (sonst pausiert, keine Mitteilungen)
  OVERRIDE_USER       optional, Standard: CSOC Dummy. PagerDuty-User (Name oder E-Mail), an den
                      der Button "Rest der Schicht abgeben" per Override uebergibt
  ONLY_IN_WINDOW      optional, Standard: false. true = nur START_HOUR bis END_HOUR aktiv
  START_HOUR          optional, Standard: 8
  END_HOUR            optional, Standard: 18
  WEEKDAYS_ONLY       optional, Standard: true (gilt nur mit ONLY_IN_WINDOW=true)
  QUIET               optional, true = keine Incident-Titel ins Log schreiben
  WEB_PORT            optional, Standard: 8790 (Live-Ansicht, nur 127.0.0.1). 0 = aus
  PD_FROM_EMAIL       optional, nur fuer Account-Keys: E-Mail fuer den From-Header beim Ack
"""

import json
import os
import re
import signal
import sys
import threading
import time
import unicodedata
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

BASE_DIR = Path(__file__).resolve().parent
CUSTOMERS_FILE = BASE_DIR / "customers.txt"
SEEN_FILE = BASE_DIR / "seen.json"
OVERRIDES_FILE = BASE_DIR / "overrides.json"
CONFIG_FILE = BASE_DIR / "config.env"


def load_config_file():
    """config.env einlesen; bereits gesetzte Umgebungsvariablen werden nicht ueberschrieben."""
    if not CONFIG_FILE.exists():
        return
    for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_config_file()


def env_bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "ja")


PD_API_TOKEN = os.environ.get("PD_API_TOKEN")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "30"))
PD_SERVICE_IDS = [s.strip() for s in os.environ.get("PD_SERVICE_IDS", "").split(",") if s.strip()]
SERVICE_FILTER = [s.strip().lower() for s in os.environ.get("SERVICE_FILTER", "").split(";") if s.strip()]
SERVICE_FILTER_TEXT = os.environ.get("SERVICE_FILTER", "").strip()     # Originalschreibweise fuer die Anzeige
SILENT_FOR = os.environ.get("SILENT_FOR", "kunden").strip().lower()      # kunden | alle | keine
NTFY_TOPIC_SILENT = os.environ.get("NTFY_TOPIC_SILENT", "").strip()      # optional eigenes Topic fuer leise
TZ = ZoneInfo(os.environ.get("TZ_NAME", "Europe/Berlin"))
START_HOUR = int(os.environ.get("START_HOUR", "8"))
END_HOUR = int(os.environ.get("END_HOUR", "18"))
WEEKDAYS_ONLY = env_bool("WEEKDAYS_ONLY", True)
ONLY_IN_WINDOW = env_bool("ONLY_IN_WINDOW", False)
ONLY_ON_CALL = env_bool("ONLY_ON_CALL", False)
OVERRIDE_USER = os.environ.get("OVERRIDE_USER", "CSOC Dummy").strip()
QUIET = env_bool("QUIET", False)
WEB_PORT = int(os.environ.get("WEB_PORT", "8790") or 0)   # 0 = Live-Ansicht aus
PD_FROM_EMAIL = os.environ.get("PD_FROM_EMAIL", "").strip()
PD_API = "https://api.pagerduty.com"
DASHBOARD_FILE = BASE_DIR / "dashboard.html"
MINI_FILE = BASE_DIR / "mini.html"          # kompakte Ansicht fuer das Extension-Popup

# Zustand fuer die Live-Ansicht
STATE_LOCK = threading.Lock()
STATE = {
    "started": None,
    "last_poll": None,
    "last_error": None,
    "paused": None,             # None = aktiv, sonst Grund der Pause
    "poll_seconds": POLL_SECONDS,
    "customers": [],
    "service_filter": SERVICE_FILTER,
    "incidents": [],            # aktuell offene Incidents mit Entscheidung
    "acked": [],                # von mir acknowledged (oder alle, wenn eigener User unbekannt)
    "acked_mine": False,        # True = "acked" ist auf meinen User gefiltert
    "shift": None,              # aktuelle Schicht: {"schedules": [...], "end": ISO-Zeit}
    "override_user": OVERRIDE_USER,
    "overrides": [],            # von mir gesetzte, noch laufende Overrides: [{"schedule", "end", ...}]
    "customers_editable": not os.environ.get("CUSTOMERS", "").strip(),
}
EVENTS = deque(maxlen=300)      # Verlauf (neueste zuerst)

PD_HEADERS = {
    "Authorization": f"Token token={PD_API_TOKEN}",
    "Accept": "application/vnd.pagerduty+json;version=2",
}


def now_str():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    print(now_str(), msg, flush=True)


def add_event(kind, text, inc=None, customer=None):
    """kind: alarm | service | customer | error | info"""
    ev = {"time": now_str(), "kind": kind, "text": text}
    if inc:
        ev.update(title=inc.get("title", ""), service=service_name(inc),
                  url=inc.get("html_url", ""), customer=customer)
    with STATE_LOCK:
        EVENTS.appendleft(ev)


def show(title):
    return "(Titel ausgeblendet)" if QUIET else title


def in_time_window(now=None):
    if not ONLY_IN_WINDOW:
        return True
    now = now or datetime.now(TZ)
    if WEEKDAYS_ONLY and now.weekday() >= 5:
        return False
    return START_HOUR <= now.hour < END_HOUR


def load_customers():
    """Aus CUSTOMERS (Env) oder customers.txt. Leere Zeilen und #-Kommentare werden ignoriert."""
    raw = os.environ.get("CUSTOMERS")
    if raw and raw.strip():
        raw = raw.replace(",", "\n")   # in der Variable: komma- oder zeilengetrennt
    else:
        if not CUSTOMERS_FILE.exists():
            return []
        raw = CUSTOMERS_FILE.read_text(encoding="utf-8")
    global _RTF_WARNED
    if raw.lstrip().startswith("{\\rtf") and not _RTF_WARNED:
        _RTF_WARNED = True
        add_event("error", "customers.txt ist Rich Text statt reinem Text")
        log("WARNUNG: customers.txt ist Rich Text (TextEdit). Bitte als reinen Text speichern: "
            "Format -> In reinen Text umwandeln.")
    customers = []
    for line in raw.splitlines():
        line = norm(line)
        if line and not line.startswith("#"):
            customers.append(line)
    return customers


# ---------- Einstellungen aus der Live-Ansicht ----------

# In der Live-Ansicht aenderbar (keine Secrets): Key -> Typ
EDITABLE = {
    "SILENT_FOR": ("kunden", "alle", "keine"),
    "SERVICE_FILTER": str,
    "ONLY_ON_CALL": bool,
    "OVERRIDE_USER": str,
    "ONLY_IN_WINDOW": bool,
    "START_HOUR": int,
    "END_HOUR": int,
    "WEEKDAYS_ONLY": bool,
    "POLL_SECONDS": int,
    "QUIET": bool,
}
SETTINGS_LOCK = threading.Lock()


def current_settings():
    g = globals()
    return {k: SERVICE_FILTER_TEXT if k == "SERVICE_FILTER" else g[k] for k in EDITABLE}


def parse_setting(key, value):
    """Wert aus der Live-Ansicht pruefen. Liefert (Python-Wert, Text fuer config.env)."""
    kind = EDITABLE[key]
    if kind is bool:
        if not isinstance(value, bool):
            raise ValueError("ja/nein erwartet")
        return value, "true" if value else "false"
    text = " ".join(str(value).split())
    if len(text) > 200:
        raise ValueError("zu lang")
    if isinstance(kind, tuple):
        if text not in kind:
            raise ValueError("erlaubt: " + ", ".join(kind))
        return text, text
    if kind is int:
        number = int(text)
        low, high = (5, 3600) if key == "POLL_SECONDS" else (0, 24)
        if not low <= number <= high:
            raise ValueError(f"erlaubt: {low} bis {high}")
        return number, str(number)
    if key == "SERVICE_FILTER":
        parts = [s.strip() for s in text.split(";") if s.strip()]
        return [s.lower() for s in parts], ";".join(parts)
    return text, text


def write_config(values):
    """Werte in config.env setzen: vorhandene Zeile ersetzen, sonst anhaengen. Kommentare bleiben."""
    lines = CONFIG_FILE.read_text(encoding="utf-8").splitlines() if CONFIG_FILE.exists() else []
    todo = dict(values)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if not line.lstrip().startswith("#") and "=" in line and key in todo:
            lines[i] = f"{key}={todo.pop(key)}"
    lines += [f"{k}={v}" for k, v in todo.items()]
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(CONFIG_FILE)


def update_settings(changes):
    """Einstellungen pruefen, sofort uebernehmen und in config.env speichern.
    Liefert (Fehlertext oder None, Liste geaenderter Keys)."""
    parsed, lines = {}, {}
    for key, value in changes.items():
        if key not in EDITABLE:
            return f"{key} ist nicht aenderbar", []
        try:
            parsed[key], lines[key] = parse_setting(key, value)
        except (ValueError, TypeError) as e:
            return f"{key}: {e}", []
    with SETTINGS_LOCK:
        changed = [k for k in parsed if globals()[k] != parsed[k]]
        try:
            write_config({k: lines[k] for k in changed})
        except OSError as e:
            return f"config.env nicht gespeichert: {e}", []
        globals().update({k: parsed[k] for k in changed})
        if "SERVICE_FILTER" in changed:
            globals()["SERVICE_FILTER_TEXT"] = lines["SERVICE_FILTER"]
    _ON_CALL_CACHE["at"] = 0.0
    with STATE_LOCK:
        STATE.update(settings=current_settings(), service_filter=SERVICE_FILTER,
                     poll_seconds=POLL_SECONDS, override_user=OVERRIDE_USER)
    return None, sorted(changed)


CUSTOMERS_FROM_ENV = bool(os.environ.get("CUSTOMERS", "").strip())
CUSTOMERS_LOCK = threading.Lock()


def edit_customers(add=None, remove=None):
    """Kunden in customers.txt ergaenzen oder entfernen (aus der Live-Ansicht).
    Kommentare und uebrige Zeilen bleiben stehen. Liefert Fehlertext oder None."""
    if CUSTOMERS_FROM_ENV:
        return "Kunden kommen aus der Variable CUSTOMERS, nicht aus customers.txt"
    with CUSTOMERS_LOCK:
        raw = CUSTOMERS_FILE.read_text(encoding="utf-8") if CUSTOMERS_FILE.exists() else ""
        if raw.lstrip().startswith("{\\rtf"):
            return "customers.txt ist Rich Text, bitte erst als reinen Text speichern"
        lines = raw.splitlines()
        if add is not None:
            name = " ".join(add.split())
            if not name or name.startswith("#") or len(name) > 100:
                return "Ungueltiger Kundenname"
            if norm(name) in {norm(l) for l in lines}:
                return f"{name} steht schon in der Liste"
            lines.append(name)
        else:
            kept = [l for l in lines if norm(l) != norm(remove)]
            if len(kept) == len(lines):
                return f"{remove} steht nicht in der Liste"
            lines = kept
        tmp = CUSTOMERS_FILE.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(CUSTOMERS_FILE)
    with STATE_LOCK:
        STATE["customers"] = load_customers()
    return None


def load_seen():
    try:
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(sorted(seen)), encoding="utf-8")


def fetch_incidents(status):
    incidents = []
    offset = 0
    while True:
        params = {"statuses[]": status, "limit": 100, "offset": offset}
        if PD_SERVICE_IDS:
            params["service_ids[]"] = PD_SERVICE_IDS
        r = requests.get(f"{PD_API}/incidents",
                         headers=PD_HEADERS, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        page = data.get("incidents", [])
        incidents.extend(page)
        # Leere Seite trotz more=true wuerde sonst endlos laufen
        if not data.get("more") or not page:
            return incidents
        offset += len(page)


MY_USER_ID = None   # None = noch nicht ermittelt, "" = nicht ermittelbar


def find_my_user_id():
    """Eigene PagerDuty-User-ID: bei persoenlichem Key ueber /users/me, sonst ueber PD_FROM_EMAIL.
    Bei Netzwerkfehlern bleibt es bei None -> naechster Durchlauf versucht es erneut."""
    global MY_USER_ID
    try:
        r = requests.get(f"{PD_API}/users/me", headers=PD_HEADERS, timeout=20)
        if r.ok:
            MY_USER_ID = r.json()["user"]["id"]
        elif PD_FROM_EMAIL:
            r = requests.get(f"{PD_API}/users", headers=PD_HEADERS,
                             params={"query": PD_FROM_EMAIL}, timeout=20)
            r.raise_for_status()
            MY_USER_ID = next((u["id"] for u in r.json().get("users", [])
                               if u.get("email", "").lower() == PD_FROM_EMAIL.lower()), "")
        else:
            MY_USER_ID = ""
    except (requests.RequestException, KeyError, ValueError) as e:
        log(f"Eigene PagerDuty-User-ID nicht ermittelt, neuer Versuch spaeter: {e}")
        return
    if not MY_USER_ID:
        log("Eigene PagerDuty-User-ID unbekannt: zeige alle acknowledged Incidents "
            "(bei Account-Key PD_FROM_EMAIL setzen).")


_ON_CALL_CACHE = {"at": 0.0, "value": True}


def fetch_my_shifts():
    """Meine aktuellen Schichten: {schedule_id: {"schedule": Name, "end": ISO-Zeit oder None}}."""
    r = requests.get(f"{PD_API}/oncalls", headers=PD_HEADERS, timeout=20,
                     params={"user_ids[]": MY_USER_ID, "limit": 100})
    r.raise_for_status()
    return {o["schedule"]["id"]: {"schedule": o["schedule"].get("summary", ""), "end": o.get("end")}
            for o in r.json().get("oncalls", []) if o.get("schedule")}


def on_call_now():
    """True, wenn ich gerade in einem Schedule on-call bin (hoechstens einmal pro Minute gefragt).
    Aktualisiert nebenbei die Schicht-Anzeige. Kann das nicht geprueft werden (User unbekannt,
    PagerDuty nicht erreichbar), lieber weiterlaufen als Alarme verpassen."""
    if time.monotonic() - _ON_CALL_CACHE["at"] < 60:
        return _ON_CALL_CACHE["value"]
    if MY_USER_ID is None:
        find_my_user_id()
    shifts = {}
    if not MY_USER_ID:
        log("On-Call-Status nicht pruefbar (eigener PagerDuty-User unbekannt), laufe weiter.")
        value = True
    else:
        try:
            shifts = fetch_my_shifts()
            value = bool(shifts)
        except (requests.RequestException, KeyError, ValueError) as e:
            log(f"On-Call-Status nicht abrufbar, laufe weiter: {e}")
            value = True
    _ON_CALL_CACHE.update(at=time.monotonic(), value=value)
    ends = [s["end"] for s in shifts.values() if s["end"]]
    with STATE_LOCK:
        STATE["overrides"] = load_overrides()
        STATE["shift"] = {"schedules": [s["schedule"] for s in shifts.values()],
                          "end": max(ends) if ends else None} if shifts else None
    return value


def find_user_id(name_or_email):
    """PagerDuty-User-ID zu Name oder E-Mail (exakt, Gross/klein egal)."""
    r = requests.get(f"{PD_API}/users", headers=PD_HEADERS, timeout=20, params={"query": name_or_email})
    r.raise_for_status()
    wanted = name_or_email.casefold()
    return next((u["id"] for u in r.json().get("users", [])
                 if wanted in (u.get("name", "").casefold(), u.get("email", "").casefold())), None)


def parse_time(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)


def load_overrides():
    """Selbst gesetzte Overrides, die noch nicht abgelaufen sind (ueberstehen einen Neustart)."""
    try:
        overrides = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        overrides = []
    now = datetime.now(TZ)
    return [o for o in overrides if parse_time(o["end"]) > now]


def save_overrides(overrides):
    OVERRIDES_FILE.write_text(json.dumps(overrides), encoding="utf-8")
    with STATE_LOCK:
        STATE["overrides"] = overrides


def pd_write_headers():
    headers = dict(PD_HEADERS, **{"Content-Type": "application/json"})
    if PD_FROM_EMAIL:
        headers["From"] = PD_FROM_EMAIL
    return headers


def hand_over_shift():
    """Rest meiner aktuellen Schicht(en) per Override an OVERRIDE_USER geben.
    Liefert (Fehlertext oder None, Beschreibung)."""
    if not OVERRIDE_USER:
        return "OVERRIDE_USER ist nicht gesetzt", ""
    if MY_USER_ID is None:
        find_my_user_id()
    if not MY_USER_ID:
        return "Eigener PagerDuty-User unbekannt (bei Account-Key PD_FROM_EMAIL setzen)", ""
    headers = pd_write_headers()
    overrides = load_overrides()
    try:
        shifts = fetch_my_shifts()
        if not shifts:
            return "Du bist gerade in keinem Schedule on-call", ""
        user_id = find_user_id(OVERRIDE_USER)
        if not user_id:
            return f"PagerDuty-User {OVERRIDE_USER!r} nicht gefunden", ""
        start = datetime.now(TZ).isoformat(timespec="seconds")
        done = []
        for schedule_id, s in shifts.items():
            if not s["end"]:
                return f"Schicht in {s['schedule']} hat kein Ende, kein Override gesetzt", ""
            r = requests.post(f"{PD_API}/schedules/{schedule_id}/overrides", headers=headers, timeout=20,
                              json={"overrides": [{"start": start, "end": s["end"],
                                                   "user": {"id": user_id, "type": "user_reference"}}]})
            if not r.ok:
                return f"{s['schedule']}: {pd_error_text(r)}", ""
            # Sammel-Endpunkt: Status steht pro Override in der Antwort
            body = r.json()
            for item in body if isinstance(body, list) else [body]:
                if item.get("status", 201) >= 300:
                    return f"{s['schedule']}: {'; '.join(item.get('errors') or ['abgelehnt'])}", ""
                # ID merken, damit "Schicht zurueckholen" den Override wieder loeschen kann
                if item.get("override", {}).get("id"):
                    overrides.append({"schedule_id": schedule_id, "schedule": s["schedule"],
                                      "id": item["override"]["id"], "end": s["end"]})
                    save_overrides(overrides)
            done.append(f"{s['schedule']} bis {parse_time(s['end']):%H:%M}")
    except (requests.RequestException, KeyError, ValueError) as e:
        return f"PagerDuty-Fehler: {e}", ""
    _ON_CALL_CACHE["at"] = 0.0   # beim naechsten Durchlauf neu pruefen -> pausiert dann
    return None, f"Override an {OVERRIDE_USER}: " + ", ".join(done)


def take_back_shift():
    """Meine Overrides loeschen, die Schicht gehoert dann wieder mir. Laeuft ein Override schon,
    kuerzt PagerDuty ihn auf jetzt. Liefert (Fehlertext oder None, Beschreibung)."""
    overrides = load_overrides()
    if not overrides:
        return "Kein abgegebener Override gefunden", ""
    headers = pd_write_headers()
    done = []
    try:
        for o in list(overrides):
            r = requests.delete(f"{PD_API}/schedules/{o['schedule_id']}/overrides/{o['id']}",
                                headers=headers, timeout=20)
            if not r.ok and r.status_code != 404:   # 404: in PagerDuty schon geloescht
                save_overrides(overrides)
                return f"{o['schedule']}: {pd_error_text(r)}", ""
            overrides.remove(o)
            done.append(o["schedule"])
    except requests.RequestException as e:
        save_overrides(overrides)
        return f"PagerDuty-Fehler: {e}", ""
    save_overrides(overrides)
    _ON_CALL_CACHE["at"] = 0.0   # beim naechsten Durchlauf neu pruefen -> wieder aktiv
    return None, "Schicht zurueckgeholt: " + ", ".join(done)


def fetch_my_acked(customers):
    """Acknowledged Incidents, die ich acknowledged habe (ohne bekannte User-ID: alle)."""
    acked = []
    for inc in fetch_incidents("acknowledged"):
        acks = inc.get("acknowledgements") or []
        mine = [a for a in acks if (a.get("acknowledger") or {}).get("id") == MY_USER_ID]
        if MY_USER_ID and not mine:
            continue
        last = (mine or acks or [{}])[-1]
        acked.append({
            "id": inc["id"],
            "title": inc.get("title", ""),
            "service": service_name(inc),
            "url": inc.get("html_url", ""),
            "customer": match_customer(inc.get("title", ""), customers),
            "acked_at": last.get("at") or inc.get("updated_at") or inc.get("created_at", ""),
        })
    return sorted(acked, key=lambda a: a["acked_at"], reverse=True)


def pd_error_text(r):
    """Fehlermeldung aus einer PagerDuty-Antwort lesbar machen."""
    try:
        err = r.json().get("error", {})
        parts = [err.get("message", "")] + list(err.get("errors", []))
        text = "; ".join(p for p in parts if p)
    except ValueError:
        text = r.text[:200]
    return f"HTTP {r.status_code}: {text or r.reason}"


def set_incident_status(incident_id, status):
    """Incident in PagerDuty auf acknowledged/resolved setzen. Liefert None oder Fehlertext."""
    headers = dict(PD_HEADERS, **{"Content-Type": "application/json"})
    if PD_FROM_EMAIL:
        headers["From"] = PD_FROM_EMAIL
    try:
        r = requests.put(f"{PD_API}/incidents/{incident_id}", headers=headers, timeout=20,
                         json={"incident": {"type": "incident_reference", "status": status}})
    except requests.RequestException as e:
        return f"PagerDuty nicht erreichbar: {e}"
    return None if r.ok else pd_error_text(r)


def service_name(incident):
    return (incident.get("service") or {}).get("summary", "")


def service_matches(incident):
    if not SERVICE_FILTER:
        return True
    name = service_name(incident).lower()
    return any(f in name for f in SERVICE_FILTER)


_RTF_WARNED = False
_INVISIBLE = dict.fromkeys(map(ord, "﻿​‌‍⁠­"), None)


def norm(s):
    """Fuer den Vergleich: Unicode vereinheitlichen, unsichtbare Zeichen raus,
    alle Leerzeichen-Arten zu einem normalen Leerzeichen, Kleinschreibung."""
    s = unicodedata.normalize("NFKC", s or "").translate(_INVISIBLE)
    return " ".join(s.split()).casefold()


def match_customer(title, customers):
    """Contains-Pruefung: Kunde kommt irgendwo im Titel vor (Gross/klein egal)."""
    t = norm(title)
    for c in customers:
        if norm(c) and norm(c) in t:
            return c
    return None


def notify(incident, customer, loud=True):
    """loud=True: Prioritaet 'urgent' (lauter Alarm).
    loud=False: Prioritaet 'low' (nur Mitteilung, kein Ton), optional auf eigenes Topic."""
    title = incident.get("title", "(ohne Titel)")
    url = incident.get("html_url", "")
    service = service_name(incident)
    topic = NTFY_TOPIC if loud else (NTFY_TOPIC_SILENT or NTFY_TOPIC)
    label = customer or service or "Alarm"
    r = requests.post(
        f"{NTFY_SERVER}/{topic}",
        data=f"{title}\nService: {service}".encode("utf-8"),
        headers={
            "Title": f"PagerDuty: {label}".encode("utf-8"),
            "Priority": "urgent" if loud else "low",
            "Tags": "rotating_light" if loud else "information_source",
            "Click": url,                  # Tippen oeffnet den Incident
        },
        timeout=20,
    )
    r.raise_for_status()


def classify(inc, customers):
    """Liefert (Entscheidung, Kunde).
    alarm    = dein Kunde und Service passt (z.B. CSOC (High))  -> laut
    service  = Service passt nicht (z.B. CSOC (Medium))
    customer = Service passt, aber kein Kunde von dir"""
    customer = match_customer(inc.get("title", ""), customers)
    if not service_matches(inc):
        return "service", customer
    if customer:
        return "alarm", customer
    return "customer", None


def wants_silent(decision, customer):
    """Soll fuer diesen (nicht lauten) Incident eine leise Mitteilung kommen?"""
    if SILENT_FOR == "alle":
        return decision in ("service", "customer")
    if SILENT_FOR == "kunden":
        return decision == "service" and customer is not None
    return False


# ---------- Live-Ansicht (nur lokal auf diesem Rechner erreichbar) ----------

ID_RE = re.compile(r"^[A-Za-z0-9]{1,64}$")
# Pfad -> (PagerDuty-Status, Ereignis-Art, Text fuer Log/Verlauf)
ACTIONS = {
    "/api/ack": ("acknowledged", "ack", "Acknowledged"),
    "/api/resolve": ("resolved", "resolve", "Resolved"),
}


class DashboardHandler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, data):
        self._send(code, json.dumps(data).encode("utf-8"), "application/json")

    def _host_ok(self):
        """Schutz gegen DNS-Rebinding: nur localhost/127.0.0.1 mit unserem Port."""
        return self.headers.get("Host", "") in (f"localhost:{WEB_PORT}", f"127.0.0.1:{WEB_PORT}")

    def _origin_ok(self):
        origin = self.headers.get("Origin")
        return origin is None or origin in (f"http://localhost:{WEB_PORT}", f"http://127.0.0.1:{WEB_PORT}")

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, b"verboten", "text/plain; charset=utf-8")
        pages = {"/": DASHBOARD_FILE, "/index.html": DASHBOARD_FILE, "/mini": MINI_FILE}
        if self.path in pages:
            try:
                body = pages[self.path].read_bytes()
            except FileNotFoundError:
                return self._send(404, f"{pages[self.path].name} fehlt".encode(), "text/plain; charset=utf-8")
            return self._send(200, body, "text/html; charset=utf-8")
        if self.path == "/api/state":
            with STATE_LOCK:
                data = dict(STATE, events=list(EVENTS))
            return self._send(200, json.dumps(data).encode("utf-8"), "application/json")
        self._send(404, b"nicht gefunden", "text/plain; charset=utf-8")

    def do_POST(self):
        # Nur vom eigenen Dashboard: richtiger Host, passender Origin, eigener Header
        if not (self._host_ok() and self._origin_ok() and self.headers.get("X-PD-Filter") == "1"):
            return self._json(403, {"error": "verboten"})
        if self.path == "/api/override":
            err, text = hand_over_shift()
            if err:
                log(f"Override fehlgeschlagen: {err}")
                add_event("error", f"Override fehlgeschlagen: {err}")
                return self._json(502, {"error": err})
            log(text)
            add_event("info", text)
            with STATE_LOCK:
                STATE["shift"] = None
            return self._json(200, {"ok": True, "text": text})
        if self.path == "/api/override/remove":
            err, text = take_back_shift()
            if err:
                log(f"Zurueckholen fehlgeschlagen: {err}")
                add_event("error", f"Zurueckholen fehlgeschlagen: {err}")
                return self._json(502, {"error": err})
            log(text)
            add_event("info", text)
            return self._json(200, {"ok": True, "text": text})
        if self.path not in ACTIONS and self.path not in (
                "/api/customers/add", "/api/customers/remove", "/api/settings"):
            return self._json(404, {"error": "nicht gefunden"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, AttributeError):
            return self._json(400, {"error": "ungueltige Anfrage"})

        if self.path == "/api/settings":
            err, changed = update_settings(body)
            if err:
                return self._json(400, {"error": err})
            if changed:
                text = "Einstellungen geaendert: " + ", ".join(changed)
                log(text)
                add_event("info", text)
            return self._json(200, {"ok": True})

        if self.path.startswith("/api/customers/"):
            name = str(body.get("name", ""))
            adding = self.path.endswith("/add")
            err = edit_customers(add=name) if adding else edit_customers(remove=name)
            if err:
                return self._json(400, {"error": err})
            text = f"Kunde {'hinzugefuegt' if adding else 'entfernt'}: {name.strip()}"
            log(text)
            add_event("info", text)
            return self._json(200, {"ok": True})

        status, kind, label = ACTIONS[self.path]
        incident_id = str(body.get("id", ""))
        if not ID_RE.match(incident_id):
            return self._json(400, {"error": "ungueltige Incident-ID"})

        with STATE_LOCK:
            inc = next((i for i in STATE["incidents"] + STATE["acked"] if i["id"] == incident_id), None)
        err = set_incident_status(incident_id, status)
        if err:
            log(f"{label} fehlgeschlagen ({incident_id}): {err}")
            add_event("error", f"{label} fehlgeschlagen: {err}")
            return self._json(502, {"error": err})

        log(f"{label}: {show(inc['title']) if inc else incident_id}")
        with STATE_LOCK:
            STATE["incidents"] = [i for i in STATE["incidents"] if i["id"] != incident_id]
            STATE["acked"] = [i for i in STATE["acked"] if i["id"] != incident_id]
            # Sofort oben anzeigen, nicht erst nach der naechsten Abfrage
            if status == "acknowledged" and inc:
                STATE["acked"].insert(0, {k: inc.get(k) for k in ("id", "title", "service", "url", "customer")}
                                      | {"acked_at": datetime.now(TZ).isoformat()})
        if inc:
            add_event(kind, f"✓ {label}",
                      {"title": inc["title"], "service": {"summary": inc["service"]}, "html_url": inc["url"]},
                      inc.get("customer"))
        else:
            add_event(kind, f"✓ {label} ({incident_id})")
        self._json(200, {"ok": True})

    def log_message(self, *args):
        pass  # keine Zugriffe ins Log schreiben


def start_dashboard():
    if not WEB_PORT:
        return
    try:
        server = ThreadingHTTPServer(("127.0.0.1", WEB_PORT), DashboardHandler)
    except OSError as e:
        log(f"Live-Ansicht nicht gestartet: Port {WEB_PORT} ist belegt ({e.strerror}). "
            f"Filter laeuft trotzdem; anderen WEB_PORT in config.env eintragen.")
        add_event("error", f"Live-Ansicht: Port {WEB_PORT} belegt")
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"Live-Ansicht: http://localhost:{WEB_PORT}")


# ---------- Hauptschleife ----------

def poll_once(seen):
    customers = load_customers()
    incidents = fetch_incidents("triggered")
    current_ids = {i["id"] for i in incidents}
    view = []

    for inc in incidents:
        decision, customer = classify(inc, customers)
        silent = wants_silent(decision, customer)
        alarmed = decision == "alarm" and inc["id"] in seen

        if inc["id"] not in seen:
            title = show(inc.get("title"))
            who = "***" if QUIET else customer
            send_loud = decision == "alarm"
            failed = False
            if send_loud or silent:
                try:
                    notify(inc, customer, loud=send_loud)
                except Exception as e:
                    # Nicht als gesehen markieren -> naechster Durchlauf versucht es erneut
                    log(f"ntfy-Fehler, neuer Versuch spaeter: {e}")
                    add_event("error", f"ntfy-Fehler: {e}", inc, customer)
                    failed = True

            if failed:
                decision = "pending"
            elif send_loud:
                alarmed = True
                log(f"ALARM laut [{who}] {title}")
                add_event("alarm", "Laut", inc, customer)
            elif silent:
                log(f"leise Mitteilung [{who or service_name(inc)}] {title}")
                add_event("silent", "Leise Mitteilung", inc, customer)
            elif decision == "service":
                log(f"ignoriert (Service {service_name(inc)}): {title}")
                add_event("service", "Service gefiltert", inc, customer)
            else:
                log(f"ignoriert: {title}")
                add_event("customer", "Kein Kunde von dir", inc)
            if not failed:
                seen.add(inc["id"])

        view.append({
            "id": inc["id"],
            "title": inc.get("title", ""),
            "service": service_name(inc),
            "created_at": inc.get("created_at", ""),
            "url": inc.get("html_url", ""),
            "decision": "silent" if silent and decision in ("service", "customer") else decision,
            "customer": customer,
            "alarmed": alarmed,
        })

    # Nur IDs behalten, die noch offen sind -> Datei waechst nicht endlos
    seen &= current_ids
    save_seen(seen)

    with STATE_LOCK:
        STATE.update(last_poll=now_str(), last_error=None, customers=customers,
                     incidents=sorted(view, key=lambda v: v["created_at"], reverse=True))

    # Erst nach den Alarmen: ein Fehler hier darf keine Benachrichtigung verhindern
    if MY_USER_ID is None:
        find_my_user_id()
    acked = fetch_my_acked(customers)
    with STATE_LOCK:
        STATE.update(acked=acked, acked_mine=bool(MY_USER_ID))


def main():
    if not PD_API_TOKEN or not NTFY_TOPIC:
        sys.exit("Bitte PD_API_TOKEN und NTFY_TOPIC setzen.")

    seen = load_seen()
    window = f", nur {START_HOUR:02d}-{END_HOUR:02d} Uhr" if ONLY_IN_WINDOW else ""
    log(f"AN. Intervall {POLL_SECONDS}s, {len(load_customers())} Kunden{window}. Stoppen mit Strg+C.")
    with STATE_LOCK:
        STATE["started"] = now_str()
        STATE["settings"] = current_settings()
        STATE["overrides"] = load_overrides()
    add_event("info", "Filter eingeschaltet")
    start_dashboard()

    paused = None
    while True:
        # Ausserhalb Zeitfenster / ohne Schedule pausieren statt beenden, damit es "an" bleibt
        if not in_time_window():
            reason = "außerhalb Zeitfenster"
        elif not on_call_now() and ONLY_ON_CALL:
            reason = "kein Schedule aktiv"
        else:
            reason = None
        if reason != paused:
            text = f"Pausiert: {reason}" if reason else "Wieder aktiv"
            log(text)
            add_event("info", text)
            paused = reason
            with STATE_LOCK:
                STATE["paused"] = reason
        if reason:
            # Kundenliste auch in der Pause aktuell halten, sonst bleibt die Live-Ansicht leer
            with STATE_LOCK:
                STATE["customers"] = load_customers()
            time.sleep(60)
            continue

        try:
            poll_once(seen)
        except Exception as e:
            log(f"Fehler: {e}")
            add_event("error", f"Fehler beim Abfragen: {e}")
            with STATE_LOCK:
                STATE["last_error"] = str(e)

        time.sleep(POLL_SECONDS)


def test_title(title, service):
    """Trockentest ohne PagerDuty: python pd_filter.py --test "Titel" "CSOC (High)" """
    customers = load_customers()
    inc = {"title": title, "service": {"summary": service}}
    decision, customer = classify(inc, customers)
    print(f"Kundenliste: {customers}")
    print(f"Service-Filter: {SERVICE_FILTER or 'alle'}")
    print(f"Titel: {title!r}  |  Service: {service!r}")
    print(f"Leise Mitteilungen fuer: {SILENT_FOR}")
    if decision == "alarm":
        print(f"-> LAUT (Kunde: {customer})")
    elif wants_silent(decision, customer):
        print(f"-> LEISE Mitteilung ohne Ton ({'Kunde: ' + customer if customer else 'kein Kunde'}, "
              f"{'Service passt nicht' if decision == 'service' else 'Service passt'})")
    elif decision == "service":
        print("-> ignoriert: Service passt nicht zum Service-Filter")
    else:
        print("-> ignoriert: kein Kunde aus der Liste im Titel")


def on_sigterm(*_):
    """kill (z.B. ./pd-filter.sh aus) genauso sauber beenden wie Strg+C."""
    raise KeyboardInterrupt


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--test":
        test_title(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "CSOC (High)")
        sys.exit(0)
    signal.signal(signal.SIGTERM, on_sigterm)
    try:
        main()
    except KeyboardInterrupt:
        log("AUS.")
