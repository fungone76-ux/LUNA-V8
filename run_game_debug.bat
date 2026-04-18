@echo off
title Luna RPG v8 - DEBUG
cd /d D:\luna-rpg-v8

echo.
echo  ============================================================
echo   LUNA RPG v8 - DEBUG MODE (no media, log level DEBUG)
echo  ============================================================
echo.

D:\luna-rpg-v8\.venv\Scripts\python.exe -m luna --no-media --log-level DEBUG

echo.
pause
