@echo off
rem Bench start - one double-click, the whole pipeline alive:
rem   1. pose_watcher (settings: pose_watcher\pose_watcher.conf;
rem      live mode waits for the robot forever, streams continuously)
rem   2. welder_watcher (settings: scripts\welder_watcher.conf;
rem      the welder's display set + the recipe witness words)
rem   3. the fork logger GUI (press Connect for the DAQ, then just weld)
rem All are single-instance: a running one wins, extra launches no-op.
start "pose_watcher" /min "%~dp0pose_watcher\pose_watcher.exe"
start "welder_watcher" /min "%~dp0scripts\welder_watcher.exe"
start "" "%~dp0QuantumXGuiFork.exe"
