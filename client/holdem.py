#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""マルチプレイ・テキサスホールデム (PySide6)

ホストモード : 全IP(0.0.0.0)で指定ポートをLISTENし、自身もプレイヤーとして参加。
クライアントモード : ホストのIPアドレスとポートを指定して接続。

ルール: ノーリミット、SB10/BB20、初期チップ1000。
オールイン時のサイドポットにも対応。手札は本人にのみ配信される。
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

# common を最初に import することで shared パッケージへのパスが通る
from common import GameWindowBase, clear_layout, fade_in, make_card_label
from shared.engines.holdem import BLIND_BB, HoldemEngine

# ---------------------------------------------------------------- メインウィンドウ

PHASE_TEXT = {
    "lobby": "ロビー", "preflop": "プリフロップ", "flop": "フロップ",
    "turn": "ターン", "river": "リバー", "showdown": "ショーダウン",
}
STATUS_TEXT = {
    "active": "", "folded": "フォールド", "allin": "オールイン",
    "waiting": "待機中 (次ハンドから)",
}


class HoldemWindow(GameWindowBase):
    DEFAULT_PORT = 35556
    GAME_TITLE = "テキサスホールデム"
    GAME_KEY = "holdem"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("マルチプレイ・テキサスホールデム")
        self.resize(980, 680)
        self.statusBar().showMessage("メニューの「ゲーム > 接続設定」から開始してください")
        self._prev_cards = {}     # key -> 前回描画したカード列 (フェードイン判定用)
        self._prev_message = ""

    # ---------------- UI 構築

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("table")
        central.setStyleSheet("QWidget#table { background:#254f26; }")
        root = QVBoxLayout(central)

        # コミュニティカード + ポット
        board_box = QGroupBox("ボード")
        board_box.setStyleSheet("QGroupBox { color:white; font-weight:bold; }")
        bv = QVBoxLayout(board_box)
        self.board_cards = QHBoxLayout()
        self.board_cards.addStretch()
        bv.addLayout(self.board_cards)
        self.pot_label = QLabel("")
        self.pot_label.setStyleSheet(
            "color:#ffe082; font-size:16px; font-weight:bold;")
        self.pot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bv.addWidget(self.pot_label)
        self.message_label = QLabel("")
        self.message_label.setStyleSheet("color:#8ef58e; font-size:14px;")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bv.addWidget(self.message_label)
        root.addWidget(board_box)

        # プレイヤー一覧(横スクロール)
        self.players_row = QHBoxLayout()
        players_holder = QWidget()
        players_holder.setLayout(self.players_row)
        players_holder.setStyleSheet("background:transparent;")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(players_holder)
        scroll.setStyleSheet("QScrollArea { background:transparent; border:none; }")
        scroll.setMinimumHeight(240)
        root.addWidget(scroll, 1)

        # 操作ボタン
        btn_row = QHBoxLayout()
        self.fold_btn = QPushButton("フォールド")
        self.call_btn = QPushButton("チェック")
        self.raise_spin = QSpinBox()
        self.raise_spin.setRange(BLIND_BB, 10 ** 7)
        self.raise_spin.setSingleStep(BLIND_BB)
        self.raise_spin.setMinimumHeight(40)
        self.raise_spin.setStyleSheet("font-size:15px;")
        self.raise_btn = QPushButton("レイズ")
        self.start_btn = QPushButton("ハンド開始")
        for b in (self.fold_btn, self.call_btn, self.raise_btn, self.start_btn):
            b.setMinimumHeight(40)
            b.setStyleSheet("font-size:15px; font-weight:bold;")
            b.setEnabled(False)
        self.raise_spin.setEnabled(False)
        self.fold_btn.clicked.connect(lambda: self.send_action("fold"))
        self.call_btn.clicked.connect(lambda: self.send_action("check_call"))
        self.raise_btn.clicked.connect(
            lambda: self.send_action("raise", self.raise_spin.value()))
        self.start_btn.clicked.connect(self.host_start_hand)
        btn_row.addStretch()
        btn_row.addWidget(self.fold_btn)
        btn_row.addWidget(self.call_btn)
        btn_row.addSpacing(20)
        btn_row.addWidget(QLabel("レイズ額:"))
        btn_row.addWidget(self.raise_spin)
        btn_row.addWidget(self.raise_btn)
        btn_row.addSpacing(30)
        btn_row.addWidget(self.start_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ログ
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(100)
        root.addWidget(self.log_view)

        self.setCentralWidget(central)

    # ---------------- 基底クラスのフック実装

    def create_engine(self):
        return HoldemEngine()

    def on_host_started(self):
        self.start_btn.setEnabled(True)

    def reset_game_ui(self):
        self._prev_cards = {}
        self._prev_message = ""
        for b in (self.fold_btn, self.call_btn, self.raise_btn, self.start_btn):
            b.setEnabled(False)
        self.raise_spin.setEnabled(False)
        clear_layout(self.board_cards)
        clear_layout(self.players_row)
        self.pot_label.setText("")
        self.message_label.setText("")

    def handle_action(self, pid, msg):
        return self.engine.act(
            pid, msg.get("action", ""), msg.get("amount", 0))

    # ---------------- 操作

    def send_action(self, action, amount=0):
        self.submit_action({"type": "action", "action": action,
                            "amount": amount})

    def host_start_hand(self):
        if self.mode == "client":
            self.request_start()   # 専用サーバのルームマスターとして開始要求
            return
        if self.mode != "host" or not self.engine:
            return
        if not self.engine.start_hand():
            self.log("◆ ハンドを開始できません (チップを持つプレイヤーが2人以上必要です)")
            return
        self.log("◆ 新しいハンドを開始しました")
        self.broadcast_info("◆ 新しいハンドを開始しました")
        self.broadcast_state()

    # ---------------- 状態描画

    def _add_cards(self, layout, cards, key):
        """カードを並べ、前回から増えた/変わった札だけフェードインさせる。"""
        prev = self._prev_cards.get(key, [])
        for i, card in enumerate(cards):
            lbl = make_card_label(card)
            layout.addWidget(lbl)
            if i >= len(prev) or list(prev[i]) != list(card):
                fade_in(lbl)
        self._prev_cards[key] = [list(c) for c in cards]

    def render_state(self, state):
        phase = state["phase"]

        # 退出済みプレイヤーのフェードイン判定情報を掃除
        alive_keys = {"community"} | {f"p{pid}" for pid in state["order"]}
        self._prev_cards = {k: v for k, v in self._prev_cards.items()
                            if k in alive_keys}

        # ボード
        clear_layout(self.board_cards)
        self.board_cards.addStretch()
        self._add_cards(self.board_cards, state["community"], "community")
        self.board_cards.addStretch()
        pot_text = f"ポット: {state['pot']}"
        if state["current_bet"]:
            pot_text += f"   現在のベット: {state['current_bet']}"
        pot_text += f"   [{PHASE_TEXT.get(phase, phase)}]"
        self.pot_label.setText(pot_text)
        self.message_label.setText(state["message"])
        if state["message"] and state["message"] != self._prev_message:
            fade_in(self.message_label, 420)   # 勝敗メッセージの登場を演出
        self._prev_message = state["message"]

        # プレイヤー
        clear_layout(self.players_row)
        for pid in state["order"]:
            p = state["players"][str(pid)]
            box = QGroupBox()
            title = p["name"]
            if pid == state["button"]:
                title += " Ⓓ"
            if pid == self.my_id:
                title += " (あなた)"
            box.setTitle(title)
            is_turn = state["turn"] == pid
            border = "#ffd54f" if is_turn else "#7fa886"
            box.setStyleSheet(
                f"QGroupBox {{ color:white; font-weight:bold;"
                f" border:2px solid {border}; border-radius:8px;"
                f" margin-top:8px; padding-top:4px; }}"
                f"QGroupBox::title {{ subcontrol-origin: margin; left:8px; }}")
            v = QVBoxLayout(box)
            cards_row = QHBoxLayout()
            self._add_cards(cards_row, p["hole"], f"p{pid}")
            cards_row.addStretch()
            v.addLayout(cards_row)
            info = QLabel(f"チップ: {p['chips']}  / ベット: {p['bet']}")
            info.setStyleSheet("color:#e0f2e9; font-size:13px;")
            v.addWidget(info)
            st_text = STATUS_TEXT.get(p["status"], p["status"])
            if p["hand_name"]:
                st_text = (st_text + "  " if st_text else "") + p["hand_name"]
            st = QLabel(st_text or ("あなたの番" if is_turn else " "))
            st.setStyleSheet("color:#ffe082; font-size:13px; font-weight:bold;")
            v.addWidget(st)
            res = QLabel(p["result"] or " ")
            res.setStyleSheet(
                "color:#8ef58e; font-size:15px; font-weight:bold;")
            v.addWidget(res)
            self.players_row.addWidget(box)
        self.players_row.addStretch()

        # ボタン制御
        me = state["players"].get(str(self.my_id))
        my_turn = (phase in HoldemEngine.BETTING_PHASES
                   and state["turn"] == self.my_id and me is not None)
        self.fold_btn.setEnabled(my_turn)
        self.call_btn.setEnabled(my_turn)
        if my_turn:
            to_call = state["current_bet"] - me["bet"]
            if to_call <= 0:
                self.call_btn.setText("チェック")
            else:
                self.call_btn.setText(f"コール ({min(to_call, me['chips'])})")
            max_to = me["bet"] + me["chips"]
            can_raise = max_to > state["current_bet"]
            self.raise_btn.setEnabled(can_raise)
            self.raise_spin.setEnabled(can_raise)
            if can_raise:
                lo = min(state["min_raise_to"], max_to)
                self.raise_spin.setRange(lo, max_to)
                self.raise_spin.setValue(lo)
        else:
            self.call_btn.setText("チェック")
            self.raise_btn.setEnabled(False)
            self.raise_spin.setEnabled(False)

        can = self.can_control(state)
        self.start_btn.setEnabled(can and phase in ("lobby", "showdown"))
        self.start_btn.setText(
            "次のハンド" if phase == "showdown" else "ハンド開始")

        # ステータスバー
        if my_turn:
            self.statusBar().showMessage(
                "あなたの番です! フォールド / チェック・コール / レイズを選んでください")
        elif phase in HoldemEngine.BETTING_PHASES and state["turn"] is not None:
            name = state["players"][str(state["turn"])]["name"]
            self.statusBar().showMessage(f"{name} の番です")
        elif phase == "showdown" and state["message"]:
            self.statusBar().showMessage(state["message"])


def main():
    app = QApplication(sys.argv)
    win = HoldemWindow()
    win.show()
    win.open_connect_dialog()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
