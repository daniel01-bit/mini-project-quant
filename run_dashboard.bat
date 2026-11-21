@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   AI Quant Workbench v7.0 — Dashboard
echo ========================================
python quant_gui.py
pause
