@echo off
rem Starts Wajeeha Archiver without a console window.
cd /d "%~dp0"
start "" pythonw "%~dp0wajeeha_archiver.py" %*
