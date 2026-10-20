#!/usr/bin/env bash
# PagerDuty-Filter an/aus fuer Mac und Linux
#   ./pd-filter.sh an       starten (im Hintergrund)
#   ./pd-filter.sh aus      stoppen
#   ./pd-filter.sh status   laeuft es?
#   ./pd-filter.sh log      Log live ansehen (Strg+C beendet nur die Anzeige)
#   ./pd-filter.sh ansicht  Live-Ansicht im Browser oeffnen
#   ./pd-filter.sh test "Titel" ["Service"]   pruefen, ob ein Titel bimmeln wuerde

cd "$(dirname "$0")" || exit 1
PIDFILE="pd_filter.pid"
LOGFILE="pd_filter.log"
VENV=".venv"
PY="$VENV/bin/python"

# Eigene Python-Umgebung im Ordner (einmalig), damit requests sicher da ist
ensure_venv() {
  if [ ! -x "$PY" ]; then
    echo "Richte Python-Umgebung ein (einmalig)..."
    python3 -m venv "$VENV" || { echo "venv konnte nicht erstellt werden."; exit 1; }
  fi
  if ! "$PY" -c "import requests" 2>/dev/null; then
    "$PY" -m pip install --quiet requests || { echo "Installation von requests fehlgeschlagen."; exit 1; }
  fi
}

running() {
  [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

case "$1" in
  an|start|on)
    if running; then
      echo "Laeuft schon (PID $(cat "$PIDFILE"))."
      exit 0
    fi
    ensure_venv
    nohup "$PY" pd_filter.py >> "$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    sleep 2
    if running; then
      echo "AN (PID $(cat "$PIDFILE")). Log: $LOGFILE  |  Live-Ansicht: ./pd-filter.sh ansicht"
    else
      echo "Start fehlgeschlagen, letzte Log-Zeilen:"
      tail -n 5 "$LOGFILE"
      rm -f "$PIDFILE"
      exit 1
    fi
    ;;
  aus|stop|off)
    if running; then
      PID="$(cat "$PIDFILE")"
      kill "$PID"
      # bis zu 5 s auf sauberes Beenden warten
      for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done
      kill -0 "$PID" 2>/dev/null && kill -9 "$PID"
      rm -f "$PIDFILE"
      echo "AUS."
    else
      rm -f "$PIDFILE"
      echo "War nicht an."
    fi
    ;;
  status)
    if running; then echo "AN (PID $(cat "$PIDFILE"))"; else echo "AUS"; fi
    ;;
  log)
    tail -n 20 -f "$LOGFILE"
    ;;
  test)
    ensure_venv
    "$PY" pd_filter.py --test "$2" "${3:-CSOC (High)}"
    ;;
  ansicht|view)
    PORT=$(grep -E '^WEB_PORT=' config.env 2>/dev/null | cut -d= -f2 | tr -d ' "')
    URL="http://localhost:${PORT:-8790}"
    running || echo "Hinweis: Filter ist AUS, die Ansicht zeigt erst etwas nach './pd-filter.sh an'."
    if command -v open >/dev/null; then open "$URL"
    elif command -v xdg-open >/dev/null; then xdg-open "$URL"
    else echo "Im Browser oeffnen: $URL"; fi
    ;;
  *)
    echo "Benutzung: $0 an | aus | status | log | ansicht | test \"Titel\" [\"Service\"]"
    exit 1
    ;;
esac
