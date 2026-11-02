@echo off
title Raudha System Launcher
cd /d %~dp0

echo ====================================================
echo   MENYALAKAN SISTEM MASJID RAUDHA
echo ====================================================
echo.

:: 1. Jalankan Bot Telegram di jendela baru
echo [1/3] Menjalankan Bot Telegram...
start "Raudha Bot" cmd /k "call venv\Scripts\activate && python bot.py"

:: 2. Jalankan Web Display (Flask) di jendela baru
echo [2/3] Menjalankan Web Display (Flask)...
start "Raudha Web" cmd /k "call venv\Scripts\activate && python app.py"

:: 3. Jalankan Ngrok di jendela baru
echo [3/3] Menjalankan Ngrok Tunnel...
start "Raudha Ngrok" cmd /k "ngrok.exe http 5000"

echo.
echo Selesai! Ketiga aplikasi sedang berjalan di jendela masing-masing.
echo Jangan tutup jendela hitam tersebut selama sistem digunakan.
timeout /t 5 >nul
exit