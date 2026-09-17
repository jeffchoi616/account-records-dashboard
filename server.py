#!/usr/bin/env python3
"""한눈 장부 — 내 PC에서 도는 작은 서버.

장부는 이 폴더의 `장부.json` 파일 하나에 들어간다. 이 폴더가 구글 드라이브 안에
있으므로 저장하는 순간 드라이브가 알아서 백업·동기화한다.

  python server.py            내 PC 에서만 열기
  python server.py --lan      같은 와이파이의 폰에서도 보기 (열쇠말 필요)
  python server.py --port 9000
"""
from __future__ import annotations

import argparse
import http.server
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import socketserver
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
DATA = HERE / "장부.json"
BACKUPS = HERE / "backups"
KEY_FILE = HERE / "claude_key.txt"          # 명세서 읽기에 쓰는 API 열쇠 (git 에 안 올라간다)
KEEP_BACKUPS = 30
MAX_BODY = 32 * 1024 * 1024  # 32MB — 장부 하나가 이보다 커질 일은 없다

# 명세서 읽기 — 브라우저에는 AI 가 없으므로 서버가 대신 Anthropic API 를 부른다.
CLAUDE_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-5"
CLAUDE_MAX_TOKENS = 8000

EMPTY = {"version": 0, "groups": {}, "cards": {}, "cats": {}, "meta": {}, "entries": {}}
COLLECTIONS = ("groups", "cards", "cats", "meta", "entries")

_lock = threading.Lock()
TOKEN: str | None = None


# ---------------------------------------------------------------- 파일 읽기/쓰기
def load() -> dict:
    if not DATA.exists():
        return dict(EMPTY, version=0)
    try:
        raw = json.loads(DATA.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as err:
        # 파일이 깨졌으면 가장 최근 백업으로 되살린다
        good = sorted(BACKUPS.glob("장부_*.json")) if BACKUPS.exists() else []
        if good:
            print(f"! 장부.json 을 읽지 못했습니다 ({err}). 백업 {good[-1].name} 으로 엽니다.")
            raw = json.loads(good[-1].read_text(encoding="utf-8"))
        else:
            print(f"! 장부.json 을 읽지 못했습니다 ({err}). 빈 장부로 시작합니다.")
            return dict(EMPTY, version=0)
    out = dict(EMPTY, version=int(raw.get("version") or 0))
    for c in COLLECTIONS:
        v = raw.get(c)
        out[c] = v if isinstance(v, dict) else {}
    return out


def save(doc: dict) -> dict:
    BACKUPS.mkdir(exist_ok=True)
    doc = dict(doc)
    doc["version"] = int(doc.get("version") or 0) + 1
    doc["savedAt"] = datetime.now().isoformat(timespec="seconds")

    tmp = DATA.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    # 드라이브 동기화가 파일을 잡고 있을 수 있어 몇 번 다시 시도한다
    for attempt in range(6):
        try:
            os.replace(tmp, DATA)
            break
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.25)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        shutil.copy2(DATA, BACKUPS / f"장부_{stamp}.json")
        old = sorted(BACKUPS.glob("장부_*.json"))[:-KEEP_BACKUPS]
        for f in old:
            f.unlink(missing_ok=True)
    except OSError as err:
        print(f"! 백업을 만들지 못했습니다: {err}")
    return doc


# ---------------------------------------------------------------- 명세서 읽기
def api_key() -> str:
    """열쇠는 파일이나 환경변수에서 읽는다. 브라우저로는 절대 내려보내지 않는다."""
    k = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not k and KEY_FILE.exists():
        k = KEY_FILE.read_text(encoding="utf-8").strip()
    return k


def ask_claude(prompt: str, images: list[dict]) -> dict:
    """그림과 지시문을 Anthropic API 로 보내고 JSON 을 받아 온다."""
    import urllib.request
    import urllib.error

    key = api_key()
    if not key:
        return {"error": "no_key", "message": "API 열쇠가 없습니다."}

    content: list[dict] = []
    for im in images[:8]:
        content.append({
            "type": "image",
            "source": {"type": "base64",
                       "media_type": im.get("type") or "image/jpeg",
                       "data": im["data"]},
        })
    content.append({"type": "text", "text": prompt})

    body = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": CLAUDE_MAX_TOKENS,
        "messages": [{"role": "user", "content": content}],
    }).encode("utf-8")

    req = urllib.request.Request(CLAUDE_URL, data=body, method="POST", headers={
        "content-type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    })
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            out = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:400]
        if err.code in (401, 403):
            return {"error": "bad_key", "message": "API 열쇠가 거부됐습니다. 다시 넣어 주세요."}
        if err.code == 429:
            return {"error": "rate", "message": "요청이 몰렸어요. 잠시 뒤 다시 시도해 주세요."}
        return {"error": "http_%d" % err.code, "message": detail}
    except Exception as err:                                  # 네트워크 끊김 등
        return {"error": "net", "message": str(err)[:300]}

    text = "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")
    return {"text": text}


