@echo off
chcp 65001

SET VENV_DIR=.venv
cd /d %~dp0

REM 拉取最新代码
git pull origin main

REM 创建虚拟环境（如果不存在）
IF NOT EXIST "%VENV_DIR%" (
    python -m venv %VENV_DIR%
)

REM 安装/更新依赖，使用虚拟环境的 pip
%VENV_DIR%\Scripts\pip.exe install --upgrade pip
%VENV_DIR%\Scripts\pip.exe install -r requirements.txt

REM 启动程序，使用虚拟环境的 python
%VENV_DIR%\Scripts\python.exe wplaceHelper.py

exit
