@echo off
REM PagerDuty-Filter stoppen (Windows)
taskkill /FI "WINDOWTITLE eq PD-Filter*" /T /F >nul 2>&1
if errorlevel 1 (
  echo War nicht an.
) else (
  echo AUS.
)
timeout /t 3 >nul
