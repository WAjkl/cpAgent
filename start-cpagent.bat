@echo off
setlocal
cd /d "%~dp0"

echo [cpAgent] Starting backend service...
start "cpAgent-Backend" /min cmd /k "C:\Users\ASUS\miniconda3\python.exe -m backend.server"

echo [cpAgent] Waiting backend ready...
timeout /t 3 /nobreak >nul

echo [cpAgent] Starting frontend...
cd frontend
call npm run dev
