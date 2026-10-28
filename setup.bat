@echo off
setlocal enabledelayedexpansion

title OM Search Engine - Windows Quick Setup

echo ================================================================================
echo                     OM SEARCH ENGINE — WINDOWS SETUP WIZARD
echo ================================================================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python is not found in your PATH.
    echo     Please install Python 3.10+ from https://www.python.org/
    echo     Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

:: 2. Run the universal Python setup wizard
python setup.py

echo.
pause
