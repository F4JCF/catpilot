@echo off
REM Construit CATPilot.exe (Python 3.10 ou plus requis : https://www.python.org)
python -m pip install --upgrade -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name CATPilot run.py
echo.
echo L'executable se trouve dans dist\CATPilot.exe
pause
