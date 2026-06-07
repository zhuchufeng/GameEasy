@echo off
chcp 65001 >nul
echo ============================================
echo   Roco Kingdom Helper - Setup
echo ============================================
echo.
echo Installing Python dependencies...
pip install -r requirements.txt
echo.
echo ============================================
echo   Setup complete!
echo   Run: python -m roco_auto
echo   (Admin rights needed for kernel driver)
echo ============================================
pause
