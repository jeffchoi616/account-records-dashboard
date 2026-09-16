@echo off
chcp 65001 > nul
cd /d "%~dp0"
title 한눈 장부

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PY=python"
  ) else (
    echo.
    echo   파이썬이 없습니다.
    echo   https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행해 주세요.
    echo   ^(설치할 때 "Add python.exe to PATH" 를 꼭 켜 주세요^)
    echo.
    pause
    exit /b 1
  )
)

if not exist "index.html" %PY% build.py

rem 폰에서도 보려면 아래 줄 끝에 --lan 을 붙이세요
%PY% server.py

pause
