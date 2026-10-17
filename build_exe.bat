@echo off
rem ------------------------------------------------------------------
rem  Builds WajeehaArchiver.exe  (folder:  dist\WajeehaArchiver\)
rem  Needs Python 3.9+ from python.org with "tcl/tk" installed.
rem ------------------------------------------------------------------
cd /d "%~dp0"
echo [1/4] Installing helper packages...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
echo [2/4] Creating the program icon...
python -c "from wajeeha import icons; icons.make_ico('wajeeha.ico')"
echo [3/4] Building the program (this takes a few minutes)...
python -m PyInstaller --noconfirm --clean --windowed --name WajeehaArchiver --icon wajeeha.ico ^
  --collect-all py7zr --collect-all pyzipper --collect-all rarfile --collect-all tkinterdnd2 ^
  --collect-all send2trash wajeeha_archiver.py
echo [4/4] Copying the optional tools folder...
if exist tools xcopy /E /I /Y tools dist\WajeehaArchiver\tools >nul
echo.
echo Done!  Your program is:  dist\WajeehaArchiver\WajeehaArchiver.exe
echo Open it, then go to  Settings ^> Explorer integration  to add the right-click menu.
pause
