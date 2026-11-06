@echo off
setlocal
cd /d "%~dp0" || goto failed
where ollama >nul 2>&1 || goto missing
set "PROOFPAY_PROVIDER=ollama"
set "PROOFPAY_MODEL="
set /p "PROOFPAY_MODEL=Enter your installed Ollama model name (see ollama list): "
if not defined PROOFPAY_MODEL goto failed
ollama show "%PROOFPAY_MODEL%" >nul 2>&1 || goto missing
call Start-ProofPay.cmd 8770
exit /b %errorlevel%
:missing
echo Install Ollama, start it and download a model using ollama pull before launching.
:failed
pause
exit /b 1
