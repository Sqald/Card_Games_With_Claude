#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""マルチプレイ・シックボー / 大小 (PySide6)

3個のダイスに全員同時ベット → ダイス演出 → 一括精算のワンロールゲーム。
大・小 (トリプルで負け) / 合計値 / エニートリプル / シングル数字に対応。
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel

# common/betting を先に import することで shared パッケージへのパスが通る
from betting import BettingWindowBase, DiceRowWidget
from common import clear_layout
from shared.engines.sicbo import SicBoEngine


# ---------------------------------------------------------------- ウィンドウ

class SicBoWindow(BettingWindowBase):
    DEFAULT_PORT = 35561
    GAME_TITLE = "シックボー"
    GAME_KEY = "sicbo"
    BOARD_TITLE = "シックボー (大小)"
    TABLE_BG = "#4a2b3d"
    NUMBER_LABEL = "数字:"
    BET_TYPES = [
        ("big", "大 11-17 (配当1倍 / トリプルで負け)", False, 0, 0),
        ("small", "小 4-10 (配当1倍 / トリプルで負け)", False, 0, 0),
        ("total", "合計値 (4-17 / 配当6〜60倍)", True, 4, 17),
        ("triple", "エニートリプル (配当30倍)", False, 0, 0),
        ("single", "シングル数字 (出た個数×1倍)", True, 1, 6),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("マルチプレイ・シックボー")
        self.resize(1000, 760)

    def build_board(self, layout):
        row = QHBoxLayout()
        row.addStretch()
        self.dice_widget = DiceRowWidget(3, size=64)
        row.addWidget(self.dice_widget)
        row.addStretch()
        layout.addLayout(row)
        hist_row = QHBoxLayout()
        hist_row.addStretch()
        hl = QLabel("履歴:")
        hl.setStyleSheet("color:#cbaebf; font-size:12px;")
        hist_row.addWidget(hl)
        self.history_row = QHBoxLayout()
        hist_row.addLayout(self.history_row)
        hist_row.addStretch()
        layout.addLayout(hist_row)

    def reset_board(self):
        self.dice_widget.show_values([1, 1, 1])
        clear_layout(self.history_row)

    def start_result_animation(self, state, on_done):
        if not state.get("dice"):
            return False
        self.dice_widget.roll_to(state["dice"], on_finished=on_done)
        return True

    def render_board(self, state, spinning):
        if spinning:
            return
        if state.get("dice") and not self.dice_widget.is_rolling():
            self.dice_widget.show_values(state["dice"])
        clear_layout(self.history_row)
        for n in state.get("history", []):
            lbl = QLabel(str(n))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedSize(24, 24)
            bg = "#c0392b" if n >= 11 else "#2980b9"
            lbl.setStyleSheet(
                f"background:{bg}; color:white; border-radius:12px;"
                "font-size:11px; font-weight:bold;")
            self.history_row.addWidget(lbl)

    def create_engine(self):
        return SicBoEngine()


def main():
    app = QApplication(sys.argv)
    win = SicBoWindow()
    win.show()
    win.open_connect_dialog()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
