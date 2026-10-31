@echo off
chcp 65001 >nul
setlocal
pushd "%~dp0"
set "UV_CMD=uv.exe"
where uv.exe >nul 2>nul
if errorlevel 1 (
  set "UV_CMD=%USERPROFILE%\.local\bin\uv.exe"
  if not exist "%USERPROFILE%\.local\bin\uv.exe" (
    echo 请先按 README.md 安装 uv，然后重新打开此脚本。
    pause
    popd
    exit /b 1
  )
)
echo 正在准备项目环境，首次运行需要联网下载，请稍候……
"%UV_CMD%" sync --locked --managed-python --inexact --no-dev
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m app.browser
rem 浏览器未就绪时仍打开看板，允许在设置中选择已有浏览器。
start "" ".venv\Scripts\pythonw.exe" "%~dp0launcher.py"
popd
exit /b 0
:failed
echo 环境准备失败，请检查上方错误与网络连接后重试。
pause
popd
exit /b 1
