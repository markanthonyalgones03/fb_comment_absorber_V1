@echo off
title Update Comment Absorber GitHub Repository
cd /d "%~dp0"

echo =================================================================
echo    UPDATING GITHUB REPOSITORY (Comment Absorber)
echo =================================================================
echo.

where git >nul 2>nul
if %errorlevel% equ 0 (
    set "GIT_CMD=git"
) else (
    if exist "C:\Program Files\Git\cmd\git.exe" (
        set "GIT_CMD=C:\Program Files\Git\cmd\git.exe"
    ) else if exist "C:\Program Files\Git\bin\git.exe" (
        set "GIT_CMD=C:\Program Files\Git\bin\git.exe"
    ) else (
        echo [ERROR] Git is not installed or not found in Program Files.
        pause
        exit /b 1
    )
)

echo [+] Staging all modified files...
"%GIT_CMD%" add .

echo [+] Committing changes...
"%GIT_CMD%" commit -m "update: Sync latest Comment Absorber files"

echo [+] Pushing to GitHub (origin main)...
"%GIT_CMD%" push origin main

echo.
echo =================================================================
echo    DONE! Your GitHub repository is now updated.
echo =================================================================
echo.
pause
