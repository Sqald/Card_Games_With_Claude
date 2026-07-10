#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTPゲーム通信レイヤ (サーバ / クライアント)

従来の改行区切りJSON (生TCP) を置き換える HTTP/1.1 + JSON の通信実装。
大学・会社などファイアウォールやプロキシのあるネットワークからでも
届きやすいことを目的とする。メッセージのJSON構造は従来と同一で、
上位層 (GameWindowBase / server.py) からは send / message / closed の
インターフェースで従来どおりに使える。

エンドポイント (すべて application/json):
  POST /api/join           hello メッセージで参加 → {"sid": セッションID}
  POST /api/send?sid=SID   ゲームメッセージを送信 → {"ok": true}
  GET  /api/poll?sid=SID   受信キューの取得 (ロングポーリング; 最長20秒保持)
                           → {"msgs": [...], "closed": bool}
  POST /api/leave?sid=SID  明示的な退出
  GET  /api/ping           死活確認 → {"ok": true, "app": "casino-games"}

セッションは poll が SESSION_TIMEOUT_SEC 秒間途絶えると退出扱いになる。
クライアントはOSのプロキシ設定を自動で利用する (大学のプロキシ環境対応)。
"""

import json
import secrets
import time
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import QCoreApplication, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import (
    QHostAddress, QNetworkAccessManager, QNetworkProxyFactory,
    QNetworkReply, QNetworkRequest, QTcpServer,
)

POLL_HOLD_SEC = 20        # ロングポーリングの最大保持時間
SESSION_TIMEOUT_SEC = 45  # pollが途絶えたら退出とみなす時間
MAX_REQUEST_BYTES = 64 * 1024

_REASON = {200: "OK", 400: "Bad Request", 404: "Not Found",
           405: "Method Not Allowed", 410: "Gone", 413: "Payload Too Large"}


# ---------------------------------------------------------------- サーバ側

class _HttpConn(QObject):
    """1リクエスト分のHTTP接続 (Connection: close で1接続1リクエスト)。"""

    def __init__(self, sock, server):
        super().__init__(server)
        self.sock = sock
        self.server = server
        self.buf = b""
        self.head = None       # (method, path, query)
        self.body_len = 0
        self.handled = False   # リクエストを上位層へ渡した後か
        self.done = False      # レスポンス送信済みか
        sock.readyRead.connect(self._on_ready)
        sock.disconnected.connect(self._on_gone)

    def _on_ready(self):
        if self.handled or self.done:
            return
        self.buf += bytes(self.sock.readAll())
        if len(self.buf) > MAX_REQUEST_BYTES:
            self.respond({"error": "too large"}, 413)
            return
        if self.head is None:
            i = self.buf.find(b"\r\n\r\n")
            if i < 0:
                return
            try:
                lines = self.buf[:i].decode("iso-8859-1").split("\r\n")
                method, target, _ = lines[0].split(" ", 2)
                headers = {}
                for line in lines[1:]:
                    k, _, v = line.partition(":")
                    headers[k.strip().lower()] = v.strip()
                parts = urlsplit(target)
                query = {k: v[0] for k, v in parse_qs(parts.query).items()}
                self.head = (method.upper(), parts.path, query)
                self.body_len = int(headers.get("content-length", "0") or 0)
            except (ValueError, IndexError):
                self.respond({"error": "bad request"}, 400)
                return
            self.buf = self.buf[i + 4:]
        if len(self.buf) < self.body_len:
            return
        body = self.buf[:self.body_len]
        method, path, query = self.head
        self.handled = True
        self.server._handle(self, method, path, query, body)

    def _on_gone(self):
        self.done = True
        self.server._conn_gone(self)
        self.deleteLater()

    def respond(self, obj, code=200):
        if self.done:
            return
        self.done = True
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        head = (f"HTTP/1.1 {code} {_REASON.get(code, 'OK')}\r\n"
                "Content-Type: application/json; charset=utf-8\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Cache-Control: no-store\r\n"
                "Connection: close\r\n\r\n")
        self.sock.write(head.encode("ascii") + body)
        self.sock.disconnectFromHost()


class HttpSession(QObject):
    """接続クライアント1人分のセッション。

    send(obj) で送信キューに積み、クライアントの poll に応答する。
    message は受信メッセージ、closed は切断 (退出/タイムアウト) を通知する。
    """

    message = Signal(object)
    closed = Signal()

    def __init__(self, sid, server):
        super().__init__(server)
        self.sid = sid
        self._server = server
        self.queue = []        # クライアントへ送る未配信メッセージ
        self.waiting = None    # 保留中のロングポール接続
        self.last_seen = time.monotonic()
        self.closing = False

    def send(self, obj):
        if self.closing:
            return
        self.queue.append(obj)
        self._server._flush(self)

    def close(self):
        """キューに残ったメッセージを届けてからセッションを終了する。"""
        if self.closing:
            return
        self.closing = True
        if self.waiting is not None:
            self._server._flush(self)
        # pollが保留されていなければ、次のpollかタイムアウト掃除で終了する


class HttpServer(QObject):
    """QTcpServer上で動く最小HTTPサーバ (ゲームセッション管理付き)。

    join を受けると HttpSession を作って new_session を発火し、
    続けて hello メッセージを session.message で上位層へ渡す。
    """

    new_session = Signal(object)   # HttpSession

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tcp = QTcpServer(self)
        self.tcp.newConnection.connect(self._on_new_connection)
        self.sessions = {}   # sid -> HttpSession
        self._sweeper = QTimer(self)
        self._sweeper.timeout.connect(self._sweep)

    # ---- 公開API

    def listen(self, port, address=QHostAddress.SpecialAddress.Any):
        ok = self.tcp.listen(address, port)
        if ok:
            self._sweeper.start(5000)
        return ok

    def is_listening(self):
        return self.tcp.isListening()

    def error_string(self):
        return self.tcp.errorString()

    def close(self):
        """待受を止め、全セッションを破棄する (closedシグナルは発火しない)。"""
        self._sweeper.stop()
        self.tcp.close()
        for sess in list(self.sessions.values()):
            if sess.waiting is not None:
                sess.waiting.respond({"msgs": sess.queue, "closed": True})
                sess.waiting = None
            sess.deleteLater()
        self.sessions = {}

    # ---- 接続処理

    def _on_new_connection(self):
        while self.tcp.hasPendingConnections():
            _HttpConn(self.tcp.nextPendingConnection(), self)

    def _conn_gone(self, conn):
        for sess in self.sessions.values():
            if sess.waiting is conn:
                sess.waiting = None   # クライアントがpollを中断した

    @staticmethod
    def _parse_json(body):
        try:
            return json.loads(body.decode("utf-8")) if body else {}
        except (ValueError, UnicodeDecodeError):
            return None

    def _handle(self, conn, method, path, query, body):
        if path == "/api/ping":
            conn.respond({"ok": True, "app": "casino-games"})
            return
        if path == "/api/join":
            if method != "POST":
                conn.respond({"error": "method"}, 405)
                return
            msg = self._parse_json(body)
            if not isinstance(msg, dict):
                conn.respond({"error": "bad json"}, 400)
                return
            sid = secrets.token_urlsafe(16)
            sess = HttpSession(sid, self)
            self.sessions[sid] = sess
            conn.respond({"sid": sid})
            self.new_session.emit(sess)
            sess.message.emit(msg)        # helloを上位層へ渡す
            return
        sess = self.sessions.get(query.get("sid", ""))
        if sess is None:
            conn.respond({"error": "unknown session"}, 410)
            return
        sess.last_seen = time.monotonic()
        if path == "/api/send":
            if method != "POST":
                conn.respond({"error": "method"}, 405)
                return
            msg = self._parse_json(body)
            if not isinstance(msg, dict):
                conn.respond({"error": "bad json"}, 400)
                return
            conn.respond({"ok": True})
            if not sess.closing:
                sess.message.emit(msg)
        elif path == "/api/poll":
            if sess.queue or sess.closing:
                self._respond_poll(sess, conn)
            else:
                if sess.waiting is not None:
                    # 多重pollは古い方を空応答で解放する
                    sess.waiting.respond({"msgs": [], "closed": False})
                sess.waiting = conn
                QTimer.singleShot(POLL_HOLD_SEC * 1000,
                                  lambda: self._poll_timeout(sess, conn))
        elif path == "/api/leave":
            conn.respond({"ok": True})
            self._drop(sess)
        else:
            conn.respond({"error": "not found"}, 404)

    def _respond_poll(self, sess, conn):
        conn.respond({"msgs": sess.queue, "closed": sess.closing})
        sess.queue = []
        if sess.closing:
            self._drop(sess, notify_poll=False)

    def _poll_timeout(self, sess, conn):
        if sess.waiting is conn and not conn.done:
            sess.waiting = None
            conn.respond({"msgs": [], "closed": False})

    def _flush(self, sess):
        if sess.waiting is not None:
            conn, sess.waiting = sess.waiting, None
            self._respond_poll(sess, conn)

    def _drop(self, sess, notify_poll=True):
        """セッションを終了し、上位層へ closed を通知する。"""
        if self.sessions.pop(sess.sid, None) is None:
            return
        if notify_poll and sess.waiting is not None:
            sess.waiting.respond({"msgs": sess.queue, "closed": True})
            sess.waiting = None
        # リクエスト処理中の再入を避けるため次のイベントループで通知する
        QTimer.singleShot(0, sess.closed.emit)

    def _sweep(self):
        now = time.monotonic()
        for sess in list(self.sessions.values()):
            if now - sess.last_seen > SESSION_TIMEOUT_SEC:
                self._drop(sess)


# ---------------------------------------------------------------- クライアント側

_bg_nam = None


def _background_nam():
    """退出通知など、クライアント破棄後も生かしたいリクエスト用のNAM。"""
    global _bg_nam
    if _bg_nam is None:
        _bg_nam = QNetworkAccessManager(QCoreApplication.instance())
    return _bg_nam

class HttpClient(QObject):
    """ゲーム用HTTPクライアント。

    open() で join し、以降はロングポーリングで受信して message を発火する。
    http:// と https:// の両方に対応し、OSのプロキシ設定を自動で使う。
    """

    message = Signal(object)
    closed = Signal()
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # 大学・会社のプロキシ環境でも届くようOS設定のプロキシを利用する
        QNetworkProxyFactory.setUseSystemConfiguration(True)
        self.nam = QNetworkAccessManager(self)
        self.base = ""
        self.sid = None
        self.active = False
        self._fails = 0
        self._replies = set()

    # ---- 公開API

    def open(self, base_url, hello):
        """base_url (例: http://host:port, https://example.com/games) へ参加。"""
        self.base = base_url.rstrip("/")
        self.active = True
        self._fails = 0
        self._request("POST", "/api/join", hello, self._on_join, 10000)

    def send(self, obj):
        if self.active and self.sid:
            self._request("POST", f"/api/send?sid={self.sid}", obj,
                          self._on_send, 10000)

    def close(self):
        """自発的に切断する (closedシグナルは発火しない)。"""
        if self.active and self.sid:
            # leave はこのクライアントが破棄されても届くよう、
            # アプリ全体で共有するNAMから送りっぱなしにする
            req = QNetworkRequest(
                QUrl(f"{self.base}/api/leave?sid={self.sid}"))
            req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                          "application/json")
            req.setTransferTimeout(3000)
            reply = _background_nam().post(req, b"{}")
            reply.finished.connect(reply.deleteLater)
        self._shutdown(emit=False)

    # ---- 内部

    def _request(self, method, path, obj, cb, timeout):
        req = QNetworkRequest(QUrl(self.base + path))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                      "application/json")
        req.setTransferTimeout(timeout)
        if method == "POST":
            data = json.dumps(obj or {}, ensure_ascii=False).encode("utf-8")
            reply = self.nam.post(req, data)
        else:
            reply = self.nam.get(req)
        self._replies.add(reply)
        reply.finished.connect(lambda: self._on_finished(reply, cb))

    def _on_finished(self, reply, cb):
        self._replies.discard(reply)
        reply.deleteLater()
        if cb is None:
            return
        status = reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        data = None
        if reply.error() == QNetworkReply.NetworkError.NoError:
            try:
                data = json.loads(bytes(reply.readAll()).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                data = None
        ok = data is not None and isinstance(data, dict) and status == 200
        cb(ok, status, data, reply.errorString())

    def _on_join(self, ok, status, data, errstr):
        if not self.active:
            return
        if not ok or "sid" not in data:
            self.error.emit(f"接続に失敗しました: {errstr or status}")
            self._shutdown(emit=True)
            return
        self.sid = data["sid"]
        self._poll()

    def _poll(self):
        if self.active and self.sid:
            self._request("GET", f"/api/poll?sid={self.sid}", None,
                          self._on_poll, (POLL_HOLD_SEC + 15) * 1000)

    def _on_poll(self, ok, status, data, errstr):
        if not self.active:
            return
        if ok:
            self._fails = 0
            for m in data.get("msgs", []):
                if isinstance(m, dict):
                    self.message.emit(m)
            if not self.active:
                return   # メッセージ処理中に切断された
            if data.get("closed"):
                self._shutdown(emit=True)
            else:
                self._poll()
            return
        if status == 410:   # サーバ側でセッションが消えている
            self._shutdown(emit=True)
            return
        self._fails += 1
        if self._fails >= 3:
            self.error.emit(f"サーバとの通信が途絶えました: {errstr}")
            self._shutdown(emit=True)
        else:
            QTimer.singleShot(1000, self._poll)   # 一時的な失敗はリトライ

    def _on_send(self, ok, status, data, errstr):
        if not ok and self.active:
            self.error.emit(f"送信に失敗しました: {errstr or status}")

    def _shutdown(self, emit):
        was = self.active
        self.active = False
        self.sid = None
        for reply in list(self._replies):
            reply.abort()
        self._replies = set()
        if emit and was:
            self.closed.emit()
