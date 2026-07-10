#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カジノゲーム・ランチャー

起動するとメニュー画面を表示し、遊ぶゲームを選択できる。
ゲームウィンドウを閉じるとメニューに戻る。
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from baccarat import BaccaratWindow
from blackjack import BlackjackWindow
from color_numbers import ColorNumbersWindow
from craps import CrapsWindow
from holdem import HoldemWindow
from money_wheel import MoneyWheelWindow
from roulette import RouletteWindow
from sicbo import SicBoWindow
from slots import SlotsWindow

GAMES = [
    ("ブラックジャック", BlackjackWindow),
    ("テキサスホールデム", HoldemWindow),
    ("ルーレット", RouletteWindow),
    ("バカラ", BaccaratWindow),
    ("クラップス", CrapsWindow),
    ("シックボー (大小)", SicBoWindow),
    ("マネーホイール", MoneyWheelWindow),
    ("スロット", SlotsWindow),
    ("Color && Numbers", ColorNumbersWindow),
]


class MenuWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("カジノゲーム")
        self.setFixedSize(560, 480)
        self.setStyleSheet("QWidget { background:#1b3a2a; }")
        self._game = None

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 24, 30, 24)
        root.setSpacing(14)

        title = QLabel("♠ カジノゲーム ♥")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "color:#ffe082; font-size:26px; font-weight:bold;"
            "background:transparent;")
        root.addWidget(title)
        sub = QLabel("マルチプレイ対応 - ホスト / クライアント / 専用サーバ")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(
            "color:#9fc9ad; font-size:13px; background:transparent;")
        root.addWidget(sub)
        root.addSpacing(6)

        btn_style = (
            "QPushButton { font-size:14px; font-weight:bold; color:white;"
            " background:#2e7d4f; border:2px solid #5cae7f;"
            " border-radius:8px; padding:11px; }"
            "QPushButton:hover { background:#389660; }")
        quit_style = btn_style.replace("#2e7d4f", "#7d2e2e").replace(
            "#5cae7f", "#ae5c5c").replace("#389660", "#963838")

        grid = QGridLayout()
        grid.setSpacing(12)
        for i, (label, win_cls) in enumerate(GAMES):
            btn = QPushButton(label)
            btn.setStyleSheet(btn_style)
            btn.clicked.connect(
                lambda _, cls=win_cls: self._open_game(cls))
            grid.addWidget(btn, i // 2, i % 2)
        root.addLayout(grid)

        quit_btn = QPushButton("アプリを閉じる")
        quit_btn.setStyleSheet(quit_style)
        quit_btn.clicked.connect(QApplication.quit)
        root.addWidget(quit_btn)
        root.addStretch()

    def _open_game(self, win_cls):
        game = win_cls()
        game.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        game.destroyed.connect(self._on_game_closed)
        self._game = game
        self.hide()
        game.show()
        game.open_connect_dialog()

    def _on_game_closed(self):
        self._game = None
        self.show()

    def closeEvent(self, event):
        super().closeEvent(event)
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    # ゲーム中はメニューを隠すため、最後のウィンドウが閉じても自動終了しない
    app.setQuitOnLastWindowClosed(False)
    menu = MenuWindow()
    menu.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
