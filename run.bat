@echo off
cd /d "%~dp0"
title Pic to PDF by Chang

echo ========================================================
echo               Pic to PDF by Chang
echo ========================================================
echo Starting server and opening browser...
echo.

if exist "%~dp0.venv\Scripts\python.exe" (
    echo [OK] Using virtual environment Python...
    "%~dp0.venv\Scripts\python.exe" app.py
    goto :done
)

if exist "%USERPROFILE%\.local\bin\uv.exe" (
    echo [OK] Using uv from user profile...
    "%USERPROFILE%\.local\bin\uv.exe" run python app.py
    goto :done
)

where uv >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Using uv from PATH...
    uv run python app.py
    goto :done
)

where python >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Using system python...
    python app.py
    goto :done
)

echo [ERROR] Python or uv was not found on your system.
pause

:done
