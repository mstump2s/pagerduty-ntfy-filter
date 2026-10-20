@echo off
REM Live-Ansicht im Browser oeffnen (Windows). Port kommt aus config.env (WEB_PORT).
cd /d "%~dp0"
set "PORT=8790"
for /f "tokens=1,* delims==" %%a in ('findstr /b /c:"WEB_PORT=" config.env 2^>nul') do set "PORT=%%b"
set "PORT=%PORT: =%"
start "" http://localhost:%PORT%
