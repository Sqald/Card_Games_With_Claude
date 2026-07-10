#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""マルチプレイ・マネーホイール / Big Six (PySide6)

54区画のホイールにシンボル (1/2/5/10/20/JOKER/LOGO) が並び、
賭けたシンボルで止まれば額面の倍率で配当。全員同時ベット →
ホイールが減速しながら回転して停止する演出付き。
"""

import math
import sys

from PySide6.QtCore import (
    QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QWidget

# common/betting を先に import することで shared パッケージへのパスが通る
from betting import BettingWindowBase
from common import clear_layout
from shared.engines.money_wheel import (
    MoneyWheelEngine, SEGMENTS, SYMBOL_COLOR, SYMBOL_DISP,
)
# ---------------------------------------------------------------- ホイール描画

class PrizeWheelWidget(QWidget):
    """54区画のマネーホイール (ルーレットと同じ減速スピン演出)。"""

    SECTOR = 360.0 / len(SEGMENTS)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(230, 230)
        self.rot = 0.0
        self.center_text = "-"
        self.center_color = "#555"
        self._anim = None
        self._idle = QTimer(self)
        self._idle.timeout.connect(self._idle_step)

    def set_idle(self, on):
        if on and not self._idle.isActive():
            self._idle.start(33)
        elif not on:
            self._idle.stop()

    def _idle_step(self):
        self.rot = (self.rot + 0.4) % 360
        self.update()

    def set_center(self, text, color):
        self.center_text = text
        self.center_color = color
        self.update()

    def _target_rot(self, index):
        return (-(index * self.SECTOR + self.SECTOR / 2)) % 360

    def show_index(self, index):
        self.stop_spin()
        self.set_idle(False)
        self.rot = self._target_rot(index)
        sym = SEGMENTS[index]
        self.set_center(SYMBOL_DISP.get(sym, sym), SYMBOL_COLOR[sym])

    def spin_to(self, index, on_finished=None, duration=4200):
        self.set_idle(False)
        self.stop_spin()
        self.set_center("?", "#555")
        start = self.rot % 360
        end = self._target_rot(index) + 360 * 5
        while end - start < 360 * 4:
            end += 360
        anim = QVariantAnimation(self)
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.setDuration(duration)
        anim.setEasingCurve(QEasingCurve.Type.OutQuart)
        anim.valueChanged.connect(self._on_anim_value)

        def _finished():
            self.rot = end % 360
            sym = SEGMENTS[index]
            self.set_center(SYMBOL_DISP.get(sym, sym), SYMBOL_COLOR[sym])
            self._anim = None
            if on_finished:
                on_finished()

        anim.finished.connect(_finished)
        self._anim = anim
        anim.start()

    def _on_anim_value(self, v):
        self.rot = float(v) % 360
        self.update()

    def stop_spin(self):
        if self._anim:
            self._anim.blockSignals(True)
            self._anim.stop()
            self._anim = None

    def paintEvent(self, _event):
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        center = QPointF(cx, cy)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        outer = QRectF(4, 4, w - 8, h - 8)
        p.setBrush(QColor("#3b2b18"))
        p.setPen(QPen(QColor("#d9b64c"), 3))
        p.drawEllipse(outer)

        sector_rect = QRectF(12, 12, w - 24, h - 24)
        radius = (w - 24) / 2.0
        num_font = QFont()
        num_font.setPointSize(6)
        num_font.setBold(True)
        for i, sym in enumerate(SEGMENTS):
            start_qt = 90 - (i * self.SECTOR + self.rot)
            path = QPainterPath()
            path.moveTo(center)
            path.arcTo(sector_rect, start_qt, -self.SECTOR)
            path.closeSubpath()
            p.setPen(QPen(QColor("#d9b64c"), 0.5))
            p.setBrush(QColor(SYMBOL_COLOR[sym]))
            p.drawPath(path)
            phi = (i * self.SECTOR + self.SECTOR / 2 + self.rot) % 360
            rad = math.radians(phi)
            tr = radius * 0.85
            pt = QPointF(cx + tr * math.sin(rad), cy - tr * math.cos(rad))
            p.save()
            p.translate(pt)
            p.rotate(phi)
            p.setPen(QColor("white"))
            p.setFont(num_font)
            p.drawText(QRectF(-11, -6, 22, 12),
                       Qt.AlignmentFlag.AlignCenter,
                       SYMBOL_DISP.get(sym, sym))
            p.restore()

        hub_r = radius * 0.42
        p.setBrush(QColor(self.center_color))
        p.setPen(QPen(QColor("#d9b64c"), 2.5))
        p.drawEllipse(center, hub_r, hub_r)
        hub_font = QFont()
        hub_font.setPointSize(16)
        hub_font.setBold(True)
        p.setPen(QColor("white"))
        p.setFont(hub_font)
        p.drawText(QRectF(cx - hub_r, cy - hub_r, hub_r * 2, hub_r * 2),
                   Qt.AlignmentFlag.AlignCenter, self.center_text)

        tri = QPolygonF([QPointF(cx - 9, 1), QPointF(cx + 9, 1),
                         QPointF(cx, 22)])
        p.setBrush(QColor("#ffd54f"))
        p.setPen(QPen(QColor("#8a6d1a"), 1.5))
        p.drawPolygon(tri)


# ---------------------------------------------------------------- ウィンドウ

class MoneyWheelWindow(BettingWindowBase):
    DEFAULT_PORT = 35562
    GAME_TITLE = "マネーホイール"
    GAME_KEY = "wheel"
    BOARD_TITLE = "マネーホイール (Big Six)"
    TABLE_BG = "#33261c"
    BET_TYPES = [
        ("1", "1 (配当1倍 / 24区画)", False, 0, 0),
        ("2", "2 (配当2倍 / 15区画)", False, 0, 0),
        ("5", "5 (配当5倍 / 7区画)", False, 0, 0),
        ("10", "10 (配当10倍 / 4区画)", False, 0, 0),
        ("20", "20 (配当20倍 / 2区画)", False, 0, 0),
        ("JOKER", "JOKER (配当40倍 / 1区画)", False, 0, 0),
        ("LOGO", "LOGO★ (配当40倍 / 1区画)", False, 0, 0),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("マルチプレイ・マネーホイール")
        self.resize(1000, 800)

    def build_board(self, layout):
        row = QHBoxLayout()
        row.addStretch()
        self.wheel = PrizeWheelWidget()
        row.addWidget(self.wheel)
        row.addStretch()
        layout.addLayout(row)
        hist_row = QHBoxLayout()
        hist_row.addStretch()
        hl = QLabel("履歴:")
        hl.setStyleSheet("color:#c9b8a9; font-size:12px;")
        hist_row.addWidget(hl)
        self.history_row = QHBoxLayout()
        hist_row.addLayout(self.history_row)
        hist_row.addStretch()
        layout.addLayout(hist_row)

    def reset_board(self):
        self.wheel.stop_spin()
        self.wheel.set_idle(False)
        self.wheel.set_center("-", "#555")
        clear_layout(self.history_row)

    def start_result_animation(self, state, on_done):
        if state.get("index") is None:
            return False
        self.wheel.spin_to(state["index"], on_finished=on_done)
        return True

    def render_board(self, state, spinning):
        if spinning:
            return
        phase = state["phase"]
        if phase == "result" and state.get("index") is not None:
            self.wheel.show_index(state["index"])
        elif phase == "betting":
            self.wheel.set_center("?", "#555")
            self.wheel.set_idle(True)
        else:
            self.wheel.set_idle(False)
            self.wheel.set_center("-", "#555")
        clear_layout(self.history_row)
        for sym in state.get("history", []):
            lbl = QLabel(SYMBOL_DISP.get(sym, sym))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedSize(26, 26)
            lbl.setStyleSheet(
                f"background:{SYMBOL_COLOR[sym]}; color:white;"
                "border-radius:13px; font-size:10px; font-weight:bold;")
            self.history_row.addWidget(lbl)

    def create_engine(self):
        return MoneyWheelEngine()


def main():
    app = QApplication(sys.argv)
    win = MoneyWheelWindow()
    win.show()
    win.open_connect_dialog()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
