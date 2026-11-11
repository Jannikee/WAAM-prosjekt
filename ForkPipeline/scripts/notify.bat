@echo off
rem notify.bat - WHAT: pushes "logging done" to the phone (ntfy.sh, free,
rem   no account).
rem WHAT it does: wrapper so notify.ps1 runs even when .ps1 opens in an
rem   editor (the .ps1 self-configures its topic on first run).
rem WHY it's here: wire it as an on_stop rule for a silent ping when a log
rem   closes - the logger never waits on it (fire-and-forget, lonely script).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0notify.ps1"
