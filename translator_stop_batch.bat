@echo off
REM ���� ���ö������̼� ������ ���� ��ũ��Ʈ
REM �ۼ���: 2025-05-25

echo ������ ���μ����� �����մϴ�...

REM ������ Python ���μ��� ã�� �� ����
for /f "tokens=2" %%i in ('tasklist /fi "imagename eq python.exe" /fi "windowtitle eq *improved_translator_python*" /fo csv ^| find "python.exe"') do (
    echo ������ ���μ��� (PID: %%i)�� �����մϴ�...
    taskkill /pid %%i /f
)

REM ��Ʈ 5000�� ����ϴ� ���μ��� ���� (���)
for /f "tokens=5" %%a in ('netstat -aon ^| find ":5000" ^| find "LISTENING"') do (
    echo ��Ʈ 5000 ��� ���μ��� (PID: %%a)�� �����մϴ�...
    taskkill /pid %%a /f 2>nul
)

echo �����Ⱑ ����Ǿ����ϴ�.
timeout /t 2 /nobreak >nul