#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""マルチプレイ・Color & Numbers (PySide6)

ホストモード : 全IP(0.0.0.0)で指定ポートをLISTENし、自身もプレイヤーとして参加。
クライアントモード : ホストのIPアドレスとポートを指定して接続。

色または数字が合うカードを出していき、先に手札を出し切ったら勝ちの
カードゲーム。スキップ / リバース / ドロー2 / ワイルド / ドロー4 に対応。
手札は本人にのみ配信され、上がった時点で他プレイヤーの手札点数を獲得する。
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

# common を最初に import することで shared パッケージへのパスが通る
from common import GameWindowBase, clear_layout, fade_in
from shared.engines.color_numbers import (
    COLORS, ColorNumbersEngine, is_playable,
)

COLOR_JP = {"R": "赤", "G": "緑", "B": "青", "Y": "黄"}
CARD_CSS = {"R": "#c0392b", "G": "#27ae60", "B": "#2980b9",
            "Y": "#d4ac0d", "W": "#333"}
VALUE_DISP = {"skip": "⊘", "rev": "⇄", "+2": "+2", "wild": "★", "+4": "+4"}


# ---------------------------------------------------------------- UI 部品

def card_text(card):
    return VALUE_DISP.get(card[1], card[1])


CARD_CSS_DIM = {"R": "#6b3430", "G": "#2f5c43", "B": "#2f4a61",
                "Y": "#6e6136", "W": "#3a3a3a"}


def card_style(card, size=16, dim=False):
    if dim:
        # 出せないカードは暗く表示
        return (f"background:{CARD_CSS_DIM[card[0]]}; color:#999;"
                f"border:2px solid #777; border-radius:6px;"
                f"font-size:{size}px; font-weight:bold;")
    color = CARD_CSS[card[0]]
    fg = "#333" if card[0] == "Y" else "white"
    return (f"background:{color}; color:{fg}; border:2px solid #eee;"
            f"border-radius:6px; font-size:{size}px; font-weight:bold;")


