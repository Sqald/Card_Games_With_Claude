#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ヘッドレス・統合ゲームサーバ (HTTP / 標準ライブラリのみ)

GUIなしで全ゲームのホストを一括で請け負う。1つのポートで複数ルームを
同時にホストする。PySide6 に依存しないため Docker 等の軽量環境で動く。

通信は HTTP/1.1 + JSON。クライアント (client/) と同じプロトコル:
  POST /api/join           hello メッセージで参加 → {"sid": セッションID}
  POST /api/send?sid=SID   ゲームメッセージ (action / start) の送信
  GET  /api/poll?sid=SID   受信キューの取得 (ロングポーリング; 最長20秒保持)
  POST /api/leave?sid=SID  明示的な退出
  GET  /api/ping           死活確認

設定は以下の優先度で解決する (sample.env を .env にコピーして編集):
  コマンドライン引数 > 環境変数 > .env ファイル > 既定値

  SERVER_NAME  サーバ名 (クライアントの接続設定で一致が必要)
  SERVER_BIND  待受アドレス (既定 0.0.0.0)
  SERVER_PORT  待受ポート (既定 80 = HTTP標準)

使い方:
    python3 server/server.py [--port 80] [--name GameServer] [--bind 0.0.0.0]
    docker compose up -d --build   (リポジトリルートで)

    ※ 80番など1024未満のポートで直接待ち受けるには、Linuxでは root 権限
      (または CAP_NET_BIND_SERVICE) が必要。macOS・Dockerはそのまま可。
