@echo off
setlocal
cd /d "%~dp0" || goto failed
if not exist ".venv\Scripts\python.exe" (
    py -3.11 -m venv .venv || goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto failed
echo Open http://127.0.0.1:8765 in your browser once the server is ready.
".venv\Scripts\python.exe" -m proofpay || goto failed
exit /b 0
:failed
echo Setup stopped. Review the error above.
pause
exit /b 1
