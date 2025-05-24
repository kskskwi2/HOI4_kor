@echo off
REM 게임 로컬라이제이션 번역기 종료 스크립트
REM 작성일: 2025-05-25

echo 번역기 프로세스를 종료합니다...

REM 번역기 Python 프로세스 찾기 및 종료
for /f "tokens=2" %%i in ('tasklist /fi "imagename eq python.exe" /fi "windowtitle eq *improved_translator_python*" /fo csv ^| find "python.exe"') do (
    echo 번역기 프로세스 (PID: %%i)를 종료합니다...
    taskkill /pid %%i /f
)

REM 포트 5000을 사용하는 프로세스 종료 (대안)
for /f "tokens=5" %%a in ('netstat -aon ^| find ":5000" ^| find "LISTENING"') do (
    echo 포트 5000 사용 프로세스 (PID: %%a)를 종료합니다...
    taskkill /pid %%a /f 2>nul
)

echo 번역기가 종료되었습니다.
timeout /t 2 /nobreak >nul