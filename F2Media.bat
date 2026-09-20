@echo off
chcp 65001 >nul 2>&1
setlocal

:: Launch the F2Media GUI (tkinter) with no console window.
:: Uses pythonw.exe (windowless Python) when available.

set "SCRIPT_DIR=%~dp0"

where pythonw >nul 2>&1
if %errorlevel% == 0 (
    start "" pythonw "%SCRIPT_DIR%gui.py"
) else (
    start "" /min python "%SCRIPT_DIR%gui.py"
)
endlocal
