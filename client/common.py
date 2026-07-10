#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""クライアント共通モジュール: 接続ダイアログ・カード描画・
演出ヘルパー・ゲームウィンドウ基底クラス

通信プロトコル : HTTP/1.1 + JSON (httpnet モジュール)。
ホストがゲーム状態の権威を持ち、プレイヤーごとの視点の状態を配信する。
クライアントの受信はロングポーリングで行い、ファイアウォールや
プロキシのあるネットワーク (大学など) からでも接続できる。

接続ダイアログの初期値はリポジトリルートの .env (CLIENT_* キー) から
読み込む (sample.env 参照)。
"""

import sys
from pathlib import Path

# client/ のスクリプトを単体実行しても shared パッケージを解決できるように
# リポジトリルートを import パスへ追加する (各ゲームファイルは common を
# 最初に import することでこのパス設定を利用する)
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PySide6.QtCore import QAbstractAnimation, QPropertyAnimation, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGraphicsOpacityEffect, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QSpinBox,
)

from httpnet import HttpClient, HttpServer
from shared.cards import RANKS, SUITS   # noqa: F401 (各ゲームへ再エクスポート)
from shared.envfile import env_int, env_str, load_env

load_env()   # <ルート>/.env があれば接続初期値などを取り込む

HOST_ID = 0        # ホストプレイヤーのID


# ---------------------------------------------------------------- 接続設定ダイアログ

class ConnectDialog(QDialog):
    def __init__(self, parent=None, title="接続設定", default_port=35555):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._default_port = default_port
        form = QFormLayout(self)

        self.name_edit = QLineEdit(env_str("CLIENT_PLAYER_NAME", "Player"))
        form.addRow("プレイヤー名:", self.name_edit)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(
            ["ホストモード", "クライアントモード", "サーバー接続モード"])
        form.addRow("モード:", self.mode_combo)

        self.ip_edit = QLineEdit(env_str("CLIENT_ADDRESS", "127.0.0.1"))
        self.ip_edit.setPlaceholderText(
            "例: 192.168.1.10 / https://game.example.com")
        self.ip_edit.setToolTip(
            "IPアドレス・ドメイン名のほか http:// や https:// のURLも指定可。\n"
            "URLを指定した場合はポート番号欄は無視されます。")
        form.addRow("ホスト/サーバアドレス:", self.ip_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(default_port)
        self.port_spin.setToolTip(
            "アドレス欄にURLを指定した場合は無視されます")
        form.addRow("ポート番号:", self.port_spin)

        self.server_edit = QLineEdit(
            env_str("CLIENT_SERVER_NAME", "GameServer"))
        form.addRow("サーバ名:", self.server_edit)
        self.room_edit = QLineEdit(env_str("CLIENT_ROOM", "room1"))
        form.addRow("ルームID:", self.room_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("スタート")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self.mode_combo.currentIndexChanged.connect(self._update_fields)
        self._update_fields()

    def _update_fields(self):
        m = self.mode_combo.currentIndex()
        self.ip_edit.setEnabled(m != 0)
        self.server_edit.setEnabled(m == 2)
        self.room_edit.setEnabled(m == 2)
        # 専用サーバは .env の CLIENT_PORT (既定80) を初期値にする。
        # ローカルのホスト/クライアント通信は従来のゲーム別ポートのまま。
        self.port_spin.setValue(
            env_int("CLIENT_PORT", 80) if m == 2 else self._default_port)

    def mode(self):
        return ("host", "client", "server")[self.mode_combo.currentIndex()]


# ---------------------------------------------------------------- 演出ヘルパー

def fade_in(widget, duration=240):
    """ウィジェットを短くフェードインさせる (新しく現れた要素の強調用)。

    入力をブロックせず、終了後はエフェクトを外して描画コストを残さない。
    """
    eff = QGraphicsOpacityEffect(widget)
    eff.setOpacity(0.0)
    widget.setGraphicsEffect(eff)
    anim = QPropertyAnimation(eff, b"opacity", widget)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(duration)

    def _done():
        try:
            widget.setGraphicsEffect(None)
        except RuntimeError:
            pass   # ウィジェットが既に破棄されている場合

    anim.finished.connect(_done)
    anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


# ---------------------------------------------------------------- カード描画

def make_card_label(card):
    rank, suit = card
    lbl = QLabel(f"{rank}\n{suit}")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setFixedSize(52, 74)
    if rank == "?":
        lbl.setStyleSheet(
            "background:#1c4e8a; color:#9fc3ee; border:2px solid #ddd;"
            "border-radius:6px; font-size:18px; font-weight:bold;")
        lbl.setText("?")
    else:
        color = "#c0392b" if suit in ("♥", "♦") else "#222"
        lbl.setStyleSheet(
            f"background:white; color:{color}; border:2px solid #bbb;"
            "border-radius:6px; font-size:16px; font-weight:bold;")
    return lbl


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            # deleteLater() は即時削除ではないため、先に親から外して残像を防ぐ
            w.hide()
            w.setParent(None)
            w.deleteLater()


# ---------------------------------------------------------------- ゲームウィンドウ基底クラス

class GameWindowBase(QMainWindow):
    """ホスト/クライアントの通信部分を担う基底クラス。

    サブクラスは以下を実装する:
      _build_ui()            : ゲーム固有のUI構築
      create_engine()        : ゲームエンジン生成 (ホスト時)
      render_state(state)    : 状態の描画
      handle_action(pid,msg) : アクション処理 (ホスト時)。状態が変わったら True
      reset_game_ui()        : 切断時のUIリセット
      on_host_started()      : ホスト開始時のUI有効化
    """

    DEFAULT_PORT = 35555
    GAME_TITLE = "ゲーム"
    GAME_KEY = "game"      # server.py のルームで使うゲーム識別子

    def __init__(self):
        super().__init__()
        self.mode = None          # "host" / "client"
        self.server = None        # HttpServer (ホスト時)
        self.clients = {}         # pid -> HttpSession (ホスト時)
        self.conn = None          # HttpClient (クライアント時)
        self.engine = None        # ゲームエンジン (ホスト時)
        self.my_id = None
        self.my_name = "Player"
        self.next_pid = 1
        self.last_state = None
        self._build_ui()
        self._build_menu()

    # ---------------- サブクラスが実装するフック

    def _build_ui(self):
        raise NotImplementedError

    def create_engine(self):
        raise NotImplementedError

    def render_state(self, state):
        raise NotImplementedError

    def handle_action(self, pid, msg):
        raise NotImplementedError

    def reset_game_ui(self):
        pass

    def on_host_started(self):
        pass

    # ---------------- 共通UI

    def _build_menu(self):
        menu = self.menuBar().addMenu("ゲーム")
        act_conn = QAction("接続設定...", self)
        act_conn.triggered.connect(self.open_connect_dialog)
        menu.addAction(act_conn)
        act_dc = QAction("切断", self)
        act_dc.triggered.connect(self.disconnect_all)
        menu.addAction(act_dc)
        menu.addSeparator()
        act_quit = QAction("終了", self)
        act_quit.triggered.connect(self.close)
        menu.addAction(act_quit)

    def log(self, text):
        # サブクラスは self.log_view (QTextEdit) を用意する
        if hasattr(self, "log_view"):
            self.log_view.append(text)

    def closeEvent(self, event):
        # ウィジェット破棄後にソケットの切断イベントが飛ばないよう先に接続を閉じる
        self.disconnect_all()
        super().closeEvent(event)

    # ---------------- 接続設定

    def open_connect_dialog(self):
        dlg = ConnectDialog(
            self, title=f"{self.GAME_TITLE} - 接続設定",
            default_port=self.DEFAULT_PORT)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.disconnect_all()
        self.my_name = dlg.name_edit.text().strip() or "Player"
        port = dlg.port_spin.value()
        mode = dlg.mode()
        if mode == "host":
            self.start_host(port)
        elif mode == "client":
            self.start_client(dlg.ip_edit.text().strip(), port)
        else:
            server = dlg.server_edit.text().strip()
            room = dlg.room_edit.text().strip()
            if not server or not room:
                QMessageBox.warning(
                    self, "エラー", "サーバ名とルームIDを入力してください")
                return
            self.start_client(dlg.ip_edit.text().strip(), port,
                              server=server, room=room)

    def disconnect_all(self):
        if self.server:
            self.server.close()
            self.server.deleteLater()
            self.server = None
        if self.conn:
            self.conn.close()
            self.conn.deleteLater()
            self.conn = None
        self.clients = {}
        self.engine = None
        self.mode = None
        self.my_id = None
        self.last_state = None
        self.next_pid = 1
        self.reset_game_ui()
        self.statusBar().showMessage("切断しました")

    # ---------------- ホストモード

    def start_host(self, port):
        server = HttpServer(self)
        if not server.listen(port):
            QMessageBox.critical(
                self, "エラー",
                f"ポート {port} でLISTENできません:\n{server.error_string()}")
            server.deleteLater()
            return
        self.server = server
        self.mode = "host"
        self.my_id = HOST_ID
        self.engine = self.create_engine()
        self.engine.add_player(HOST_ID, self.my_name)
        server.new_session.connect(self._on_new_session)
        self.on_host_started()
        self.statusBar().showMessage(
            f"ホストモード: 0.0.0.0:{port} でHTTP待受中 (全IPからのアクセスを許可)")
        self.log(f"◆ サーバー開始: ポート {port} (HTTP / 全インターフェースで待受)")
        self.broadcast_state()

    def _on_new_session(self, sess):
        pid = self.next_pid
        self.next_pid += 1
        self.clients[pid] = sess
        sess.message.connect(lambda msg, pid=pid: self._on_client_msg(pid, msg))
        sess.closed.connect(lambda pid=pid: self._on_client_left(pid))

    def _on_client_msg(self, pid, msg):
        t = msg.get("type")
        if t == "hello":
            name = str(msg.get("name", "")).strip() or f"Player{pid}"
            self.engine.add_player(pid, name)
            self.clients[pid].send({"type": "welcome", "id": pid})
            self.log(f"◆ {name} が参加しました")
            self.broadcast_info(f"◆ {name} が参加しました")
            self.broadcast_state()
        elif t == "action":
            if self.handle_action(pid, msg):
                self.broadcast_state()

    def _on_client_left(self, pid):
        sess = self.clients.pop(pid, None)
        if sess:
            sess.deleteLater()
        if self.engine and pid in self.engine.players:
            name = self.engine.players[pid]["name"]
            self.engine.remove_player(pid)
            self.log(f"◆ {name} が退出しました")
            self.broadcast_info(f"◆ {name} が退出しました")
            self.broadcast_state()

    def broadcast_info(self, text):
        for ls in self.clients.values():
            ls.send({"type": "info", "msg": text})

    def broadcast_state(self):
        if not self.engine:
            return
        for pid, ls in self.clients.items():
            ls.send({"type": "state", "state": self.engine.public_state(pid)})
        self._apply_state(self.engine.public_state(self.my_id))

    # ---------------- クライアントモード

    def start_client(self, address, port, server=None, room=None):
        """address には IP・ドメイン名のほか http(s):// のURLも指定できる。

        URLを指定した場合は port は無視される (リバースプロキシや
        https 経由での接続用)。
        """
        if not address:
            QMessageBox.warning(
                self, "エラー",
                "アドレス (IP・ドメイン名・URL) を入力してください")
            return
        hello = {"type": "hello", "name": self.my_name}
        if server is not None:
            # 専用サーバ (server.py) への接続: サーバ名+ルームIDで参加する
            hello.update(server=server, room=room, game=self.GAME_KEY)
        base = address if "://" in address else f"http://{address}:{port}"
        conn = HttpClient(self)
        conn.message.connect(self._on_server_msg)
        conn.closed.connect(self._on_server_closed)
        conn.error.connect(self._on_client_error)
        self.conn = conn
        self.mode = "client"
        target = base + (f" (ルーム: {room})" if server else "")
        self.statusBar().showMessage(f"{target} に接続中...")
        self.log(f"◆ {target} に接続しています...")
        conn.open(base, hello)

    def _on_client_error(self, text):
        if self.mode == "client":
            self.log(f"◆ 接続エラー: {text}")
            self.statusBar().showMessage(f"接続エラー: {text}")

    def _on_server_closed(self):
        if self.mode == "client":
            self.log("◆ サーバーとの接続が切れました")
            self.disconnect_all()

    def _on_server_msg(self, msg):
        t = msg.get("type")
        if t == "welcome":
            self.my_id = msg["id"]
            self.statusBar().showMessage(
                f"クライアントモード: 接続完了 (あなたのID: {self.my_id})")
            self.log("◆ ホストに接続しました。ホストの開始を待っています")
        elif t == "state":
            self._apply_state(msg["state"])
        elif t == "info":
            self.log(msg.get("msg", ""))
        elif t == "error":
            text = msg.get("msg", "サーバーエラー")
            self.log(f"◆ エラー: {text}")
            self.statusBar().showMessage(f"エラー: {text}")

    # ---------------- 共通: 状態適用・操作送信

    def _apply_state(self, state):
        self.last_state = state
        self.render_state(state)

    def submit_action(self, msg):
        """自分のアクションを送る (ホストならローカル処理、クライアントなら送信)。"""
        if self.mode == "host":
            if self.handle_action(self.my_id, msg):
                self.broadcast_state()
        elif self.mode == "client" and self.conn:
            self.conn.send(msg)

    def can_control(self, state):
        """ゲーム開始などの進行操作ができるか。

        ホストモードでは常に可。専用サーバ接続時はルームマスター
        (state["master"]) のみ可。GUIホストへの接続時は master が
        含まれないため常に不可。
        """
        if self.mode == "host":
            return True
        return self.my_id is not None and state.get("master") == self.my_id

    def request_start(self):
        """専用サーバへゲーム開始を要求する (ルームマスター用)。"""
        if self.mode == "client" and self.conn:
            self.conn.send({"type": "start"})
