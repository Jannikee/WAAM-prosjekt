@echo off
rem build_welder.cmd - builds welder_watcher.cs (the console app) with the
rem in-box .NET Framework compiler. WHAT: rebuilds the exe IN PLACE.
rem WHY: zero installs (csc + ClientWebSocket in System.dll ship with Windows)
rem and the .cs ships beside the exe so the tool is inspectable + repairable
rem on any Windows box: edit the source, run this, done.
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe
"%CSC%" /nologo /target:exe /optimize+ ^
  /out:welder_watcher.exe ^
  /r:System.dll ^
  welder_watcher.cs
if errorlevel 1 (
  echo BUILD FAILED
) else (
  echo built welder_watcher.exe
)
