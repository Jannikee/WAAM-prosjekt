@echo off
rem builds q_rng.cs in place with the in-box C# compiler - zero installs
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
%CSC% /nologo /out:q_rng.exe q_rng.cs
echo built q_rng.exe
