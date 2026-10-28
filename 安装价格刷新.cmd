@echo off
chcp 65001 >nul
cd /d "%~dp0"
title cpAgent 价格刷新 - 安装/管理

set PY=C:\Users\ASUS\miniconda3\python.exe
set TASK=cpAgent-PriceRefresh
set SCRIPT=%~dp0hz_price_refresh.py

echo ============================================
echo   cpAgent 国内价格刷新 - 安装器
echo ============================================
echo.
echo   数据源：中关村在线参考价（不需要任何 API key）
echo   频率  ：每小时自动跑一次
echo   输出  ：更新 data\hardware_db.json 里的价格
echo.
echo   为什么不用项目自带的 refresh_live.py：
echo   它的价源是海外价（美元街价 / Amazon UK 含税价），
echo   比国内实际售价高 1.5-3 倍，会把 RTX 4080 Super 算成 25681。
echo.
echo --------------------------------------------
echo   [1] 安装（注册每小时计划任务，开机自启）
echo   [2] 立即跑一次（看效果）
echo   [3] 查看日志
echo   [4] 卸载
echo   [5] 常驻窗口模式（不用计划任务时）
echo --------------------------------------------
set /p CH=请输入 1-5 然后回车：

if "%CH%"=="1" goto install
if "%CH%"=="2" goto runonce
if "%CH%"=="3" goto showlog
if "%CH%"=="4" goto uninstall
if "%CH%"=="5" goto loopmode
goto end

:install
echo.
echo 正在注册计划任务（每小时）...
schtasks /Create /TN "%TASK%" /TR "\"%PY%\" \"%SCRIPT%\" --once" /SC HOURLY /MO 1 /F
if errorlevel 1 (
  echo [失败] 注册失败。可以右键本文件「以管理员身份运行」再试。
) else (
  echo [成功] 已注册：%TASK%
  echo        每小时自动跑，电脑开机后即生效，无需再配置。
  echo.
  echo 现在先手动跑一次，确认能连通：
  "%PY%" "%SCRIPT%" --once
)
goto end

:runonce
echo.
"%PY%" "%SCRIPT%" --once
goto end

:showlog
echo.
if exist "%~dp0data\price_refresh.log" (
  powershell -NoProfile -Command "Get-Content '%~dp0data\price_refresh.log' -Tail 40"
) else (
  echo 还没有日志，先跑一次 [2] 吧。
)
goto end

:uninstall
echo.
schtasks /Delete /TN "%TASK%" /F
echo 已删除计划任务。
goto end

:loopmode
echo.
echo 常驻模式：这个窗口不能关，关了就不再刷新。
echo 每 60 分钟刷一次。Ctrl+C 停止。
echo.
"%PY%" "%SCRIPT%" --loop --interval 60
goto end

:end
echo.
pause
