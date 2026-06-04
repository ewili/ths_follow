@echo off
title Signal Server - 股票同花顺跟单系统

cd /d "%~dp0"

echo ========================================
echo   Signal Server 启动
echo ========================================
echo.

REM 1. Check portable Python
if not exist "python311\python.exe" (
    echo 错误: 未找到便携 Python
    echo 请先运行 setup.bat 搭建环境
    echo.
    pause
    exit /b 1
)

REM 2. Check / Install VC++ Redistributable
reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\X64" /v Version >nul 2>&1
if errorlevel 1 (
    if exist "vc_redist.x64.exe" (
        echo 正在安装 VC++ 运行时...
        vc_redist.x64.exe /install /quiet /norestart
    ) else (
        echo 警告: 未检测到 VC++ 运行时，验证码识别可能无法工作
        echo 如遇问题请安装 vc_redist.x64.exe
    )
)

REM 3. Clear logs
echo 清理日志文件...
if exist "logs" del /q "logs\*.log" 2>nul
echo 日志已清空
echo.

REM 4. Start service
echo 启动 Signal Server...
echo 服务地址: http://localhost:8000
echo 按 Ctrl+C 停止服务
echo.

set "PYTHONPATH=%~dp0"
python311\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

pause
