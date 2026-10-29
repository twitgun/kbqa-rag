@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
set PYTHONPATH=%CD%
echo 启动知源后端  http://127.0.0.1:8000
echo 接口文档      http://127.0.0.1:8000/api/docs
python -m uvicorn kbqa.main:app --host 127.0.0.1 --port 8000
pause
