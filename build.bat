@echo off
REM Construit CATPilot.exe (Python 3.10 ou plus requis : https://www.python.org)
python -m pip install --upgrade -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name CATPilot --icon assets\catpilot.ico --add-data "assets\catpilot.ico;assets" --collect-all pyrtlsdrlib run.py
echo.
echo L'executable se trouve dans dist\CATPilot.exe
pause
