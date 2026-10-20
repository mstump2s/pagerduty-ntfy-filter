@echo off
REM PagerDuty-Filter starten (Windows). Laeuft in einem minimierten Fenster "PD-Filter".
cd /d "%~dp0"
tasklist /V /FI "WINDOWTITLE eq PD-Filter*" | find /I "PD-Filter" >nul
if not errorlevel 1 (
  echo Laeuft schon.
  timeout /t 3 >nul
  exit /b
)
REM Eigene Python-Umgebung im Ordner (einmalig), damit requests sicher da ist
if not exist ".venv\Scripts\python.exe" (
  echo Richte Python-Umgebung ein ^(einmalig^)...
  python -m venv .venv 2>nul || py -3 -m venv .venv
  if not exist ".venv\Scripts\python.exe" (
    echo venv konnte nicht erstellt werden. Ist Python installiert?
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -c "import requests" 2>nul
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install --quiet requests
  if errorlevel 1 (
    echo Installation von requests fehlgeschlagen.
    pause
    exit /b 1
  )
)
start "PD-Filter" /min cmd /c ".venv\Scripts\python.exe pd_filter.py >> pd_filter.log 2>&1"
echo AN. Log: pd_filter.log  ^|  Live-Ansicht: ansicht.bat
timeout /t 3 >nul
