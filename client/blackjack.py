#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""マルチプレイ・ブラックジャック (PySide6)

ホストモード : 全IP(0.0.0.0)で指定ポートをLISTENし、自身もプレイヤーとして参加。
クライアントモード : ホストのIPアドレスとポートを指定して接続。
"""

import copy
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QTextEdit, QVBoxLayout, QWidget,
)

# common を最初に import することで shared パッケージへのパスが通る
from common import GameWindowBase, clear_layout, fade_in, make_card_label
from shared.engines.blackjack import GameEngine

# ---------------------------------------------------------------- メインウィンドウ

class BlackjackWindow(GameWindowBase):
    DEFAULT_PORT = 35555
    GAME_TITLE = "ブラックジャック"
    GAME_KEY = "blackjack"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("マルチプレイ・ブラックジャック")
        self.resize(900, 640)
        self.statusBar().showMessage("メニューの「ゲーム > 接続設定」から開始してください")
        # ディーラー公開演出: 結果を伏せたままカードを1枚ずつめくる
        self._reveal_timer = QTimer(self)
        self._reveal_timer.timeout.connect(self._reveal_step)
        self._revealing = False
        self._reveal_shown = 0
        self._rendered_phase = None
        self._prev_cards = {}   # key -> 前回描画したカード列 (フェードイン判定用)

    # ---------------- UI 構築

    def _build_ui(self):
        central = QWidget()
        central.setStyleSheet("QWidget#table { background:#1e6b3c; }")
        central.setObjectName("table")
        root = QVBoxLayout(central)

        # ディーラー
        dealer_box = QGroupBox("ディーラー")
        dealer_box.setStyleSheet("QGroupBox { color:white; font-weight:bold; }")
        dv = QVBoxLayout(dealer_box)
        self.dealer_cards = QHBoxLayout()
        self.dealer_cards.addStretch()
        dv.addLayout(self.dealer_cards)
        self.dealer_value_label = QLabel("")
        self.dealer_value_label.setStyleSheet("color:#ffe082; font-size:14px;")
        self.dealer_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dv.addWidget(self.dealer_value_label)
        root.addWidget(dealer_box)

        # プレイヤー一覧(横スクロール)
        self.players_row = QHBoxLayout()
        players_holder = QWidget()
        players_holder.setLayout(self.players_row)
        players_holder.setStyleSheet("background:transparent;")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(players_holder)
        scroll.setStyleSheet("QScrollArea { background:transparent; border:none; }")
        scroll.setMinimumHeight(230)
        root.addWidget(scroll, 1)

        # 操作ボタン
        btn_row = QHBoxLayout()
        self.hit_btn = QPushButton("ヒット")
        self.stand_btn = QPushButton("スタンド")
        self.start_btn = QPushButton("ラウンド開始")
        for b in (self.hit_btn, self.stand_btn, self.start_btn):
            b.setMinimumHeight(40)
            b.setStyleSheet("font-size:15px; font-weight:bold;")
            b.setEnabled(False)
        self.hit_btn.clicked.connect(lambda: self.send_action("hit"))
        self.stand_btn.clicked.connect(lambda: self.send_action("stand"))
        self.start_btn.clicked.connect(self.host_start_round)
        btn_row.addStretch()
        btn_row.addWidget(self.hit_btn)
        btn_row.addWidget(self.stand_btn)
        btn_row.addSpacing(30)
        btn_row.addWidget(self.start_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ログ
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(110)
        root.addWidget(self.log_view)

        self.setCentralWidget(central)

    # ---------------- 基底クラスのフック実装

    def create_engine(self):
        return GameEngine()

    def on_host_started(self):
        self.start_btn.setEnabled(True)

    def reset_game_ui(self):
        self._reveal_timer.stop()
        self._revealing = False
        self._reveal_shown = 0
        self._rendered_phase = None
        self._prev_cards = {}
        for b in (self.hit_btn, self.stand_btn, self.start_btn):
            b.setEnabled(False)
        clear_layout(self.dealer_cards)
        clear_layout(self.players_row)
        self.dealer_value_label.setText("")

    def handle_action(self, pid, msg):
        return self.engine.act(pid, msg.get("action", ""))

    # ---------------- 操作

    def send_action(self, action):
        self.submit_action({"type": "action", "action": action})

    def host_start_round(self):
        if self.mode == "host" and self.engine:
            self.engine.start_round()
            self.log("◆ 新しいラウンドを開始しました")
            self.broadcast_info("◆ 新しいラウンドを開始しました")
            self.broadcast_state()
        elif self.mode == "client":
            self.request_start()   # 専用サーバのルームマスターとして開始要求

    # ---------------- 状態描画 (ディーラー公開演出付き)

    def render_state(self, state):
        if self._revealing:
            # 演出終了までは結果を伏せた状態を描画し続ける
            self._render(self._mask_reveal(state))
            return
        if (self._rendered_phase == "playing" and state["phase"] == "result"
                and len(state["dealer"]) >= 2):
            # 全員の手番終了 → ディーラーのカードを1枚ずつ公開する
            self._revealing = True
            self._reveal_shown = 1
            self._render(self._mask_reveal(state))
            self._reveal_timer.start(650)
            return
        self._render(state)

    def _mask_reveal(self, state):
        """公開演出中: 未公開のディーラーカードと勝敗・チップを伏せる。"""
        s = copy.deepcopy(state)
        dealer = s["dealer"]
        shown = min(self._reveal_shown, len(dealer))
        s["dealer"] = dealer[:shown] + [["?", "?"]] * (len(dealer) - shown)
        if shown < len(dealer):
            s["dealer_value"] = None
        for p in s["players"].values():
            p["result"] = ""
            p["chips"] = "?"   # 精算後のチップ額から結果が分かるため
        return s

    def _reveal_step(self):
        state = self.last_state
        if not state:
            self._reveal_timer.stop()
            self._revealing = False
            return
        self._reveal_shown += 1
        if self._reveal_shown > len(state["dealer"]):
            # 全カード公開済み → 1拍おいて結果を一括公開
            self._reveal_timer.stop()
            self._revealing = False
            self._render(state, fade_results=True)
            if state.get("dealer_value") is not None:
                self.log(f"◆ ディーラーの合計: {state['dealer_value']}")
            return
        self._render(self._mask_reveal(state))

    def _add_cards(self, layout, cards, key):
        """カードを並べ、前回から増えた/変わった札だけフェードインさせる。"""
        prev = self._prev_cards.get(key, [])
        for i, card in enumerate(cards):
            lbl = make_card_label(card)
            layout.addWidget(lbl)
            if i >= len(prev) or list(prev[i]) != list(card):
                fade_in(lbl)
        self._prev_cards[key] = [list(c) for c in cards]

    def _render(self, state, fade_results=False):
        phase = state["phase"]
        self._rendered_phase = phase

        # ディーラー
        clear_layout(self.dealer_cards)
        self.dealer_cards.addStretch()
        self._add_cards(self.dealer_cards, state["dealer"], "dealer")
        self.dealer_cards.addStretch()
        if state["dealer_value"] is not None:
            self.dealer_value_label.setText(f"合計: {state['dealer_value']}")
        elif state["dealer"]:
            self.dealer_value_label.setText("合計: ?")
        else:
            self.dealer_value_label.setText("")

        # プレイヤー
        clear_layout(self.players_row)
        # 退出済みプレイヤーのフェードイン判定情報を掃除
        alive_keys = {"dealer"} | {f"p{pid}" for pid in state["order"]}
        self._prev_cards = {k: v for k, v in self._prev_cards.items()
                            if k in alive_keys}
        status_text = {
            "waiting": "待機中", "stand": "スタンド",
            "bust": "バースト!", "blackjack": "ブラックジャック!",
        }
        for pid in state["order"]:
            p = state["players"][str(pid)]
            box = QGroupBox()
            title = p["name"] + (" (あなた)" if pid == self.my_id else "")
            box.setTitle(title)
            # 選択待ちのプレイヤーを強調表示
            deciding = (phase == "playing" and p["status"] == "playing"
                        and not p["chosen"])
            border = "#ffd54f" if deciding else "#89b89b"
            box.setStyleSheet(
                f"QGroupBox {{ color:white; font-weight:bold;"
                f" border:2px solid {border}; border-radius:8px;"
                f" margin-top:8px; padding-top:4px; }}"
                f"QGroupBox::title {{ subcontrol-origin: margin; left:8px; }}")
            v = QVBoxLayout(box)
            cards_row = QHBoxLayout()
            self._add_cards(cards_row, p["cards"], f"p{pid}")
            cards_row.addStretch()
            v.addLayout(cards_row)
            info = QLabel(
                f"合計: {p['value'] if p['cards'] else '-'}  / "
                f"チップ: {p['chips']}")
            info.setStyleSheet("color:#e0f2e9; font-size:13px;")
            v.addWidget(info)
            if p["status"] == "playing":
                st_str = "選択済み ✓" if p["chosen"] else "選択中..."
            else:
                st_str = status_text.get(p["status"], p["status"])
            st = QLabel(st_str)
            st.setStyleSheet("color:#ffe082; font-size:13px; font-weight:bold;")
            v.addWidget(st)
            if p["result"]:
                res = QLabel(p["result"])
                color = ("#8ef58e" if p["result"].startswith("WIN")
                         else "#ff9e9e" if p["result"].startswith("LOSE")
                         else "#dddddd")
                res.setStyleSheet(
                    f"color:{color}; font-size:15px; font-weight:bold;")
                v.addWidget(res)
                if fade_results:
                    fade_in(res, 420)
            self.players_row.addWidget(box)
        self.players_row.addStretch()

        # ボタン制御: 自分が未選択のときだけ有効
        me = state["players"].get(str(self.my_id))
        need_choice = (phase == "playing" and me is not None
                       and me["status"] == "playing" and not me["chosen"])
        self.hit_btn.setEnabled(need_choice)
        self.stand_btn.setEnabled(need_choice)
        can = self.can_control(state)
        # 公開演出中は次ラウンドを開始できない
        self.start_btn.setEnabled(
            can and phase != "playing" and not self._revealing)
        self.start_btn.setText(
            "次のラウンド" if phase == "result" else "ラウンド開始")

        if self._revealing:
            self.statusBar().showMessage("ディーラーのカードを公開中...")
        elif phase == "result":
            if me and me["result"]:
                self.statusBar().showMessage(f"ラウンド終了: あなたは {me['result']}")
        elif need_choice:
            self.statusBar().showMessage(
                "ヒットかスタンドを選んでください (全員揃うと一括で進みます)")
        elif phase == "playing":
            waiting = [q["name"] for q in state["players"].values()
                       if q["status"] == "playing" and not q["chosen"]]
            self.statusBar().showMessage(
                "選択待ち: " + "、".join(waiting) if waiting else "処理中...")


# 旧名との互換用エイリアス
MainWindow = BlackjackWindow


def main():
    app = QApplication(sys.argv)
    win = BlackjackWindow()
    win.show()
    win.open_connect_dialog()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
