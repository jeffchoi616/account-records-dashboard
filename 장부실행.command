#!/bin/bash
# 맥에서 두 번 눌러 실행합니다.
# 처음 한 번은 터미널에서  chmod +x "장부실행.command"  를 해 주세요.
cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo
  echo "  파이썬이 없습니다."
  echo "  터미널에서  xcode-select --install  또는 https://www.python.org/downloads/ 로 설치해 주세요."
  echo
  read -r -p "닫으려면 Enter"
  exit 1
fi

[ -f index.html ] || "$PY" build.py

# 폰에서도 보려면 아래 줄 끝에 --lan 을 붙이세요
"$PY" server.py

read -r -p "닫으려면 Enter"
