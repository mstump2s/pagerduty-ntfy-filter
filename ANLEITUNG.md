# PD-Filter – Anleitung

Fragt PagerDuty regelmäßig nach offenen (triggered) Incidents ab und schickt dir
per [ntfy](https://ntfy.sh) einen **lauten** Push nur dann, wenn einer deiner Kunden im
Titel steht **und** der Service passt (Standard: `CSOC (High)`). Andere Incidents
kommen auf Wunsch als **leise** Mitteilung (ohne Ton) oder werden ignoriert.
Dazu gibt es eine Live-Ansicht im Browser mit Ack- und Resolve-Buttons.

Voraussetzung: Python 3.9 oder neuer. `requests` wird beim ersten Start automatisch
in einer eigenen `.venv` im Ordner installiert.

## 1. Einrichten

1. **config.env anlegen:** `config.env.example` nach `config.env` kopieren und ausfüllen:
   - `PD_API_TOKEN` – persönlicher PagerDuty-API-Key
     (PagerDuty → My Profile → User Settings → API Access → Create API User Token)
   - `NTFY_TOPIC` – ein langer, schwer erratbarer Name, z. B. `pd_max_8f3k2q91`
   - optional `NTFY_TOPIC_SILENT` – eigenes Topic für die leisen Mitteilungen
   - optional `PD_FROM_EMAIL` – nur bei einem *Account*-API-Key nötig (für Ack/Resolve)
   - Die übrigen Werte haben sinnvolle Standards und sind in der Datei erklärt.
2. **Kunden eintragen:** `customers.txt.example` nach `customers.txt` kopieren und
   einen Kunden pro Zeile eintragen.
   Groß-/Kleinschreibung ist egal, ein Treffer ist es, wenn der Text irgendwo im
   Incident-Titel vorkommt. Zeilen mit `#` sind Kommentare. Änderungen gelten ab
   dem nächsten Durchlauf, ohne Neustart.
   Mit TextEdit unbedingt als **reinen Text** speichern (Format → In reinen Text umwandeln).
   Alternativ in der Live-Ansicht: Feld „Kunde hinzufügen“ bzw. × am Kunden.
   Ohne Kunden wird **nichts** laut gemeldet (nicht etwa alles).
3. **ntfy-App** auf dem Handy installieren und dein Topic (bzw. beide Topics) abonnieren.
   Für laute Alarme in der App bei der Priorität „urgent“ Ton/Durchbrechen von
   „Nicht stören“ erlauben.

## 2. Starten und stoppen

**Mac / Linux** (im Ordner, einmalig `chmod +x pd-filter.sh`):

| Befehl | Wirkung |
|---|---|
| `./pd-filter.sh an` | startet im Hintergrund (legt beim ersten Mal die `.venv` an) |
| `./pd-filter.sh aus` | stoppt |
| `./pd-filter.sh status` | läuft es? |
| `./pd-filter.sh log` | Log live ansehen (Strg+C beendet nur die Anzeige) |
| `./pd-filter.sh ansicht` | Live-Ansicht im Browser öffnen |
| `./pd-filter.sh test "Titel" ["Service"]` | prüfen, ob ein Titel laut/leise/ignoriert wäre |

**Windows:** `an.bat` (startet minimiert im Fenster „PD-Filter“), `aus.bat`, `ansicht.bat`.

Nach Änderungen an `config.env` einmal aus- und wieder anschalten.

## 3. Live-Ansicht

`http://localhost:8790` (Port über `WEB_PORT` änderbar, nur auf dem eigenen Rechner
erreichbar). Zeigt Status, Kunden, offene Incidents mit Entscheidung und den Verlauf;
die Zähler-Kacheln oben filtern die Tabelle. **Ack** und **Resolve** setzen den
Incident direkt in PagerDuty (ohne Rückfrage).

Ganz oben stehen die offenen, noch nicht acknowledged Incidents **deiner Kunden**
(mit Ack/Resolve), darunter die Incidents, die **du** acknowledged hast, jeweils mit
Resolve-Button. Die Tabelle „Weitere offene Incidents“ enthält den Rest. Deinen PagerDuty-User erkennt das Tool am persönlichen API-Key;
bei einem Account-Key dafür `PD_FROM_EMAIL` setzen, sonst werden alle
acknowledged Incidents angezeigt.

Unter **Einstellungen** (aufklappen) lassen sich ändern: leise Mitteilungen
(`SILENT_FOR`), Service-Filter, „nur im Schedule“, Override-User, Zeitfenster,
Abfrage-Intervall und `QUIET`. Das gilt sofort, ohne Neustart, und wird in
`config.env` gespeichert. API-Key, ntfy-Topics und Port bleiben bewusst nur in der Datei.

**Optional als Browser-Extension** (Chrome, Edge): `chrome://extensions` öffnen,
oben rechts **Entwicklermodus** an, **Entpackte Erweiterung laden** und den Ordner
`extension` auswählen. Ein Klick aufs Icon öffnet die Live-Ansicht als Popup. Das Badge
zeigt die offenen Incidents deiner Kunden (`II` = pausiert, `!` = Fehler, `aus` = Filter
läuft nicht). Bei geändertem `WEB_PORT` den Port in den drei Dateien in `extension/`
anpassen und die Erweiterung neu laden.

## 4. Was wann passiert

| Kunde im Titel | Service passt | Ergebnis |
|---|---|---|
| ja | ja | 🔔 **laut** (ntfy-Priorität urgent) |
| ja | nein | 🔕 leise, wenn `SILENT_FOR=kunden` oder `alle` |
| nein | ja/nein | 🔕 leise nur bei `SILENT_FOR=alle`, sonst ignoriert |

Jeder Incident wird nur einmal gemeldet (gemerkt in `seen.json`). Schlägt der
ntfy-Versand fehl, wird es beim nächsten Durchlauf erneut versucht.

**Arbeitszeiten:** Mit `ONLY_IN_WINDOW=true` ist der Filter nur von `START_HOUR` bis
`END_HOUR` aktiv (Standard 8–18 Uhr, mit `WEEKDAYS_ONLY=true` nur Mo–Fr) und pausiert
sonst, ohne sich zu beenden.

**Nur im Schedule:** Mit `ONLY_ON_CALL=true` ist der Filter nur aktiv, solange du in
PagerDuty gerade in einem Schedule on-call bist (geprüft einmal pro Minute). Sonst
pausiert er: keine Abfrage, keine Mitteilungen. Kann der Status nicht geprüft werden
(eigener User unbekannt, PagerDuty nicht erreichbar), läuft er sicherheitshalber weiter.

**Schicht abgeben:** Solange du on-call bist, zeigt die Live-Ansicht oben deine Schicht
und den Button **„Rest der Schicht an CSOC Dummy abgeben“**. Ein Klick legt in PagerDuty
(ohne Rückfrage) einen Override von jetzt bis Schichtende auf `OVERRIDE_USER` an
(Standard `CSOC Dummy`, Name oder E-Mail). Mit `ONLY_ON_CALL=true` pausiert der Filter
danach automatisch.

## 5. Dateien

| Datei | Inhalt |
|---|---|
| `pd_filter.py` | das Programm |
| `dashboard.html` | Live-Ansicht |
| `config.env` | deine Einstellungen inkl. API-Key (**nicht weitergeben**) |
| `customers.txt` | deine Kundenliste (nicht im Repo, Vorlage: `customers.txt.example`) |
| `seen.json`, `pd_filter.log`, `pd_filter.pid` | werden automatisch angelegt |
