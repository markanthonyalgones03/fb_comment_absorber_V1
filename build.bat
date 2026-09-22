@echo off
title Building Facebook Comment Collector Standalone Application
echo ==========================================================
echo  Building Facebook Comment Collector Standalone (.exe)
echo ==========================================================
python build_exe.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Build failed! Please check the output above.
    pause
    exit /b %ERRORLEVEL%
)
echo.
echo ==========================================================
echo  Build successful! Check the 'dist\FacebookCommentCollector' folder.
echo ==========================================================
pause
