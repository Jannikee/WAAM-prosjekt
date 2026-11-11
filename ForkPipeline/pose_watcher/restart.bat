@echo off
taskkill /IM pose_watcher.exe >nul 2>nul
timeout /t 1 >nul
start "pose_watcher" /min "%~dp0pose_watcher.exe"
