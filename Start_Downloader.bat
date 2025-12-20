@echo off
chcp 65001 >nul
title 流光下载器 - YouTube 视频下载工具

echo.
echo ========================================
echo   流光下载器 - YouTube 视频下载工具
echo ========================================
echo.
echo 正在检查配置...
echo.

REM 检查代理配置
findstr /C:"LUMINA_PROXY=http://127.0.0.1:33210" .env >nul
if %errorlevel% equ 0 (
    echo [√] 代理配置: http://127.0.0.1:33210
) else (
    echo [!] 警告: 未检测到代理配置
    echo     请确保 .env 文件中有: LUMINA_PROXY=http://127.0.0.1:33210
)

REM 检查 cookies
if exist cookies.txt (
    echo [√] Cookies 文件: cookies.txt
) else (
    echo [!] 警告: 未找到 cookies.txt
)

echo.
echo 正在启动服务器...
echo.
echo 启动后请访问: http://127.0.0.1:5001
echo 按 Ctrl+C 可停止服务器
echo.
echo ========================================
echo.

python app.py

pause
