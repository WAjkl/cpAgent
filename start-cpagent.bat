@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

rem ============================================================
rem  关键：清掉 ELECTRON_RUN_AS_NODE
rem  这个环境变量一旦存在，electron.exe 会退化成纯 Node 运行，
rem  require('electron') 返回的是路径字符串而不是 API 对象，
rem  于是 ipcMain 是 undefined，窗口起不来，报
rem    TypeError: Cannot read properties of undefined (reading 'handle')
rem  外在表现就是「双击快捷方式什么都没发生」。
rem ============================================================
set ELECTRON_RUN_AS_NODE=

echo ============================================
echo   cpAgent 启动中
echo ============================================
echo   后端：127.0.0.1:8766
echo   前端：Electron 窗口（约 5 秒后弹出）
echo.

rem 后端已在跑就不重复启动，避免 8766 端口冲突
netstat -ano | findstr ":8766" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
  echo [1/2] 后端已在运行，跳过
) else (
  echo [1/2] 启动后端服务...
  start "cpAgent-Backend" /min cmd /k "C:\Users\ASUS\miniconda3\python.exe -m backend.server"
  echo       等待后端就绪...
  timeout /t 3 /nobreak >nul
)

rem 首次运行时依赖可能不存在
if not exist "frontend\node_modules" (
  echo       未找到 node_modules，正在 npm install（首次约 2-5 分钟）...
  pushd frontend
  call npm install
  popd
)

echo [2/2] 启动前端 Electron...
echo.
cd frontend
call npm run dev

echo.
echo 前端已退出。
pause
