@echo off
chcp 65001 >nul
REM ===========================================================================
REM  최초 1회 설정 / 복구용 - 더블클릭해서 실행하세요 (Windows)
REM
REM  하는 일:
REM   - 이 폴더가 git 저장소가 아니면 저장소로 만들고 깃허브에 연결한다.
REM   - 최신 프로그램을 받는다.
REM   - 장부.json(실제 기록)과 backups/ 는 git 이 추적하지 않으므로 그대로 남는다.
REM ===========================================================================
cd /d "%~dp0"
set REPO=https://github.com/jeffchoi616/account-records-dashboard.git

echo 폴더: %cd%
echo.

if exist "장부.json" (
  copy /y "장부.json" "장부.json.backup" >nul
  echo - 장부.json 을 장부.json.backup 으로 복사해 뒀습니다.
)

if not exist ".git" (
  echo - git 저장소가 아니라서 새로 연결합니다.
  git init -q
  if errorlevel 1 goto nogit
  git remote add origin %REPO% 2>nul
  if errorlevel 1 git remote set-url origin %REPO%
)

echo - 최신 프로그램을 받는 중...
git fetch origin main
if errorlevel 1 goto fail
git reset --hard origin/main
if errorlevel 1 goto fail

echo - 화면을 다시 만드는 중...
where py >nul 2>nul && (py build.py) || (python build.py)

echo.
echo - 완료. 현재 버전:
git log -1 --format="  %%h  %%ad  %%s" --date=short
echo.
echo 이제 장부실행.bat 을 눌러 실행하세요.
pause
exit /b 0

:nogit
echo git 이 설치돼 있지 않습니다. https://git-scm.com 에서 설치하세요.
pause
exit /b 1

:fail
echo 실패 - 인터넷 연결을 확인하세요.
pause
exit /b 1
