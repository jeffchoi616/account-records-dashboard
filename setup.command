#!/bin/bash
# ===========================================================================
#  최초 1회 설정 / 복구용 - 더블클릭해서 실행하세요 (macOS)
#  처음 한 번은 터미널에서  chmod +x "setup.command"  가 필요합니다.
#
#  하는 일:
#   - 이 폴더가 git 저장소가 아니면 저장소로 만들고 깃허브에 연결한다.
#   - 최신 프로그램을 받는다.
#   - 장부.json(실제 기록)과 backups/ 는 git 이 추적하지 않으므로 그대로 남는다.
# ===========================================================================
cd "$(dirname "$0")" || exit 1
REPO="https://github.com/jeffchoi616/account-records-dashboard.git"

echo "폴더: $(pwd)"
echo

if ! command -v git >/dev/null 2>&1; then
  echo "git 이 없습니다. 터미널에서  xcode-select --install  로 설치하세요."
  read -r -p "닫으려면 Enter"
  exit 1
fi

if [ -f "장부.json" ]; then
  cp "장부.json" "장부.json.backup"
  echo "- 장부.json 을 장부.json.backup 으로 복사해 뒀습니다."
fi

if [ ! -d ".git" ]; then
  echo "- git 저장소가 아니라서 새로 연결합니다."
  git init -q
  git remote add origin "$REPO" 2>/dev/null || git remote set-url origin "$REPO"
fi

echo "- 최신 프로그램을 받는 중..."
if ! git fetch origin main || ! git reset --hard origin/main; then
  echo "실패 - 인터넷 연결을 확인하세요."
  read -r -p "닫으려면 Enter"
  exit 1
fi

echo "- 화면을 다시 만드는 중..."
if command -v python3 >/dev/null 2>&1; then python3 build.py; else python build.py; fi

chmod +x "장부실행.command" "setup.command" 2>/dev/null

echo
echo "- 완료. 현재 버전:"
git log -1 --format="  %h  %ad  %s" --date=short
echo
echo "이제 장부실행.command 를 눌러 실행하세요."
read -r -p "닫으려면 Enter"
