# pagerduty-ntfy-filter

Weniger Lärm im PagerDuty-Dienst: Das Tool fragt PagerDuty regelmäßig nach offenen
Incidents ab und schickt dir per [ntfy](https://ntfy.sh) nur dann einen **lauten** Push
aufs Handy, wenn einer **deiner Kunden** im Titel steht und der Service passt.
Alles andere kommt als **leise** Mitteilung oder wird ignoriert.

Dazu gibt es eine Live-Ansicht im Browser, über die du Incidents direkt in
PagerDuty acknowledgen und resolven oder den Rest deiner Schicht abgeben kannst.

## Funktionen

- **Filter nach Kunde und Service:** Kundenliste als einfache Textdatei, Treffer per
  Teilstring im Incident-Titel (Groß-/Kleinschreibung egal), auch direkt in der
  Live-Ansicht pflegbar. Optionaler Service-Filter,
  z. B. nur `CSOC (High)` laut.
- **Laut oder leise:** Laute Alarme mit ntfy-Priorität *urgent*. Leise Mitteilungen
  ohne Ton, optional auf einem eigenen Topic.
- **Kein Doppel-Alarm:** Jeder Incident wird nur einmal gemeldet, auch nach einem Neustart.
- **Live-Ansicht** (`http://localhost:8790`, nur lokal erreichbar):
  - oben die offenen Incidents deiner Kunden, dann die von dir acknowledged Incidents
  - Ack und Resolve mit einem Klick
  - Zähler-Kacheln als Filter, Verlauf aller Entscheidungen
  - Einstellungen (leise Mitteilungen, Service-Filter, Schedule, Zeitfenster …) live
    ändern, ohne Neustart
- **Browser-Extension** (optional, Chrome/Edge): kompaktes Popup mit Ack/Resolve, Badge
  mit der Zahl offener Incidents deiner Kunden, Icon blinkt bei lauten Alarmen
- **Nur im Schedule aktiv** (`ONLY_ON_CALL=true`): Bist du laut PagerDuty gerade nicht
  on-call, pausiert der Filter und schickt nichts.
- **Schicht abgeben:** Ein Button legt einen Override von jetzt bis Schichtende auf
  einen anderen User an (`OVERRIDE_USER`, z. B. ein Dummy-User). Nach einer Pause holt
  „Schicht zurückholen“ sie wieder zurück (löscht den Override).
- **Arbeitszeiten** (`ONLY_IN_WINDOW=true`): nur zu festen Zeiten aktiv.

## Schnellstart

Voraussetzung: Python 3.9 oder neuer und ein PagerDuty-API-Key.

```bash
git clone https://github.com/mstump2s/pagerduty-ntfy-filter.git
cd pagerduty-ntfy-filter
cp config.env.example config.env          # PD_API_TOKEN und NTFY_TOPIC eintragen
cp customers.txt.example customers.txt    # eigene Kunden eintragen
chmod +x pd-filter.sh
./pd-filter.sh an                         # startet im Hintergrund
./pd-filter.sh ansicht                    # Live-Ansicht öffnen
```

Unter Windows: `an.bat`, `aus.bat`, `ansicht.bat`.

Dann in der [ntfy-App](https://ntfy.sh) dein Topic abonnieren. Prüfen, wie ein Titel
behandelt würde, geht ohne PagerDuty mit `./pd-filter.sh test "Titel" "Service"`.

Alle Einstellungen und Details stehen in der [Anleitung](ANLEITUNG.md).

## Sicherheit

- `config.env` (API-Key, ntfy-Topics) und `customers.txt` sind in `.gitignore` und
  gehören nicht ins Repo.
- ntfy-Topics auf ntfy.sh sind öffentlich lesbar, wenn man den Namen kennt: einen
  langen, zufälligen Namen wählen. Mit `QUIET=true` landen keine Incident-Titel im Log
  und keine Kundendaten in den ntfy-Mitteilungen: dort steht dann nur „Incident“.
- Die Live-Ansicht lauscht nur auf `127.0.0.1` und nimmt Aktionen nur von der eigenen
  Seite an.