class ColorPickDialog(QDialog):
    """ワイルドカード用の色選択ダイアログ。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("色を選択")
        self.picked = None
        row = QHBoxLayout(self)
        for code in COLORS:
            btn = QPushButton(COLOR_JP[code])
            btn.setFixedSize(70, 60)
            fg = "#333" if code == "Y" else "white"
            btn.setStyleSheet(
                f"background:{CARD_CSS[code]}; color:{fg};"
                "font-size:16px; font-weight:bold; border-radius:8px;")
            btn.clicked.connect(lambda _, c=code: self._pick(c))
            row.addWidget(btn)

    def _pick(self, code):
        self.picked = code
        self.accept()

    @staticmethod
    def get(parent=None):
        dlg = ColorPickDialog(parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.picked
        return None


# ---------------------------------------------------------------- メインウィンドウ

class ColorNumbersWindow(GameWindowBase):
    DEFAULT_PORT = 35558
    GAME_TITLE = "Color & Numbers"
    GAME_KEY = "colornum"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("マルチプレイ・Color & Numbers")
        self.resize(1000, 720)
        self.statusBar().showMessage("メニューの「ゲーム > 接続設定」から開始してください")
        self._prev_top = None        # 場札の変化検出 (フェードイン用)
        self._prev_direction = None
        self._prev_message = ""

    # ---------------- UI 構築

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("table")
        central.setStyleSheet("QWidget#table { background:#5c1f1f; }")
        root = QVBoxLayout(central)

        # 場 (捨て札トップ・現在色・方向・山札)
        board_box = QGroupBox("場")
        board_box.setStyleSheet("QGroupBox { color:white; font-weight:bold; }")
        bv = QVBoxLayout(board_box)
        top_row = QHBoxLayout()
        top_row.addStretch()
        self.top_card_label = QLabel("-")
        self.top_card_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.top_card_label.setFixedSize(64, 92)
        self.top_card_label.setStyleSheet(
            "background:#444; color:#999; border:2px solid #eee;"
            "border-radius:6px; font-size:18px; font-weight:bold;")
        top_row.addWidget(self.top_card_label)
        info_col = QVBoxLayout()
        self.color_label = QLabel("")
        self.color_label.setStyleSheet(
            "color:white; font-size:14px; font-weight:bold;")
        info_col.addWidget(self.color_label)
        self.dir_label = QLabel("")
        self.dir_label.setStyleSheet("color:#ffd54f; font-size:14px;")
        info_col.addWidget(self.dir_label)
        self.deck_label = QLabel("")
        self.deck_label.setStyleSheet("color:#e8c9c9; font-size:13px;")
        info_col.addWidget(self.deck_label)
        top_row.addSpacing(16)
        top_row.addLayout(info_col)
        top_row.addStretch()
        bv.addLayout(top_row)
        self.message_label = QLabel("")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setStyleSheet(
            "color:#8ef58e; font-size:15px; font-weight:bold;")
        bv.addWidget(self.message_label)
        root.addWidget(board_box)

        # プレイヤー一覧
        self.players_row = QHBoxLayout()
        players_holder = QWidget()
        players_holder.setLayout(self.players_row)
        players_holder.setStyleSheet("background:transparent;")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(players_holder)
        scroll.setStyleSheet("QScrollArea { background:transparent; border:none; }")
        scroll.setMinimumHeight(150)
        root.addWidget(scroll, 1)

        # 自分の手札
        hand_box = QGroupBox("あなたの手札 (クリックで出す)")
        hand_box.setStyleSheet("QGroupBox { color:white; font-weight:bold; }")
        hv = QVBoxLayout(hand_box)
        self.hand_row = QHBoxLayout()
        hand_holder = QWidget()
        hand_holder.setLayout(self.hand_row)
        hand_holder.setStyleSheet("background:transparent;")
        hand_scroll = QScrollArea()
        hand_scroll.setWidgetResizable(True)
        hand_scroll.setWidget(hand_holder)
        hand_scroll.setStyleSheet(
            "QScrollArea { background:transparent; border:none; }")
        hand_scroll.setFixedHeight(120)
        hv.addWidget(hand_scroll)
        root.addWidget(hand_box)

        # 操作ボタン
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.draw_btn = QPushButton("カードを引く")
        self.pass_btn = QPushButton("パス")
        self.start_btn = QPushButton("ゲーム開始")
        for b in (self.draw_btn, self.pass_btn, self.start_btn):
            b.setMinimumHeight(40)
            b.setStyleSheet("font-size:15px; font-weight:bold;")
            b.setEnabled(False)
        self.draw_btn.clicked.connect(
            lambda: self.submit_action({"type": "action", "action": "draw"}))
        self.pass_btn.clicked.connect(
            lambda: self.submit_action({"type": "action", "action": "pass"}))
        self.start_btn.clicked.connect(self.host_start_game)
        btn_row.addWidget(self.draw_btn)
        btn_row.addWidget(self.pass_btn)
        btn_row.addSpacing(30)
        btn_row.addWidget(self.start_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ログ
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(90)
        root.addWidget(self.log_view)

        self.setCentralWidget(central)

    # ---------------- 基底クラスのフック実装

    def create_engine(self):
        return ColorNumbersEngine()

    def on_host_started(self):
        self.start_btn.setEnabled(True)

    def reset_game_ui(self):
        self._prev_top = None
        self._prev_direction = None
        self._prev_message = ""
        for b in (self.draw_btn, self.pass_btn, self.start_btn):
            b.setEnabled(False)
        clear_layout(self.players_row)
        clear_layout(self.hand_row)
        self.top_card_label.setText("-")
        self.top_card_label.setStyleSheet(
            "background:#444; color:#999; border:2px solid #eee;"
            "border-radius:6px; font-size:18px; font-weight:bold;")
        self.color_label.setText("")
        self.dir_label.setText("")
        self.deck_label.setText("")
        self.message_label.setText("")

    def handle_action(self, pid, msg):
        return self.engine.act(
            pid, msg.get("action", ""), msg.get("index"), msg.get("color"))

    # ---------------- 操作

    def host_start_game(self):
        if self.mode == "client":
            self.request_start()   # 専用サーバのルームマスターとして開始要求
            return
        if self.mode != "host" or not self.engine:
            return
        if not self.engine.start_game():
            self.log("◆ ゲームを開始できません (2人以上必要です)")
            return
        self.log("◆ 新しいゲームを開始しました")
        self.broadcast_info("◆ 新しいゲームを開始しました")
        self.broadcast_state()

    def _on_card_clicked(self, index, card):
        msg = {"type": "action", "action": "play", "index": index}
        if card[0] == "W":
            color = ColorPickDialog.get(self)
            if color is None:
                return
            msg["color"] = color
        self.submit_action(msg)

    # ---------------- 状態描画

    def render_state(self, state):
        phase = state["phase"]

        # 場
        top = state["top"]
        if top:
            self.top_card_label.setText(card_text(top))
            self.top_card_label.setStyleSheet(card_style(top, size=20))
            if self._prev_top is not None and list(top) != self._prev_top:
                fade_in(self.top_card_label, 300)   # 出されたカードを演出
        self._prev_top = list(top) if top else None
        col = state["current_color"]
        if col and phase == "playing":
            self.color_label.setText(f"現在の色: {COLOR_JP.get(col, col)}")
            self.color_label.setStyleSheet(
                f"color:white; font-size:14px; font-weight:bold;"
                f"background:{CARD_CSS[col]}; border-radius:4px; padding:2px 8px;")
        else:
            self.color_label.setText("")
            self.color_label.setStyleSheet(
                "color:white; font-size:14px; font-weight:bold;")
        if phase == "playing":
            self.dir_label.setText(
                "順回り →" if state["direction"] == 1 else "← 逆回り")
            if (self._prev_direction is not None
                    and state["direction"] != self._prev_direction):
                fade_in(self.dir_label, 360)   # リバース発動を演出
            self._prev_direction = state["direction"]
            self.deck_label.setText(f"山札: {state['deck_count']} 枚")
        else:
            self._prev_direction = None
            self.dir_label.setText("")
            self.deck_label.setText("")
        self.message_label.setText(state["message"])
        if state["message"] and state["message"] != self._prev_message:
            fade_in(self.message_label, 420)   # 勝敗メッセージの登場を演出
        self._prev_message = state["message"]

        # プレイヤー
        clear_layout(self.players_row)
        for pid in state["order"]:
            p = state["players"][str(pid)]
            box = QGroupBox()
            title = p["name"] + (" (あなた)" if pid == self.my_id else "")
            box.setTitle(title)
            is_turn = state["turn"] == pid
            border = "#ffd54f" if is_turn else "#b38585"
            box.setStyleSheet(
                f"QGroupBox {{ color:white; font-weight:bold;"
                f" border:2px solid {border}; border-radius:8px;"
                f" margin-top:8px; padding-top:4px; }}"
                f"QGroupBox::title {{ subcontrol-origin: margin; left:8px; }}")
            v = QVBoxLayout(box)
            if p["in_round"]:
                info = QLabel(f"手札: {p['count']} 枚  / スコア: {p['score']}")
            else:
                info = QLabel(f"待機中 (次ゲームから)  / スコア: {p['score']}")
            info.setStyleSheet("color:#f2dede; font-size:13px;")
            v.addWidget(info)
            badge = ""
            if phase == "playing" and p["in_round"] and p["count"] == 1:
                badge = "ラスト1枚!"
            elif is_turn:
                badge = "手番"
            st = QLabel(badge or " ")
            st.setStyleSheet(
                "color:#ff8a8a; font-size:15px; font-weight:bold;"
                if badge == "ラスト1枚!" else
                "color:#ffe082; font-size:13px; font-weight:bold;")
            v.addWidget(st)
            # 結果画面では残った手札を公開
            if (phase == "result" and pid != self.my_id
                    and p["hand"]):
                mini_row = QHBoxLayout()
                for card in p["hand"][:10]:
                    ml = QLabel(card_text(card))
                    ml.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    ml.setFixedSize(30, 44)
                    ml.setStyleSheet(card_style(card, size=11))
                    mini_row.addWidget(ml)
                mini_row.addStretch()
                v.addLayout(mini_row)
            v.addStretch()
            self.players_row.addWidget(box)
        self.players_row.addStretch()

        # 自分の手札
        clear_layout(self.hand_row)
        me = state["players"].get(str(self.my_id))
        my_turn = phase == "playing" and state["turn"] == self.my_id
        pending_mine = state["pending"] == self.my_id and my_turn
        p_idx = state["pending_index"]
        hand = (me or {}).get("hand") or []
        for i, card in enumerate(hand):
            btn = QPushButton(card_text(card))
            btn.setFixedSize(58, 84)
            ok = (my_turn
                  and (not pending_mine or i == p_idx)
                  and top is not None
                  and is_playable(card, top, col))
            btn.setStyleSheet(card_style(card, size=16, dim=not ok))
            btn.setEnabled(ok)
            btn.clicked.connect(
                lambda _, i=i, c=tuple(card): self._on_card_clicked(i, c))
            self.hand_row.addWidget(btn)
        self.hand_row.addStretch()

        # ボタン制御
        self.draw_btn.setEnabled(my_turn and not pending_mine)
        self.pass_btn.setEnabled(pending_mine)
        can = self.can_control(state)
        self.start_btn.setEnabled(can and phase != "playing")
        self.start_btn.setText(
            "次のゲーム" if phase == "result" else "ゲーム開始")

        # ステータスバー
        if pending_mine:
            self.statusBar().showMessage(
                "引いたカードを出すか「パス」を押してください")
        elif my_turn:
            self.statusBar().showMessage(
                "あなたの番です! カードを出すか「カードを引く」を押してください")
        elif phase == "playing" and state["turn"] is not None:
            name = state["players"][str(state["turn"])]["name"]
            self.statusBar().showMessage(f"{name} の番です")
        elif phase == "result":
            self.statusBar().showMessage(state["message"])


def main():
    app = QApplication(sys.argv)
    win = ColorNumbersWindow()
    win.show()
    win.open_connect_dialog()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
