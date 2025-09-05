@echo off
SET VENV_DIR=.venv
IF NOT EXIST "%VENV_DIR%" (
    echo 创建虚拟环境...
    python -m venv %VENV_DIR%
)

echo 激活虚拟环境...
call %VENV_DIR%\Scripts\activate.

echo 安装依赖...
pip install --upgrade pip
pip install -r requirements.txt

echo 启动 wplaceHelper.py...
python wplaceHelper.py

pause
