#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""マルチプレイ・スロット (PySide6)

ラウンドや順番の概念がなく、各プレイヤーが好きなタイミングで
スピンできる (1回 50 チップ)。全員のリールと当たりが全員の画面に
リアルタイム表示され、リールは順番に止まる演出付き。
"""

import random
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QTextEdit, QVBoxLayout, QWidget,
)

# common を最初に import することで shared パッケージへのパスが通る
from common import GameWindowBase, fade_in
from shared.engines.slots import BET, PAYTABLE_TEXT, REEL, SlotsEngine

PANEL_STYLE = (
    "QGroupBox { color:white; font-weight:bold;"
    " border:2px solid #a685b3; border-radius:8px;"
    " margin-top:8px; padding-top:4px; }"
    "QGroupBox::title { subcontrol-origin: margin; left:8px; }")
# 大当たり時に一時的に金枠でフラッシュさせる
PANEL_FLASH_STYLE = PANEL_STYLE.replace("#a685b3", "#ffd54f")

# ---------------------------------------------------------------- ウィンドウ

class SlotsWindow(GameWindowBase):
    DEFAULT_PORT = 35563
    GAME_TITLE = "スロット"
    GAME_KEY = "slots"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("マルチプレイ・スロット")
        self.resize(1000, 700)
        self.statusBar().showMessage("メニューの「ゲーム > 接続設定」から開始してください")
        self.panels = {}   # pid -> パネル情報 (永続ウィジェット)

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("table")
        central.setStyleSheet("QWidget#table { background:#3a1f3f; }")
        root = QVBoxLayout(central)

        board_box = QGroupBox("スロットフロア")
        board_box.setStyleSheet("QGroupBox { color:white; font-weight:bold; }")
        bv = QVBoxLayout(board_box)
        pay = QLabel(PAYTABLE_TEXT)
        pay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pay.setStyleSheet("color:#d9c3e0; font-size:12px;")
        bv.addWidget(pay)
        self.message_label = QLabel("")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setStyleSheet(
            "color:#ffe082; font-size:16px; font-weight:bold;")
        bv.addWidget(self.message_label)
        root.addWidget(board_box)

        self.players_row = QHBoxLayout()
        self.players_row.addStretch()
        holder = QWidget()
        holder.setLayout(self.players_row)
        holder.setStyleSheet("background:transparent;")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        scroll.setStyleSheet("QScrollArea { background:transparent; border:none; }")
        root.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.spin_btn = QPushButton(f"スピン (BET {BET})")
        self.spin_btn.setMinimumHeight(48)
        self.spin_btn.setStyleSheet(
            "font-size:17px; font-weight:bold; padding:0 30px;")
        self.spin_btn.setEnabled(False)
        self.spin_btn.clicked.connect(
            lambda: self.submit_action({"type": "action", "action": "spin"}))
        btn_row.addWidget(self.spin_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(90)
        root.addWidget(self.log_view)

        self.setCentralWidget(central)

    # ---- 基底フック

    def create_engine(self):
        return SlotsEngine()

    def handle_action(self, pid, msg):
        return self.engine.act(pid, msg.get("action", ""))

    def reset_game_ui(self):
        for panel in self.panels.values():
            panel["timer"].stop()
            panel["box"].hide()
            panel["box"].setParent(None)
            panel["box"].deleteLater()
        self.panels = {}
        self.spin_btn.setEnabled(False)
        self.message_label.setText("")

    # ---- パネル管理

    def _make_panel(self, pid):
        box = QGroupBox()
        box.setStyleSheet(PANEL_STYLE)
        v = QVBoxLayout(box)
        reels_row = QHBoxLayout()
        reels_row.addStretch()
        reels = []
        for _ in range(3):
            lbl = QLabel("—")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedSize(58, 58)
            lbl.setStyleSheet(
                "background:white; color:#333; border:2px solid #888;"
                "border-radius:6px; font-size:22px; font-weight:bold;")
            reels.append(lbl)
            reels_row.addWidget(lbl)
        reels_row.addStretch()
        v.addLayout(reels_row)
        chips = QLabel("")
        chips.setStyleSheet("color:#e8d9ee; font-size:13px;")
        chips.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(chips)
        win = QLabel(" ")
        win.setStyleSheet("color:#8ef58e; font-size:15px; font-weight:bold;")
        win.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(win)
        timer = QTimer(self)
        panel = {"box": box, "reels": reels, "chips": chips, "win": win,
                 "timer": timer, "seq": 0, "steps": 0, "final": None}
        timer.timeout.connect(lambda pid=pid: self._anim_step(pid))
        # 末尾の stretch の前に挿入
        self.players_row.insertWidget(self.players_row.count() - 1, box)
        return panel

    def _start_anim(self, pid, symbols, win, chips):
        panel = self.panels[pid]
        panel["final"] = (list(symbols), win, chips)
        panel["steps"] = 0
        panel["win"].setText(" ")
        panel["timer"].start(80)

    def _anim_step(self, pid):
        panel = self.panels.get(pid)
        if not panel or not panel["final"]:
            return
        panel["steps"] += 1
        symbols, win, chips = panel["final"]
        done = 0
        for i, lbl in enumerate(panel["reels"]):
            stop_at = 8 + i * 5   # リールが順番に止まる
            if panel["steps"] >= stop_at:
                lbl.setText(symbols[i])
                done += 1
            else:
                lbl.setText(random.choice(REEL))
        if done == 3:
            panel["timer"].stop()
            panel["final"] = None
            panel["chips"].setText(f"チップ: {chips}")
            if win > 0:
                panel["win"].setText(f"WIN +{win}")
                panel["win"].setStyleSheet(
                    "color:#8ef58e; font-size:15px; font-weight:bold;")
                fade_in(panel["win"], 360)
                if win >= BET * 20:   # 大当たりはパネルを金枠でフラッシュ
                    panel["box"].setStyleSheet(PANEL_FLASH_STYLE)
                    QTimer.singleShot(
                        1600, lambda pid=pid: self._unflash_panel(pid))
            else:
                panel["win"].setText(f"はずれ -{BET}")
                panel["win"].setStyleSheet(
                    "color:#caa; font-size:13px;")

    def _unflash_panel(self, pid):
        panel = self.panels.get(pid)
        if panel:
            panel["box"].setStyleSheet(PANEL_STYLE)

    # ---- 状態描画

    def render_state(self, state):
        players = state["players"]
        order = state["order"]

        for pid in list(self.panels):
            if pid not in order:
                panel = self.panels.pop(pid)
                panel["timer"].stop()
                panel["box"].hide()
                panel["box"].setParent(None)
                panel["box"].deleteLater()

        for pid in order:
            p = players[str(pid)]
            panel = self.panels.get(pid)
            if panel is None:
                panel = self._make_panel(pid)
                self.panels[pid] = panel
                if p["symbols"]:
                    for lbl, s in zip(panel["reels"], p["symbols"]):
                        lbl.setText(s)
            panel["box"].setTitle(
                p["name"] + (" (あなた)" if pid == self.my_id else ""))
            if p["seq"] > panel["seq"]:
                panel["seq"] = p["seq"]
                self._start_anim(pid, p["symbols"], p["win"], p["chips"])
                if p["win"] >= BET * 20:
                    self.log(f"🎉 {p['name']} が大当たり! +{p['win']}")
            elif panel["final"] is None:   # アニメ中はネタバレしない
                panel["chips"].setText(f"チップ: {p['chips']}")

        self.message_label.setText(state.get("message", ""))
        me = players.get(str(self.my_id))
        can_spin = (self.mode in ("host", "client") and me is not None
                    and me["chips"] >= BET)
        self.spin_btn.setEnabled(can_spin)
        if me is not None:
            if me["chips"] < BET:
                self.statusBar().showMessage("チップが足りません")
            else:
                self.statusBar().showMessage(
                    "好きなタイミングでスピンできます (順番待ちなし)")


def main():
    app = QApplication(sys.argv)
    win = SlotsWindow()
    win.show()
    win.open_connect_dialog()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
