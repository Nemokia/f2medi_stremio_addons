@echo off
chcp 65001 >nul 2>&1
setlocal

set "SCRIPT_DIR=%~dp0"

:: ─── Priority 1: Standalone EXE in project root (no deps needed) ──
if exist "%SCRIPT_DIR%F2Media.exe" (
    start "" "%SCRIPT_DIR%F2Media.exe"
    endlocal
    exit /b 0
)

:: ─── Priority 2: Standalone EXE in dist folder ────────────────────
if exist "%SCRIPT_DIR%dist\F2Media.exe" (
    start "" "%SCRIPT_DIR%dist\F2Media.exe"
    endlocal
    exit /b 0
)

:: ─── Priority 3: Fallback to Python + WSL (development mode) ──────
where pythonw >nul 2>&1
if %errorlevel% == 0 (
    start "" pythonw "%SCRIPT_DIR%gui.py"
    endlocal
    exit /b 0
)

where python >nul 2>&1
if %errorlevel% == 0 (
    start "" /min python "%SCRIPT_DIR%gui.py"
    endlocal
    exit /b 0
)

where py >nul 2>&1
if %errorlevel% == 0 (
    start "" /min py "%SCRIPT_DIR%gui.py"
    endlocal
    exit /b 0
)

:: ─── Nothing found ────────────────────────────────────────────────
echo.
echo   F2Media: No runtime found.
echo.
echo   For end users:
echo     Double-click the F2Media.exe file instead.
echo     (Run build.bat once to create it.)
echo.
echo   For developers:
echo     Install Python 3.10+ from https://www.python.org/downloads/
echo     Then run: pip install -r requirements.txt
echo     Then run: python gui.py  (requires WSL)
echo.
pause
endlocal
