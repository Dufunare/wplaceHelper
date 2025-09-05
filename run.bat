chcp 65001

@echo off
SET VENV_DIR=.venv

REM 进入批处理文件所在目录
cd /d %~dp0


echo 拉取最新代码...
git pull origin main

REM 创建虚拟环境（如果不存在）
IF NOT EXIST "%VENV_DIR%" (
    echo 创建虚拟环境...
    python -m venv %VENV_DIR%
)

REM 激活虚拟环境
echo 激活虚拟环境...
call %VENV_DIR%\Scripts\activate.bat

REM 安装依赖
echo 安装依赖...
pip install --upgrade pip
pip install -r requirements.txt

REM 启动程序
echo 启动 wplaceHelper.py...
python wplaceHelper.py

REM 保持终端窗口打开
exit
