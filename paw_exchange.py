"""
PAW Exchange in der Live-Ansicht: wartende Uploads vom PAW anzeigen und per Klick
mit Claude (Enterprise-Account) analysieren lassen.

Alles Kryptografische und Git macht analyze.sh aus dem analyze-Skill; hier wird es nur
aufgerufen. Ohne analyze.sh ist die Seite aus.

  PAW_ANALYZE         optional, Pfad zu analyze.sh.
                      Standard: ~/.claude-work/skills/analyze/analyze.sh
  PAW_CLAUDE_CONFIG   optional, Claude-Config des Enterprise-Accounts. Standard: ~/.claude-work
  PAW_CCUSAGE         optional, Befehl fuer die Kosten pro Analyse. Standard: npx --yes ccusage@20.0.45
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path

ANALYZE_SH = Path(os.path.expanduser(os.environ.get("PAW_ANALYZE", "~/.claude-work/skills/analyze/analyze.sh")))
CLAUDE_CONFIG = Path(os.path.expanduser(os.environ.get("PAW_CLAUDE_CONFIG", "~/.claude-work")))
WORK_DIR = Path.home() / ".paw-exchange"
UPLOAD_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}$")
CACHE_SECONDS = 20
COST_SECONDS = 120
CCUSAGE = shlex.split(os.environ.get("PAW_CCUSAGE", "npx --yes ccusage@20.0.45"))
# Claude legt die Sitzungen unter projects/<Pfad mit - statt / und .> ab
SESSIONS_DIR = CLAUDE_CONFIG / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(WORK_DIR))
SESSION_UPLOAD_RE = re.compile(r"Upload: +(\d{4}-\d{2}-\d{2}_\d{6})|<command-args>\s*(\d{4}-\d{2}-\d{2}_\d{6})")

_lock = threading.Lock()
_cache = {"at": 0.0, "data": None}
_started = {}                   # Upload-ID -> Zeitpunkt, an dem die Analyse gestartet wurde
_cost_lock = threading.Lock()
_cost_cache = {"at": 0.0, "data": []}
_session_uploads = {}           # Sitzungsdatei -> ((mtime, size), Upload-ID oder None)

# Automatischer Start laeuft im Dienst, nicht im Browser: neue Uploads starten nach AUTO_SEC Sekunden,
# auch wenn die PAW-Seite nicht offen ist. Nur Uploads, die erst nach dem Start des Dienstes auftauchen
# und juenger als AUTO_MAX_AGE sind; jeder Upload hoechstens einmal automatisch.
AUTO_SEC = 10
AUTO_MAX_AGE = 15 * 60
AUTO_TICK = 2
_auto = {}                      # Upload-ID -> Zeitpunkt (epoch), zu dem die Analyse automatisch startet
_auto_handled = set()           # gestoppt, schon automatisch gestartet oder manuell gestartet
_auto_seen = None               # Upload-IDs beim Start des Dienstes
_auto_thread = None


def enabled():
    return ANALYZE_SH.is_file()


def _run(*args, timeout=120):
    # Die Live-Ansicht ist kein Claude: Variablen einer evtl. startenden Claude-Sitzung nicht weitergeben,
    # sonst blockiert analyze.sh (es laesst Daten nur an den Enterprise-Account)
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CONFIG_DIR")}
    try:
        r = subprocess.run([str(ANALYZE_SH), *args], capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return "analyze.sh hat nicht rechtzeitig geantwortet", ""
    if r.returncode != 0:
        return (r.stderr.strip() or r.stdout.strip() or "analyze.sh fehlgeschlagen").lstrip("✗ "), ""
    return None, r.stdout


def state(force=False):
    """Uploads und Ergebnisse, hoechstens alle CACHE_SECONDS frisch aus dem Repo geholt."""
    with _lock:
        if not force and _cache["data"] and time.monotonic() - _cache["at"] < CACHE_SECONDS:
            return _cache["data"] | {"auto": dict(_auto), "costs": costs()}
        err, out = _run("list", "--json")
        if err:
            data = dict(_cache["data"] or {"uploads": [], "results": []}, error=err)
        else:
            data = json.loads(out) | {"error": None}
            ids = {u["id"] for u in data["uploads"]}
            for k in [k for k in _started if k not in ids]:
                del _started[k]
        data["started"] = {k: v for k, v in _started.items()}
        data["auto"] = dict(_auto)
        data["updated"] = time.time()
        _cache.update(at=time.monotonic(), data=data)
        return data | {"costs": costs()}


def _session_upload(path):
    """Upload-ID, die eine Claude-Sitzung analysiert hat (aus der get-Ausgabe oder den /analyze-Argumenten)."""
    st = path.stat()
    key = (st.st_mtime, st.st_size)
    hit = _session_uploads.get(path)
    if hit and hit[0] == key:
        return hit[1]
    found = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = SESSION_UPLOAD_RE.search(line)
            if m:
                found = m.group(1) or m.group(2)
                break
    _session_uploads[path] = (key, found)
    return found


def _ccusage_sessions():
    path = os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin"
    exe = shutil.which(CCUSAGE[0], path=path)
    if not exe:
        return []
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"} | {"CLAUDE_CONFIG_DIR": str(CLAUDE_CONFIG), "PATH": path}
    try:
        r = subprocess.run([exe, *CCUSAGE[1:], "session", "--json", "--offline"], capture_output=True, text=True,
                           timeout=90, env=env, cwd=str(Path.home()))
        return json.loads(r.stdout).get("session", []) if r.returncode == 0 else []
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return []


def costs():
    """Kosten pro Analyse-Lauf laut ccusage (eine Claude-Sitzung = ein Lauf, Nachfragen im Chat zaehlen mit). Neueste zuerst."""
    with _cost_lock:
        if time.monotonic() - _cost_cache["at"] < COST_SECONDS:
            return _cost_cache["data"]
        uploads = {}
        if SESSIONS_DIR.is_dir():
            uploads = {p.stem: u for p in SESSIONS_DIR.glob("*.jsonl") if (u := _session_upload(p))}
        runs = []
        for s in _ccusage_sessions() if uploads else []:
            upload_id = uploads.get(s.get("period"))
            if upload_id:
                runs.append({"id": upload_id, "session": s.get("period"), "cost": s.get("totalCost") or 0,
                             "model": ", ".join(m.replace("claude-", "") for m in s.get("modelsUsed") or []),
                             "tokens": s.get("totalTokens") or 0, "cacheRead": s.get("cacheReadTokens") or 0,
                             "last": (s.get("metadata") or {}).get("lastActivity") or ""})
        data = sorted(runs, key=lambda c: c["last"], reverse=True)
        _cost_cache.update(at=time.monotonic(), data=data)
        return data


def _known(upload_id):
    if not UPLOAD_ID_RE.match(upload_id):
        return False
    return any(u["id"] == upload_id for u in state()["uploads"])


def analyze(upload_id, note="", boost=False):
    """Oeffnet iTerm mit Claude (Enterprise-Account), das /analyze fuer diesen Upload ausfuehrt.
    boost: /analyze-boost statt /analyze – gleicher Ablauf, aber auf Opus statt Sonnet."""
    if not _known(upload_id):
        return "Upload nicht gefunden"
    run_dir = WORK_DIR / "launch"
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt = f"/{'analyze-boost' if boost else 'analyze'} {upload_id}"
    if note.strip():
        prompt += "\n\nZusätzliche Hinweise des Analysten (vom Mac):\n" + note.strip()
    # Eigene Dateien pro Start, damit sich zwei kurz nacheinander gestartete Laeufe nicht ueberschreiben
    stem = f"{upload_id}_{time.strftime('%H%M%S')}"
    prompt_file = run_dir / f"{stem}.prompt"
    prompt_file.write_text(prompt, encoding="utf-8")
    cmd = run_dir / f"{stem}.command"
    # Beendet sich Claude gleich wieder, bleibt das Fenster offen, damit die Fehlermeldung lesbar ist
    cmd.write_text(
        "#!/bin/zsh -l\n"
        f"cd {shlex.quote(str(WORK_DIR))}\n"
        f"CLAUDE_CONFIG_DIR={shlex.quote(str(CLAUDE_CONFIG))} claude \"$(<{shlex.quote(str(prompt_file))})\"\n"
        "rc=$?\n"
        "if (( SECONDS < 30 )); then print \"\\nClaude hat sich nach $SECONDS s beendet (Exit $rc). Enter schliesst das Fenster.\"; read -r; fi\n",
        encoding="utf-8")
    cmd.chmod(0o700)
    r = subprocess.run(["open", "-a", "iTerm", str(cmd)], capture_output=True, text=True)
    if r.returncode != 0:
        r = subprocess.run(["open", "-a", "Terminal", str(cmd)], capture_output=True, text=True)
        if r.returncode != 0:
            return "Terminal konnte nicht geoeffnet werden: " + r.stderr.strip()
    with _lock:
        _started[upload_id] = time.time()
        _auto.pop(upload_id, None)
        _auto_handled.add(upload_id)
        if _cache["data"]:
            _cache["data"]["started"] = dict(_started)
    return None


def done(upload_id):
    """Upload aus dem Repo loeschen (analyze.sh done)."""
    if not _known(upload_id):
        return "Upload nicht gefunden"
    err, _ = _run("done", upload_id)
    if not err:
        with _lock:
            _started.pop(upload_id, None)
        state(force=True)
    return err


def stop_auto(upload_id):
    """Automatischen Start fuer diesen Upload abbrechen (Stopp oder + Hinweis auf der Seite)."""
    if not UPLOAD_ID_RE.match(upload_id):
        return "Upload nicht gefunden"
    with _lock:
        _auto.pop(upload_id, None)
        _auto_handled.add(upload_id)
    return None


def _upload_age(u):
    try:
        return time.time() - time.mktime(time.strptime(u["id"], "%Y-%m-%d_%H%M%S"))
    except (KeyError, ValueError):
        return None


def _auto_step():
    global _auto_seen
    try:
        data = state()
    except Exception:
        return
    if data.get("error") and not data.get("uploads"):
        return
    ids = {u["id"] for u in data["uploads"]}
    if _auto_seen is None:
        _auto_seen = ids
        return
    with_result = {r.get("inbox") for r in data["results"]}
    due = []
    with _lock:
        for k in [k for k in _auto if k not in ids]:
            del _auto[k]
        for u in data["uploads"]:
            uid = u["id"]
            age = _upload_age(u)
            eligible = (uid not in _auto_seen and uid not in _auto_handled and not u.get("error")
                        and uid not in with_result and uid not in _started and age is not None and age < AUTO_MAX_AGE)
            if not eligible:
                _auto.pop(uid, None)
            elif uid not in _auto:
                _auto[uid] = time.time() + AUTO_SEC
            elif _auto[uid] <= time.time():
                del _auto[uid]
                _auto_handled.add(uid)      # nie zweimal automatisch starten, auch wenn der Start scheitert
                due.append(uid)
    for uid in due:
        err = analyze(uid)
        _auto_log(f"PAW: automatisch gestartet ({uid})" if not err else f"PAW: automatischer Start fehlgeschlagen ({uid}): {err}")


def _auto_log(text):
    try:
        with open(WORK_DIR / "auto.log", "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
    except OSError:
        pass


def start_auto():
    """Hintergrund-Thread fuer den automatischen Start (einmal pro Prozess)."""
    global _auto_thread
    if _auto_thread or not enabled():
        return

    def loop():
        while True:
            _auto_step()
            time.sleep(AUTO_TICK)

    _auto_thread = threading.Thread(target=loop, name="paw-auto", daemon=True)
    _auto_thread.start()
