#!/usr/bin/env python3
"""화면 하나로 두 곳을 만든다.

`src/ui.html` 이 진짜 원본이다. 여기에는 <title>·<style>·화면 본문·<script> 만 들어 있다.
  · 아티팩트  → src/ui.html 을 그대로 게시한다 (Claude 가 바깥 껍데기를 씌운다)
  · 내 PC     → 이 스크립트가 껍데기와 local-db.js 를 붙여 index.html 을 만든다

화면을 고쳤으면 src/ui.html 만 고치고 이걸 다시 돌린다.
    python build.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src" / "ui.html"
OUT = HERE / "index.html"

SHELL_HEAD = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark">
<style>
  :root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
  body{margin:0}
  img{max-width:100%}
  [hidden]{display:none!important}
</style>
<script src="local-db.js"></script>
"""

SHELL_TAIL = "\n</body>\n</html>\n"


def main() -> int:
    if not SRC.exists():
        print(f"! 원본이 없습니다: {SRC}")
        return 1
    ui = SRC.read_text(encoding="utf-8")

    # 원본 맨 앞의 <title> 과 <link rel=stylesheet> 는 <head> 안으로 옮긴다
    head_bits, body = [], ui
    for tag in ("<title>", "<link "):
        while body.lstrip().startswith(tag):
            body = body.lstrip()
            end = body.index(">", body.index(tag)) + 1
            if tag == "<title>":
                end = body.index("</title>") + len("</title>")
            head_bits.append(body[:end])
            body = body[end:]

    out = SHELL_HEAD + "\n".join(head_bits) + "\n</head>\n<body>\n" + body.lstrip() + SHELL_TAIL
    OUT.write_text(out, encoding="utf-8")
    print(f"index.html 을 새로 만들었습니다 ({len(out):,} 자)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
