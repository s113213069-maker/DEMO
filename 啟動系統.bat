@echo off
cd /d "%~dp0"
if not exist .venv (
  py -m venv .venv
)
call .venv\Scripts\activate
py -m pip install -r requirements.txt
py -m uvicorn app:app --host 0.0.0.0 --port 8000
pause
