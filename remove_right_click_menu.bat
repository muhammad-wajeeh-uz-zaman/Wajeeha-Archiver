@echo off
rem Removes everything install_right_click_menu.bat added.
cd /d "%~dp0"
python wajeeha_archiver.py --unregister-shell
pause