"""

import argparse
import json
import secrets
import signal
import socket as pysocket
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.envfile import env_int, env_str, load_env          # noqa: E402
from shared.engines import (                                   # noqa: E402
    baccarat, blackjack, color_numbers, craps, holdem, money_wheel,
    roulette, sicbo, slots,
)

DEFAULT_PORT = 80
DEFAULT_NAME = "GameServer"
DEFAULT_BIND = "0.0.0.0"

POLL_HOLD_SEC = 20        # ロングポーリングの最大保持時間
SESSION_TIMEOUT_SEC = 45  # pollが途絶えたら退出とみなす時間
MAX_REQUEST_BYTES = 64 * 1024

# ゲーム状態・セッション・ルームを守る単一ロック。
# ロングポーリングは Condition.wait() でこのロックを解放しながら待つ。
LOCK = threading.RLock()


def log(text):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}", flush=True)


def resolve_bind_address(bind):
    """bind の値 (IP / ドメイン名 / 空) を待受アドレスに解決する。"""
    if not bind or bind in ("0.0.0.0", "any", "*"):
        return "0.0.0.0", "0.0.0.0 (全インターフェース)"
    try:
        ip = pysocket.getaddrinfo(bind, None)[0][4][0]
    except OSError as e:
        raise RuntimeError(f"バインド先「{bind}」を解決できません: {e}")
    disp = ip if ip == bind else f"{bind} → {ip}"
    return ip, disp


# ---------------------------------------------------------------- ゲーム定義

def _act_blackjack(engine, pid, msg):
    return engine.act(pid, msg.get("action", ""))


def _start_blackjack(engine):
    if engine.phase == "playing" or not engine.players:
        return False
    engine.start_round()
    return True


def _act_holdem(engine, pid, msg):
    return engine.act(pid, msg.get("action", ""), msg.get("amount", 0))


def _act_betting(engine, pid, msg):
    """時限ベット型ゲーム共通 (ルーレット / バカラ / クラップス 等)。"""
    a = msg.get("action")
    if a == "bet":
        return engine.place_bet(pid, msg.get("bet_type"),
                                msg.get("number", 0), msg.get("amount", 0))
    if a == "clear":
        return engine.clear_bets(pid)
    if a == "done":
        return engine.set_done(pid)
    return False


def _act_slots(engine, pid, msg):
    return engine.act(pid, msg.get("action", ""))


def _act_colornum(engine, pid, msg):
    return engine.act(pid, msg.get("action", ""),
                      msg.get("index"), msg.get("color"))


GAMES = {
    "blackjack": {
        "label": "ブラックジャック",
        "engine": blackjack.GameEngine,
        "start": _start_blackjack,
        "act": _act_blackjack,
    },
    "holdem": {
        "label": "テキサスホールデム",
        "engine": holdem.HoldemEngine,
        "start": lambda e: e.start_hand(),
        "act": _act_holdem,
    },
    "roulette": {
        "label": "ルーレット",
        "engine": roulette.RouletteEngine,
        "start": lambda e: e.start_round(),
        "act": _act_betting,
    },
    "colornum": {
        "label": "Color & Numbers",
        "engine": color_numbers.ColorNumbersEngine,
        "start": lambda e: e.start_game(),
        "act": _act_colornum,
    },
    "baccarat": {
        "label": "バカラ",
        "engine": baccarat.BaccaratEngine,
        "start": lambda e: e.start_round(),
        "act": _act_betting,
    },
    "craps": {
        "label": "クラップス",
        "engine": craps.CrapsEngine,
        "start": lambda e: e.start_round(),
        "act": _act_betting,
    },
    "sicbo": {
        "label": "シックボー",
        "engine": sicbo.SicBoEngine,
        "start": lambda e: e.start_round(),
        "act": _act_betting,
    },
    "wheel": {
        "label": "マネーホイール",
        "engine": money_wheel.MoneyWheelEngine,
        "start": lambda e: e.start_round(),
        "act": _act_betting,
    },
    "slots": {
        "label": "スロット",
        "engine": slots.SlotsEngine,
        "start": lambda e: True,   # スロットは開始操作不要
        "act": _act_slots,
    },
}


# ---------------------------------------------------------------- セッション / ルーム

class Session:
    """接続クライアント1人分のセッション (要LOCKで操作)。"""

    def __init__(self, sid):
        self.sid = sid
        self.queue = []        # クライアントへ送る未配信メッセージ
        self.cond = threading.Condition(LOCK)
        self.last_seen = time.time()
        self.closing = False
        self.room = None       # 参加先 Room
        self.pid = None

    def send(self, obj):
        if not self.closing:
            self.queue.append(obj)
            self.cond.notify_all()


class Room:
    def __init__(self, room_id, game_key):
        self.id = room_id
        self.game = game_key
        self.spec = GAMES[game_key]
        self.engine = self.spec["engine"]()
        self.clients = {}    # pid -> Session
        self.master = None   # ゲーム開始権限を持つ pid
        self.next_pid = 1

    def label(self):
        return f"ルーム[{self.id}]({self.spec['label']})"

    def broadcast_state(self):
        for pid, sess in self.clients.items():
            state = self.engine.public_state(pid)
            state["master"] = self.master
            state["room"] = self.id
            sess.send({"type": "state", "state": state})

    def broadcast_info(self, text):
        for sess in self.clients.values():
            sess.send({"type": "info", "msg": text})


# ---------------------------------------------------------------- サーバ本体

class GameHub:
    """ルームとセッションの管理。全メソッドは内部でLOCKを取る。"""

    def __init__(self, name):
        self.name = name
        self.rooms = {}      # room_id -> Room
        self.sessions = {}   # sid -> Session
        self._stop = threading.Event()
        self._ticker = threading.Thread(target=self._tick_loop, daemon=True)
        self._ticker.start()

    # ---- 参加

    def join(self, hello):
        """hello を検証して参加させる。常に sid を返す
        (拒否時はエラーメッセージ+切断予約を積んだセッションを返す)。"""
        with LOCK:
            sess = Session(secrets.token_urlsafe(16))
            self.sessions[sess.sid] = sess
            self._join_locked(sess, hello)
            return sess.sid

    def _reject(self, sess, text):
        log(f"拒否: {text}")
        sess.send({"type": "error", "msg": text})
        sess.closing = True   # メッセージを届けた後にpollで切断される
        sess.cond.notify_all()

    def _join_locked(self, sess, msg):
        if "server" not in msg:
            self._reject(
                sess, "このポートは専用サーバです。接続設定で"
                      "「サーバー接続モード」を選び、サーバ名とルームIDを指定してください")
            return
        if str(msg.get("server", "")) != self.name:
            self._reject(sess, f"サーバ名が違います (このサーバ: {self.name})")
            return
        game = msg.get("game")
        if game not in GAMES:
            self._reject(sess, f"未対応のゲームです: {game}")
            return
        room_id = str(msg.get("room", "")).strip()
        if not room_id:
            self._reject(sess, "ルームIDを指定してください")
            return
        name = str(msg.get("name", "")).strip() or "Player"

        room = self.rooms.get(room_id)
        if room is None:
            room = Room(room_id, game)
            self.rooms[room_id] = room
            log(f"{room.label()} を作成しました")
        elif room.game != game:
            self._reject(
                sess, f"ルーム {room_id} は {room.spec['label']} の"
                      f"ルームです (現在 {len(room.clients)} 人)")
            return

        pid = room.next_pid
        room.next_pid += 1
        sess.room = room
        sess.pid = pid
        room.clients[pid] = sess
        room.engine.add_player(pid, name)
        if room.master is None:
            room.master = pid
        sess.send({"type": "welcome", "id": pid})
        suffix = " (ルームマスター)" if room.master == pid else ""
        room.broadcast_info(f"◆ {name} が参加しました{suffix}")
        room.broadcast_state()
        log(f"{room.label()} に {name} (pid={pid}) が参加{suffix} "
            f"/ {len(room.clients)} 人")

    # ---- メッセージ処理

    def handle(self, sid, msg):
        """/api/send の処理。セッションが無ければ False。"""
        with LOCK:
            sess = self.sessions.get(sid)
            if sess is None:
                return False
            sess.last_seen = time.time()
            room = sess.room
            if room is None or sess.closing:
                return True   # 未参加/切断予約中のメッセージは無視
            t = msg.get("type")
            if t == "action":
                if room.spec["act"](room.engine, sess.pid, msg):
                    room.broadcast_state()
            elif t == "start":
                self._start_game(sess, room)
            return True

    def _start_game(self, sess, room):
        if sess.pid != room.master:
            sess.send({"type": "info",
                       "msg": "◆ ゲームを開始できるのはルームマスターだけです"})
            return
        if room.spec["start"](room.engine):
            room.broadcast_info("◆ ゲームを開始しました")
            room.broadcast_state()
            log(f"{room.label()} ゲーム開始")
        else:
            sess.send({"type": "info",
                       "msg": "◆ 開始できません (参加人数などを確認してください)"})

    # ---- ロングポーリング

    def poll(self, sid):
        """メッセージが来るか最長 POLL_HOLD_SEC 秒待って返す。
        戻り値: (msgs, closed) / セッション不明なら None。"""
        with LOCK:
            sess = self.sessions.get(sid)
            if sess is None:
                return None
            sess.last_seen = time.time()
            deadline = time.time() + POLL_HOLD_SEC
            while (not sess.queue and not sess.closing
                   and time.time() < deadline):
                sess.cond.wait(deadline - time.time())
            msgs, sess.queue = sess.queue, []
            closed = sess.closing
            if closed:
                self._drop(sess)   # 残メッセージを渡し終えたので終了
            else:
                sess.last_seen = time.time()
            return msgs, closed

    # ---- 退出

    def leave(self, sid):
        with LOCK:
            sess = self.sessions.get(sid)
            if sess is None:
                return False
            self._drop(sess)
            return True

    def _drop(self, sess):
        """セッションを終了し、ルームから退出させる。(要LOCK / 冪等)"""
        if self.sessions.pop(sess.sid, None) is None:
            return
        sess.closing = True
        sess.cond.notify_all()   # 保留中のpollを解放する
        room = sess.room
        sess.room = None
        if room is None:
            return
        pid = sess.pid
        room.clients.pop(pid, None)
        name = None
        if pid in room.engine.players:
            name = room.engine.players[pid]["name"]
            room.engine.remove_player(pid)
        if not room.clients:
            del self.rooms[room.id]
            log(f"{room.label()} が空になったため削除しました")
        else:
            if name:
                room.broadcast_info(f"◆ {name} が退出しました")
            if room.master == pid:
                room.master = min(room.clients)
                new_name = room.engine.players.get(
                    room.master, {}).get("name", f"pid={room.master}")
                room.broadcast_info(
                    f"◆ {new_name} が新しいルームマスターになりました")
                log(f"{room.label()} マスター引き継ぎ → {new_name}")
            room.broadcast_state()
        if name:
            log(f"{room.label()} から {name} が退出 / {len(room.clients)} 人")

    # ---- 1秒ティック (ベット締切・セッションタイムアウト)

    def _tick_loop(self):
        while not self._stop.wait(1.0):
            with LOCK:
                for room in list(self.rooms.values()):
                    e = room.engine
                    if hasattr(e, "expired") and e.phase == "betting":
                        if e.expired():
                            e.close_betting()
                            room.broadcast_info(f"◆ 時間切れ! {e.message}")
                            log(f"{room.label()} 時間切れ → {e.message}")
                        room.broadcast_state()   # 残り時間の同期
                now = time.time()
                for sess in list(self.sessions.values()):
                    if now - sess.last_seen > SESSION_TIMEOUT_SEC:
                        log("セッションタイムアウト (poll途絶)")
                        self._drop(sess)

    def stop(self):
        self._stop.set()


# ---------------------------------------------------------------- HTTPハンドラ

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    hub = None   # 起動時に設定する

    def log_message(self, *args):
        pass   # アクセスログは抑制 (ゲームログのみ出す)

    def _json(self, code, obj):
        try:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type",
                             "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass   # クライアントが待たずに切断した

    def _body_json(self):
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            return None
        if not 0 <= n <= MAX_REQUEST_BYTES:
            return None
        try:
            data = self.rfile.read(n) if n else b"{}"
            obj = json.loads(data.decode("utf-8") or "{}")
            return obj if isinstance(obj, dict) else None
        except (ValueError, UnicodeDecodeError, OSError):
            return None

    def _query(self):
        parts = urlsplit(self.path)
        return parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()}

    def do_GET(self):
        path, query = self._query()
        if path == "/api/ping":
            self._json(200, {"ok": True, "app": "casino-games"})
        elif path == "/api/poll":
            result = self.hub.poll(query.get("sid", ""))
            if result is None:
                self._json(410, {"error": "unknown session"})
            else:
                msgs, closed = result
                self._json(200, {"msgs": msgs, "closed": closed})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path, query = self._query()
        if path == "/api/join":
            msg = self._body_json()
            if msg is None:
                self._json(400, {"error": "bad json"})
                return
            self._json(200, {"sid": self.hub.join(msg)})
        elif path == "/api/send":
            msg = self._body_json()
            if msg is None:
                self._json(400, {"error": "bad json"})
                return
            if self.hub.handle(query.get("sid", ""), msg):
                self._json(200, {"ok": True})
            else:
                self._json(410, {"error": "unknown session"})
        elif path == "/api/leave":
            if self.hub.leave(query.get("sid", "")):
                self._json(200, {"ok": True})
            else:
                self._json(410, {"error": "unknown session"})
        else:
            self._json(404, {"error": "not found"})


class QuietHTTPServer(ThreadingHTTPServer):
    """クライアントの切断 (poll中断など) を正常系としてログに出さない。"""

    daemon_threads = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError,
                            TimeoutError)):
            return
        super().handle_error(request, client_address)


# ---------------------------------------------------------------- 起動

def main():
    load_env()   # <ルート>/.env があれば環境変数として取り込む

    parser = argparse.ArgumentParser(
        description="統合ゲームサーバ (GUIなし / HTTP / 標準ライブラリのみ)")
    parser.add_argument("--port", type=int, default=None,
                        help=f"待受ポート (既定: 環境変数 SERVER_PORT または "
                             f"{DEFAULT_PORT})")
    parser.add_argument("--name", default=None,
                        help=f"サーバ名 (既定: 環境変数 SERVER_NAME または "
                             f"{DEFAULT_NAME})")
    parser.add_argument("--bind", default=None,
                        help="待受アドレス。IPまたはドメイン名 "
                             f"(既定: 環境変数 SERVER_BIND または {DEFAULT_BIND})")
    args = parser.parse_args()

    name = args.name or env_str("SERVER_NAME", DEFAULT_NAME)
    port = args.port or env_int("SERVER_PORT", DEFAULT_PORT)
    bind = args.bind or env_str("SERVER_BIND", DEFAULT_BIND)

    try:
        address, disp = resolve_bind_address(bind)
        hub = GameHub(name)
        Handler.hub = hub
        httpd = QuietHTTPServer((address, port), Handler)
    except (RuntimeError, OSError) as e:
        log(f"起動失敗: {e}")
        if port < 1024:
            log("※ 1024未満のポートは Linux では root 権限 "
                "(または CAP_NET_BIND_SERVICE) が必要です")
        sys.exit(1)

    log(f"サーバ「{name}」起動: http://{disp}:{port}")
    log(f"対応ゲーム: {', '.join(g['label'] for g in GAMES.values())}")

    def _shutdown(*_):
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    try:
        httpd.serve_forever()
    finally:
        hub.stop()
        httpd.server_close()
        log("サーバを終了しました")


if __name__ == "__main__":
    main()
