#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""マルチプレイ・バカラ (PySide6)

プレイヤー / バンカー / タイ / ペアに全員同時にベットし、
締切後にカードが1枚ずつめくられる。サードカードは標準ルールで自動処理。
配当: プレイヤー1倍 / バンカー0.95倍 / タイ8倍 / ペア11倍。
"""

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout,
)

# common/betting を先に import することで shared パッケージへのパスが通る
from betting import BettingWindowBase
from common import clear_layout, fade_in, make_card_label
from shared.engines.baccarat import BaccaratEngine, hand_total


# ---------------------------------------------------------------- ウィンドウ

HIST_COLOR = {"P": "#2980b9", "B": "#c0392b", "T": "#27ae60"}


class BaccaratWindow(BettingWindowBase):
    DEFAULT_PORT = 35559
    GAME_TITLE = "バカラ"
    GAME_KEY = "baccarat"
    BOARD_TITLE = "バカラ"
    TABLE_BG = "#20343f"
    BET_TYPES = [
        ("player", "プレイヤー (配当1倍)", False, 0, 0),
        ("banker", "バンカー (配当0.95倍)", False, 0, 0),
        ("tie", "タイ (配当8倍)", False, 0, 0),
        ("ppair", "プレイヤーペア (配当11倍)", False, 0, 0),
        ("bpair", "バンカーペア (配当11倍)", False, 0, 0),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("マルチプレイ・バカラ")
        self.resize(1000, 760)
        self._reveal_timer = QTimer(self)
        self._reveal_timer.timeout.connect(self._reveal_step)
        self._reveal_state = None
        self._reveal_n = 0
        self._reveal_done_cb = None

    # ---- 盤面

    def build_board(self, layout):
        row = QHBoxLayout()
        row.addStretch()

        self.p_box = QGroupBox("PLAYER")
        self.p_box.setStyleSheet(
            "QGroupBox { color:#7ec8ff; font-weight:bold; }")
        pv = QVBoxLayout(self.p_box)
        self.p_cards_row = QHBoxLayout()
        pv.addLayout(self.p_cards_row)
        self.p_total_label = QLabel(" ")
        self.p_total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.p_total_label.setStyleSheet(
            "color:#7ec8ff; font-size:18px; font-weight:bold;")
        pv.addWidget(self.p_total_label)
        row.addWidget(self.p_box)

        vs = QLabel("VS")
        vs.setStyleSheet("color:#ffe082; font-size:22px; font-weight:bold;")
        row.addSpacing(18)
        row.addWidget(vs)
        row.addSpacing(18)

        self.b_box = QGroupBox("BANKER")
        self.b_box.setStyleSheet(
            "QGroupBox { color:#ff9e9e; font-weight:bold; }")
        bv2 = QVBoxLayout(self.b_box)
        self.b_cards_row = QHBoxLayout()
        bv2.addLayout(self.b_cards_row)
        self.b_total_label = QLabel(" ")
        self.b_total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.b_total_label.setStyleSheet(
            "color:#ff9e9e; font-size:18px; font-weight:bold;")
        bv2.addWidget(self.b_total_label)
        row.addWidget(self.b_box)
        row.addStretch()
        layout.addLayout(row)

        hist_row = QHBoxLayout()
        hist_row.addStretch()
        hl = QLabel("履歴:")
        hl.setStyleSheet("color:#9fb8c9; font-size:12px;")
        hist_row.addWidget(hl)
        self.history_row = QHBoxLayout()
        hist_row.addLayout(self.history_row)
        hist_row.addStretch()
        layout.addLayout(hist_row)

    def reset_board(self):
        self._reveal_timer.stop()
        self._reveal_state = None
        clear_layout(self.p_cards_row)
        clear_layout(self.b_cards_row)
        clear_layout(self.history_row)
        self.p_total_label.setText(" ")
        self.b_total_label.setText(" ")

    def _draw_side(self, cards_row, total_label, cards, shown, color,
                   fade_index=None):
        clear_layout(cards_row)
        cards_row.addStretch()
        for i, card in enumerate(cards):
            lbl = make_card_label(card if i < shown else ("?", "?"))
            cards_row.addWidget(lbl)
            if i == fade_index:
                fade_in(lbl, 300)   # めくられた瞬間のカードを演出
        cards_row.addStretch()
        revealed = cards[:shown]
        total_label.setText(
            f"合計: {hand_total(revealed)}" if revealed else " ")

    def _reveal_sequence(self, state):
        """(side, そのサイドの公開枚数) の列。P,B交互 → 3枚目。"""
        seq = [("p", 1), ("b", 1), ("p", 2), ("b", 2)]
        if len(state["p_cards"]) > 2:
            seq.append(("p", 3))
        if len(state["b_cards"]) > 2:
            seq.append(("b", 3))
        return seq

    def start_result_animation(self, state, on_done):
        if not state.get("p_cards"):
            return False
        self._reveal_state = state
        self._reveal_n = 0
        self._reveal_done_cb = on_done
        self._paint_reveal()
        self._reveal_timer.start(650)
        return True

    def _reveal_step(self):
        self._reveal_n += 1
        st = self._reveal_state
        if self._reveal_n >= len(self._reveal_sequence(st)):
            self._reveal_timer.stop()
            self._reveal_state = None
            cb, self._reveal_done_cb = self._reveal_done_cb, None
            if cb:
                cb()
            return
        self._paint_reveal()

    def _paint_reveal(self):
        st = self._reveal_state
        seq = self._reveal_sequence(st)[:self._reveal_n + 1]
        p_shown = max([n for s, n in seq if s == "p"], default=0)
        b_shown = max([n for s, n in seq if s == "b"], default=0)
        side, cnt = seq[-1]   # 今めくられたカードだけフェードイン
        self._draw_side(self.p_cards_row, self.p_total_label,
                        st["p_cards"], p_shown, "#7ec8ff",
                        fade_index=cnt - 1 if side == "p" else None)
        self._draw_side(self.b_cards_row, self.b_total_label,
                        st["b_cards"], b_shown, "#ff9e9e",
                        fade_index=cnt - 1 if side == "b" else None)

    def render_board(self, state, spinning):
        if spinning:
            return   # 公開演出はタイマーが盤面を更新する
        self._draw_side(self.p_cards_row, self.p_total_label,
                        state.get("p_cards") or [], 9, "#7ec8ff")
        self._draw_side(self.b_cards_row, self.b_total_label,
                        state.get("b_cards") or [], 9, "#ff9e9e")
        # 勝者側を金枠で強調
        for box, side in ((self.p_box, "player"), (self.b_box, "banker")):
            color = "#7ec8ff" if side == "player" else "#ff9e9e"
            border = ("#ffd54f" if state.get("winner") in (side, "tie")
                      and state["phase"] == "result" else "#557")
            box.setStyleSheet(
                f"QGroupBox {{ color:{color}; font-weight:bold;"
                f" border:2px solid {border}; border-radius:8px;"
                f" margin-top:8px; }}"
                f"QGroupBox::title {{ subcontrol-origin: margin; left:8px; }}")
        clear_layout(self.history_row)
        for h in state.get("history", []):
            lbl = QLabel(h)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedSize(24, 24)
            lbl.setStyleSheet(
                f"background:{HIST_COLOR[h]}; color:white;"
                "border-radius:12px; font-size:12px; font-weight:bold;")
            self.history_row.addWidget(lbl)

    def create_engine(self):
        return BaccaratEngine()


def main():
    app = QApplication(sys.argv)
    win = BaccaratWindow()
    win.show()
    win.open_connect_dialog()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
