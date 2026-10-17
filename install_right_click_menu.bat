@echo off
rem Adds "Wajeeha Archiver" to the Explorer right-click menu (current user only, no admin needed).
cd /d "%~dp0"
python wajeeha_archiver.py --register-shell
pause
