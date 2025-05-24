@echo off

echo 번역기를 백그라운드에서 시작합니다...

cd /d "%~dp0"


start /b python improved_translator_python.py
timeout /t 3 /nobreak >nul
start http://localhost:5000
echo 번역기가 백그라운드에서 실행 중입니다.
echo 브라우저에서 http://localhost:5000 에 접속하세요.
echo.
echo 종료하려면 작업 관리자에서 python.exe 프로세스를 종료하세요.
echo 또는 stop_translator.bat 을 실행하세요.

pause