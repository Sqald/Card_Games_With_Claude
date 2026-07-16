#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カジノゲーム・ランチャー

起動するとメニュー画面を表示し、遊ぶゲームを選択できる。
ゲームウィンドウを閉じるとメニューに戻る。
"""

import importlib
import sys

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QLabel, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

# ゲームモジュールの import は重いので、起動時には読み込まず、
# メニューで選択されたゲームだけをその場で読み込む。
GAMES = [
    ("ブラックジャック", "blackjack", "BlackjackWindow"),
    ("テキサスホールデム", "holdem", "HoldemWindow"),
    ("ルーレット", "roulette", "RouletteWindow"),
    ("バカラ", "baccarat", "BaccaratWindow"),
    ("クラップス", "craps", "CrapsWindow"),
    ("シックボー (大小)", "sicbo", "SicBoWindow"),
    ("マネーホイール", "money_wheel", "MoneyWheelWindow"),
    ("スロット", "slots", "SlotsWindow"),
    ("Color && Numbers", "color_numbers", "ColorNumbersWindow"),
]


class _ImportThread(QThread):
    """import 中にUIが固まらないよう、別スレッドでモジュールを読み込む。"""

    done = Signal(object, object)  # (module, error)

    def __init__(self, mod_name, parent=None):
        super().__init__(parent)
        self._mod_name = mod_name

    def run(self):
        try:
            module = importlib.import_module(self._mod_name)
        except Exception as exc:
            self.done.emit(None, exc)
        else:
            self.done.emit(module, None)


class MenuWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("カジノゲーム")
        self.setFixedSize(560, 480)
        self.setStyleSheet("QWidget { background:#1b3a2a; }")
        self._game = None
        self._window_cache = {}  # mod_name -> ウィンドウクラス
        self._import_thread = None
        self._buttons = []

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
            "QPushButton:hover { background:#389660; }"
            "QPushButton:disabled { background:#24503a; color:#88a894;"
            " border-color:#3c6e52; }")
        quit_style = btn_style.replace("#2e7d4f", "#7d2e2e").replace(
            "#5cae7f", "#ae5c5c").replace("#389660", "#963838")

        grid = QGridLayout()
        grid.setSpacing(12)
        for i, (label, mod_name, cls_name) in enumerate(GAMES):
            btn = QPushButton(label)
            btn.setStyleSheet(btn_style)
            btn.clicked.connect(
                lambda _, g=(label, mod_name, cls_name):
                    self._open_game(*g))
            self._buttons.append(btn)
            grid.addWidget(btn, i // 2, i % 2)
        root.addLayout(grid)

        quit_btn = QPushButton("アプリを閉じる")
        quit_btn.setStyleSheet(quit_style)
        quit_btn.clicked.connect(QApplication.quit)
        root.addWidget(quit_btn)

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(
            "color:#ffe082; font-size:12px; background:transparent;")
        root.addWidget(self._status)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(12)
        self._bar.setStyleSheet(
            "QProgressBar { background:#143020; border:1px solid #5cae7f;"
            " border-radius:6px; }"
            "QProgressBar::chunk { background:#ffe082; border-radius:5px; }")
        self._bar.hide()
        root.addWidget(self._bar)
        root.addStretch()

        # import の進捗率は取れないため、完了までバーを疑似的に進める
        self._bar_timer = QTimer(self)
        self._bar_timer.setInterval(50)
        self._bar_timer.timeout.connect(self._advance_bar)

    def _advance_bar(self):
        value = self._bar.value()
        if value < 90:
            self._bar.setValue(value + max(1, (90 - value) // 8))

    def _start_bar(self):
        self._bar.setValue(0)
        self._bar.show()
        self._bar_timer.start()

    def _finish_bar(self, ok):
        self._bar_timer.stop()
        if ok:
            self._bar.setValue(100)
            QTimer.singleShot(150, self._bar.hide)
        else:
            self._bar.hide()

    def _set_buttons_enabled(self, enabled):
        for btn in self._buttons:
            btn.setEnabled(enabled)

    def _open_game(self, label, mod_name, cls_name):
        win_cls = self._window_cache.get(mod_name)
        if win_cls is not None:
            self._launch(win_cls)
            return
        # 初回選択時のみ読み込む。別スレッドなのでUIは固まらない
        self._set_buttons_enabled(False)
        self._status.setText(f"{label} を読み込んでいます…")
        self._start_bar()
        thread = _ImportThread(mod_name, self)
        thread.done.connect(
            lambda module, error: self._on_import_done(
                label, mod_name, cls_name, module, error))
        thread.finished.connect(thread.deleteLater)
        self._import_thread = thread
        thread.start()

    def _on_import_done(self, label, mod_name, cls_name, module, error):
        self._import_thread = None
        self._set_buttons_enabled(True)
        self._finish_bar(ok=error is None)
        if error is not None:
            self._status.setText(f"{label} の読み込みに失敗しました: {error}")
            return
        self._status.setText("")
        win_cls = getattr(module, cls_name)
        self._window_cache[mod_name] = win_cls
        self._launch(win_cls)

    def _launch(self, win_cls):
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
