#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""マルチプレイ・クラップス (PySide6)

ロールごとに全員同時にベット (30秒 or 全員賭け終了で締切) → ダイス演出。
パスライン / ドントパスはポイント制でラウンドをまたいで場に残る (🔒表示)。
フィールド / エニーセブン / エニークラップス / イレブンはワンロールベット。
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel

# common/betting を先に import することで shared パッケージへのパスが通る
from betting import BettingWindowBase, DiceRowWidget
from common import clear_layout
from shared.engines.craps import CrapsEngine


# ---------------------------------------------------------------- ウィンドウ

class CrapsWindow(BettingWindowBase):
    DEFAULT_PORT = 35560
    GAME_TITLE = "クラップス"
    GAME_KEY = "craps"
    BOARD_TITLE = "クラップス"
    TABLE_BG = "#274e2b"
    START_LABEL = "ロール開始"
    NEXT_LABEL = "次のロール"
    BET_TYPES = [
        ("pass", "パスライン (配当1倍)", False, 0, 0),
        ("dp", "ドントパス (配当1倍)", False, 0, 0),
        ("field", "フィールド (2は2倍/12は3倍)", False, 0, 0),
        ("any7", "エニーセブン (配当4倍)", False, 0, 0),
        ("anycraps", "エニークラップス (配当7倍)", False, 0, 0),
        ("eleven", "イレブン (配当15倍)", False, 0, 0),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("マルチプレイ・クラップス")
        self.resize(1000, 760)

    def build_board(self, layout):
        row = QHBoxLayout()
        row.addStretch()
        self.dice_widget = DiceRowWidget(2, size=68)
        row.addWidget(self.dice_widget)
        row.addStretch()
        layout.addLayout(row)
        self.point_label = QLabel("")
        self.point_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.point_label.setStyleSheet(
            "color:#ffd54f; font-size:17px; font-weight:bold;")
        layout.addWidget(self.point_label)
        hist_row = QHBoxLayout()
        hist_row.addStretch()
        hl = QLabel("履歴:")
        hl.setStyleSheet("color:#a9c9ad; font-size:12px;")
        hist_row.addWidget(hl)
        self.history_row = QHBoxLayout()
        hist_row.addLayout(self.history_row)
        hist_row.addStretch()
        layout.addLayout(hist_row)

    def reset_board(self):
        self.dice_widget.show_values([1, 1])
        self.point_label.setText("")
        clear_layout(self.history_row)

    def start_result_animation(self, state, on_done):
        if not state.get("dice"):
            return False
        self.dice_widget.roll_to(state["dice"], on_finished=on_done)
        return True

    def render_board(self, state, spinning):
        if spinning:
            self.point_label.setText("ロール中…")
            return
        if state.get("dice") and not self.dice_widget.is_rolling():
            self.dice_widget.show_values(state["dice"])
        point = state.get("point")
        self.point_label.setText(
            f"ポイント: {point}" if point else "カムアウトロール")
        clear_layout(self.history_row)
        for n in state.get("history", []):
            lbl = QLabel(str(n))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedSize(24, 24)
            bg = "#c0392b" if n == 7 else "#2c3e50"
            lbl.setStyleSheet(
                f"background:{bg}; color:white; border-radius:12px;"
                "font-size:11px; font-weight:bold;")
            self.history_row.addWidget(lbl)

    def create_engine(self):
        return CrapsEngine()


def main():
    app = QApplication(sys.argv)
    win = CrapsWindow()
    win.show()
    win.open_connect_dialog()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
