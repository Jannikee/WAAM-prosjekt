@echo off
rem build_img1.cmd - WHAT: rebuilds img_cap1.exe (the one-shot photo tool) IN
rem PLACE from img_cap1.cs (the WinRT frame-server route: in-box facades +
rem the system namespace winmds).
rem WHY: the source ships beside the exe - inspectable + repairable on any
rem Windows box (csc ships with Windows; zero installs): edit, run this, done.
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe
set FX=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319
if not exist "%FX%\System.Runtime.dll" set FX=%WINDIR%\Microsoft.NET\Framework\v4.0.30319
set WM=%WINDIR%\System32\WinMetadata
"%CSC%" /nologo /target:winexe /unsafe /optimize+ ^
  /out:img_cap1.exe ^
  /r:System.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll ^
  /r:"%FX%\System.Runtime.dll" ^
  /r:"%FX%\System.Runtime.InteropServices.WindowsRuntime.dll" ^
  /r:"%WM%\Windows.Foundation.winmd" ^
  /r:"%WM%\Windows.Devices.winmd" ^
  /r:"%WM%\Windows.Media.winmd" ^
  /r:"%WM%\Windows.Graphics.winmd" ^
  /r:"%WM%\Windows.Storage.winmd" ^
  img_cap1.cs
if errorlevel 1 (
  echo BUILD FAILED
) else (
  echo built img_cap1.exe
)
