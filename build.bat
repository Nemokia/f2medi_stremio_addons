@echo off
setlocal
title F2Media - Build Standalone EXE

:: --- Disable proxy if set (fixes SOCKS error) ---
set "HTTPS_PROXY="
set "HTTP_PROXY="
set "https_proxy="
set "http_proxy="
set "ALL_PROXY="
set "all_proxy="

echo.
echo ============================================
echo   F2Media Addon - Build Standalone EXE
echo ============================================
echo.

:: --- Check Python ---
where py >nul 2>&1
if %errorlevel% == 0 (
    set "PY=py"
    goto :py_found
)
where python >nul 2>&1
if %errorlevel% == 0 (
    set "PY=python"
    goto :py_found
)
echo [ERROR] Python not found.
echo         Install from https://www.python.org/downloads/
pause
exit /b 1

:py_found
echo Using: %PY%
%PY% --version
echo.

:: --- Install PyInstaller ---
echo [1/3] Installing PyInstaller...
%PY% -m pip install pyinstaller --disable-pip-version-check --quiet
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install PyInstaller.
    pause
    exit /b 1
)
echo       Done.

:: --- Install project dependencies ---
echo [2/3] Installing project dependencies...
%PY% -m pip install fastapi uvicorn requests beautifulsoup4 urllib3 pysocks --disable-pip-version-check --quiet
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo       Done.

:: --- Build EXE ---
echo [3/3] Building F2Media.exe ...
echo       (this may take 1-2 minutes)
echo.

%PY% -m PyInstaller --onefile --noconsole --name F2Media --clean --hidden-import uvicorn --hidden-import uvicorn.logging --hidden-import uvicorn.loops --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols --hidden-import uvicorn.protocols.http --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan --hidden-import uvicorn.lifespan.on --hidden-import fastapi --hidden-import starlette --hidden-import starlette.routing --hidden-import starlette.responses --hidden-import starlette.middleware --hidden-import starlette.middleware.cors --hidden-import bs4 --hidden-import requests --hidden-import urllib3 --hidden-import socks --hidden-import click --hidden-import h11 --hidden-import httpcore --hidden-import anyio --hidden-import sniffio --add-data "httpclient;httpclient" --add-data "parsers;parsers" --add-data "resolvers;resolvers" --add-data "utils;utils" --add-data "main.py;." --add-data "gui.py;." --add-data "gui_backend.py;." f2media_standalone.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Build failed. See errors above.
    pause
    exit /b 1
)

:: --- Done ---
echo.
echo ============================================
echo   BUILD SUCCESSFUL
echo   Output: dist\F2Media.exe
echo ============================================
echo.
echo   Users can run dist\F2Media.exe directly.
echo   No Python, no WSL, no packages needed.
echo.
pause