# ---------------------------------------------------------------- 서버
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\-]+$")
SERVE = {"index.html": "text/html; charset=utf-8", "local-db.js": "text/javascript; charset=utf-8"}


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "HannunJangbu"
    protocol_version = "HTTP/1.1"

    # ---- 공통
    def log_message(self, fmt, *args):  # 조용히
        pass

    def _authorised(self) -> bool:
        if TOKEN is None:
            return True
        key = parse_qs(urlparse(self.path).query).get("k", [None])[0]
        if key and secrets.compare_digest(key, TOKEN):
            self._set_cookie = True
            return True
        cookie = self.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            name, _, val = part.strip().partition("=")
            if name == "jangbu_key" and secrets.compare_digest(val, TOKEN):
                return True
        return False

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if getattr(self, "_set_cookie", False):
            self.send_header("Set-Cookie", f"jangbu_key={TOKEN}; Path=/; SameSite=Lax; Max-Age=2592000")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    # ---- GET
    def do_GET(self):
        if not self._authorised():
            return self._send(403, "열쇠말이 필요합니다.".encode("utf-8"), "text/plain; charset=utf-8")
        path = urlparse(self.path).path
        if path == "/api/data":
            with _lock:
                return self._json(200, load())
        if path == "/api/read":
            # 열쇠가 있는지만 알려 준다 — 열쇠 자체는 절대 내려보내지 않는다
            return self._json(200, {"ready": bool(api_key()), "model": CLAUDE_MODEL})
        name = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
        if name not in SERVE or not SAFE_NAME.match(name):
            return self._send(404, b"not found", "text/plain")
        f = HERE / name
        if not f.exists():
            return self._send(404, b"not found", "text/plain")
        self._send(200, f.read_bytes(), SERVE[name])

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY:
            return None
        try:
            obj = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return obj if isinstance(obj, dict) else None

    # ---- PUT  (장부 저장 / 명세서 읽기 / 열쇠 저장)
    def do_PUT(self):
        if not self._authorised():
            return self._json(403, {"error": "forbidden"})
        path = urlparse(self.path).path

        if path == "/api/read":
            body = self._body()
            if body is None:
                return self._json(400, {"error": "bad json"})
            imgs = body.get("images") or []
            if not isinstance(imgs, list) or not imgs:
                return self._json(400, {"error": "no_images", "message": "읽을 그림이 없어요."})
            out = ask_claude(str(body.get("prompt") or ""), imgs)
            return self._json(200, out)

        if path == "/api/key":
            body = self._body()
            if body is None:
                return self._json(400, {"error": "bad json"})
            key = str(body.get("key") or "").strip()
            try:
                if key:
                    KEY_FILE.write_text(key, encoding="utf-8")
                    try:
                        os.chmod(KEY_FILE, 0o600)
                    except OSError:
                        pass
                elif KEY_FILE.exists():
                    KEY_FILE.unlink()
            except OSError as err:
                return self._json(500, {"error": "save", "message": str(err)[:200]})
            return self._json(200, {"ready": bool(api_key())})

        if path != "/api/data":
            return self._json(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._json(400, {"error": "bad length"})
        if length <= 0 or length > MAX_BODY:
            return self._json(400, {"error": "bad length"})
        try:
            incoming = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._json(400, {"error": "bad json"})
        if not isinstance(incoming, dict):
            return self._json(400, {"error": "bad json"})

        with _lock:
            current = load()
            base = incoming.get("baseVersion")
            # 다른 기기가 먼저 저장했으면 덮어쓰지 않고 현재 내용을 돌려준다
            if base is not None and int(base) != current["version"]:
                return self._json(409, {"error": "conflict", "current": current})
            doc = {"version": current["version"]}
            for c in COLLECTIONS:
                v = incoming.get(c)
                doc[c] = v if isinstance(v, dict) else current[c]
            try:
                saved = save(doc)
            except OSError as err:
                return self._json(500, {"error": f"저장 실패: {err}"})
        return self._json(200, {"ok": True, "version": saved["version"], "savedAt": saved["savedAt"]})

    # 창을 닫을 때 브라우저가 보내는 마지막 저장은 POST 로 온다
    do_POST = do_PUT


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main() -> int:
    global TOKEN
    ap = argparse.ArgumentParser(description="한눈 장부 서버")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--lan", action="store_true", help="같은 와이파이의 다른 기기에서도 보기")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if not (HERE / "index.html").exists():
        print("! index.html 이 없습니다.  python build.py  를 먼저 돌려 주세요.")
        return 1

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    if args.lan:
        TOKEN = secrets.token_urlsafe(9)

    port = args.port
    for _ in range(20):
        try:
            httpd = Server((host, port), Handler)
            break
        except OSError:
            port += 1
    else:
        print("! 쓸 수 있는 포트를 찾지 못했습니다.")
        return 1

    mine = f"http://127.0.0.1:{port}/" + (f"?k={TOKEN}" if TOKEN else "")
    print("─" * 56)
    print("  한눈 장부")
    print(f"  장부 파일 : {DATA}")
    print(f"  내 PC     : {mine}")
    if args.lan:
        print(f"  폰·태블릿 : http://{lan_ip()}:{port}/?k={TOKEN}")
        print("             (같은 와이파이에서만. 폰에서는 보기 전용입니다)")
    print("  끄려면 이 창에서 Ctrl+C")
    print("─" * 56)

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(mine)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n닫았습니다.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
