@echo off
rem Spusteni QKD demonstratoru: Python + knihovny + GUI
cd /d "%~dp0"

rem 1) stahni nejnovejsi verzi kodu (jen kdyz je nainstalovany git)
where git >nul 2>nul && git pull

rem 2) kdyz chybi Python, nainstaluj ho
where python >nul 2>nul || (
  echo Instaluji Python...
  winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
  set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
)

rem 3) nainstaluj / aktualizuj knihovny
python -m pip install --upgrade pip
python -m pip install --upgrade -r pc\requirements.txt

rem 4) spust GUI
python pc\qkd_gui.py
pause
