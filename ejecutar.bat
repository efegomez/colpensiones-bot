@echo off
REM ============================================================
REM  ejecutar.bat — Lanza el bot de Colpensiones en Windows
REM  Úsalo en el Programador de Tareas de Windows para cron.
REM ============================================================

SET SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

echo [%date% %time%] Iniciando Colpensiones Bot...
python colpensiones_bot.py >> logs\cron_windows.log 2>&1
echo [%date% %time%] Ejecucion finalizada. Revisa logs\cron_windows.log

pause
