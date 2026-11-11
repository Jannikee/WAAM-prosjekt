@echo off
rem build.cmd - WHAT: rebuilds the GUI companion tools IN PLACE.
rem WHAT it does: kw_grapher.exe (live kW graph from the logger CSV),
rem   bell.exe (the C# port of bell.py), streams.exe (every stream field as
rem   live big numbers) - all with the in-box csc, zero installs.
rem WHY it's here: the .cs sources ship beside the exes so every tool is
rem   inspectable + repairable on any Windows box: edit, run this, done.
rem   (The pollers/watcher have their own build_*.cmd beside them.)
cd /d "%~dp0"
set CSC=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe
%CSC% /nologo /target:winexe /platform:anycpu /out:kw_grapher.exe ^
  /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:Microsoft.VisualBasic.dll ^
  kw_grapher.cs
if %errorlevel% neq 0 (echo BUILD FAILED: kw_grapher & exit /b 1)
echo BUILD OK: kw_grapher.exe
%CSC% /nologo /target:winexe /platform:anycpu /out:bell.exe ^
  /r:System.Windows.Forms.dll /r:System.Drawing.dll ^
  bell.cs
if %errorlevel% neq 0 (echo BUILD FAILED: bell & exit /b 1)
echo BUILD OK: bell.exe
%CSC% /nologo /target:winexe /platform:anycpu /out:streams.exe ^
  /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:Microsoft.VisualBasic.dll ^
  streams.cs
if %errorlevel% neq 0 (echo BUILD FAILED: streams & exit /b 1)
echo BUILD OK: streams.exe
