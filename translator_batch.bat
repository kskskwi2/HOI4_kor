@echo off

echo �����⸦ ��׶��忡�� �����մϴ�...

cd /d "%~dp0"


start /b python improved_translator_python.py
timeout /t 3 /nobreak >nul
start http://localhost:5000
echo �����Ⱑ ��׶��忡�� ���� ���Դϴ�.
echo ���������� http://localhost:5000 �� �����ϼ���.
echo.
echo �����Ϸ��� �۾� �����ڿ��� python.exe ���μ����� �����ϼ���.
echo �Ǵ� stop_translator.bat �� �����ϼ���.

pause