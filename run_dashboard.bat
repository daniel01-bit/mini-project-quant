@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   AI Quant Terminal v4.0 — Dashboard
echo ========================================
python quant_gui.py
pause
