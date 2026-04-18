@echo off
title Luna RPG v8
cd /d D:\luna-rpg-v8

echo.
echo  ============================================================
echo   LUNA RPG v8 - World Simulation + Complete Poker
echo  ============================================================
echo.

:: Controlla argomenti
set ARGS=
if "%1"=="--no-media" (
    set ARGS=--no-media
    echo  [Media] DISABILITATA - Solo testo
) else if "%1"=="--debug" (
    set ARGS=--no-media --log-level DEBUG
    echo  [Media] DISABILITATA - Modalita DEBUG
) else (
    echo  [Media] ABILITATA - RunPod
)
echo.

:: Avvia nel terminale corrente
D:\luna-rpg-v8\.venv\Scripts\python.exe -m luna %ARGS%

echo.
if %errorlevel% neq 0 (
    echo  [ERRORE] Uscito con codice %errorlevel%
) else (
    echo  [OK] Chiuso correttamente
)
pause
