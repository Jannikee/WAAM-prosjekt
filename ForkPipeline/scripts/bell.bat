@echo off
rem bell.bat - WHAT: rings the bell (bell.py in a 400x400 window, closes on
rem   any key or click; a real synthesized ring).
rem WHAT it does: wrapper so bell.py runs even when .py opens in an editor;
rem   prefers pythonw (no console window), falls back to python.
rem WHY it's here: the trigger-system demo companion - any logger rule can
rem   `run bell.bat` for an attention signal. (bell.cs/bell.exe = the C#
rem   port, built by build.cmd; this bat runs the python original.)
set "SCRIPT=%~dp0bell.py"
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "%SCRIPT%"
) else (
  start "" python "%SCRIPT%"
)
