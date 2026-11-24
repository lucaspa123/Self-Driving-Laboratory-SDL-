@echo off
rem Abre el programa del SDL. La primera vez instala lo necesario (tarda unos minutos).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Preparando el programa por primera vez...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo No se encontro Python. Instale Python 3.10 o mas nuevo desde https://www.python.org y vuelva a intentar.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo No se pudieron instalar las librerias. Revise la conexion a internet.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" iniciar.py
pause
