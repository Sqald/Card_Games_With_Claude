#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""マルチプレイ・カジノルーレット (PySide6)

ホストモード : 全IP(0.0.0.0)で指定ポートをLISTENし、自身もプレイヤーとして参加。
クライアントモード : ホストのIPアドレスとポートを指定して接続。

ヨーロピアン式 (0-36)。ベットはターン制ではなく全員同時受付で、
全員が「賭け終了」を押すか、制限時間 (60秒) が経過するとスピンする。
ベットは実際のカジノと同じレイアウトのテーブルにチップを置いて行う
(チップ額を選んでセルをクリック)。
"""

import copy
import math
import sys

from PySide6.QtCore import (
    QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

# common を最初に import することで shared パッケージへのパスが通る
from common import GameWindowBase, clear_layout, fade_in
from shared.engines.roulette import (
    BETTING_TIME, COLOR_CSS, RouletteEngine, WHEEL_ORDER, color_of,
)

# チップの額面と色 (実カジノ風)
CHIP_VALUES = [10, 50, 100, 500]
CHIP_COLORS = {10: "#7f8c8d", 50: "#c0392b", 100: "#2980b9", 500: "#8e44ad"}


def chip_button_style(value):
    return (
        f"QPushButton {{ background:{CHIP_COLORS[value]}; color:white;"
        " border:3px dashed #e0e0e0; border-radius:23px;"
        " font-size:13px; font-weight:bold; }"
        "QPushButton:checked { border:3px solid #ffd54f; }"
        "QPushButton:disabled { background:#555; color:#999;"
        " border:3px dashed #777; }")


# ---------------------------------------------------------------- ベットテーブル

class BetTableWidget(QWidget):
    """実際のカジノと同じルーレットのベッティングレイアウト。

    0 / 数字36マス / ダース / アウトサイド (1-18, EVEN, RED, BLACK,
    ODD, 19-36) をクリックしてベットする。自分のチップは金色、
    他プレイヤーの合計は青灰色のチップとして各セルに表示する。
    """

    bet_clicked = Signal(str, int)   # (bet_type, number)

    MARGIN = 6
    CELL_W = 46
    CELL_H = 40
    ZERO_W = 40
    OUT_H = 34
    FELT = "#14432b"
    CELL_BG = "#1b4d33"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.regions = []   # (QRectF, btype, number, ラベル, 背景色)
        self._build_regions()
        self.setFixedSize(
            self.MARGIN * 2 + self.ZERO_W + self.CELL_W * 12,
            self.MARGIN * 2 + self.CELL_H * 3 + self.OUT_H * 2)
        self.setMouseTracking(True)
        self.my_bets = {}      # (btype, number) -> 自分の合計額
        self.other_bets = {}   # (btype, number) -> 他プレイヤーの合計額
        self.winning = None
        self.betting_enabled = False
        self._hover = None

    def _build_regions(self):
        m, w, h = self.MARGIN, self.CELL_W, self.CELL_H
        x0 = m + self.ZERO_W
        # 0 (左端・3行ぶち抜き)
        self.regions.append((QRectF(m, m, self.ZERO_W, h * 3),
                             "straight", 0, "0", COLOR_CSS["green"]))
        # 数字 1-36 (実際の配置: 上段が3の倍数)
        for c in range(12):
            for r in range(3):
                num = 3 * (c + 1) - r
                self.regions.append((
                    QRectF(x0 + c * w, m + r * h, w, h),
                    "straight", num, str(num), COLOR_CSS[color_of(num)]))
        # ダース
        y1 = m + h * 3
        dozens = [("dozen1", "1st 12"), ("dozen2", "2nd 12"),
                  ("dozen3", "3rd 12")]
        for i, (bt, label) in enumerate(dozens):
            self.regions.append((QRectF(x0 + i * 4 * w, y1, 4 * w, self.OUT_H),
                                 bt, 0, label, self.CELL_BG))
        # アウトサイド
        y2 = y1 + self.OUT_H
        outs = [("low", "1-18", self.CELL_BG), ("even", "EVEN", self.CELL_BG),
                ("red", "RED", COLOR_CSS["red"]),
                ("black", "BLACK", COLOR_CSS["black"]),
                ("odd", "ODD", self.CELL_BG), ("high", "19-36", self.CELL_BG)]
        for i, (bt, label, bg) in enumerate(outs):
            self.regions.append((QRectF(x0 + i * 2 * w, y2, 2 * w, self.OUT_H),
                                 bt, 0, label, bg))

    # ---- 状態操作

    def set_bets(self, mine, others):
        self.my_bets = dict(mine)
        self.other_bets = dict(others)
        self.update()

    def set_winning(self, number):
        if self.winning != number:
            self.winning = number
            self.update()

    def set_betting_enabled(self, on):
        if self.betting_enabled != on:
            self.betting_enabled = on
            if not on:
                self._hover = None
            self.setCursor(Qt.CursorShape.PointingHandCursor if on
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    # ---- マウス操作

    def _region_at(self, pos):
        for i, (rect, *_rest) in enumerate(self.regions):
            if rect.contains(pos):
                return i
        return None

    def mouseMoveEvent(self, event):
        if not self.betting_enabled:
            return
        i = self._region_at(event.position())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, _event):
        if self._hover is not None:
            self._hover = None
            self.update()

    def mousePressEvent(self, event):
        if (not self.betting_enabled
                or event.button() != Qt.MouseButton.LeftButton):
            return
        i = self._region_at(event.position())
        if i is not None:
            _, btype, number, _, _ = self.regions[i]
            self.bet_clicked.emit(btype, number)

    # ---- 描画

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(self.FELT))
        p.setPen(QPen(QColor("#d9b64c"), 2))
        p.drawRoundedRect(
            QRectF(1, 1, self.width() - 2, self.height() - 2), 8, 8)

        font = QFont()
        font.setBold(True)
        for i, (rect, btype, number, label, bg) in enumerate(self.regions):
            color = QColor(bg)
            if not self.betting_enabled:
                color = color.darker(115)
            if i == self._hover:
                color = color.lighter(135)
            p.setBrush(color)
            p.setPen(QPen(QColor(255, 255, 255, 130), 1))
            p.drawRect(rect)
            if (self.winning is not None and btype == "straight"
                    and number == self.winning):
                # 当選番号を金枠で強調
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor("#ffd54f"), 3))
                p.drawRect(rect.adjusted(1.5, 1.5, -1.5, -1.5))
            font.setPointSize(11 if btype == "straight" else 10)
            p.setFont(font)
            p.setPen(QColor("white"))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

        # チップ (他プレイヤー → 自分の順で描き、自分のを手前にする)
        for key, amount in self.other_bets.items():
            self._draw_chip(p, key, amount, mine=False)
        for key, amount in self.my_bets.items():
            self._draw_chip(p, key, amount, mine=True)

    def _rect_for(self, key):
        btype, number = key
        for rect, bt, num, _, _ in self.regions:
            if bt == btype and (bt != "straight" or num == number):
                return rect
        return None

    def _draw_chip(self, p, key, amount, mine):
        rect = self._rect_for(key)
        if rect is None:
            return
        if mine:
            center = QPointF(rect.center().x(), rect.center().y() + 4)
            radius = 13.0
            p.setBrush(QColor("#ffd54f"))
            p.setPen(QPen(QColor("#8a6d1a"), 1.5))
            fg = "#4a3a08"
        else:
            center = QPointF(rect.left() + 12, rect.top() + 11)
            radius = 10.0
            p.setBrush(QColor("#607d8b"))
            p.setPen(QPen(QColor("#37474f"), 1.5))
            fg = "white"
        p.drawEllipse(center, radius, radius)
        font = QFont()
        font.setBold(True)
        text = str(amount)
        font.setPointSize(8 if len(text) <= 3 else 7)
        p.setFont(font)
        p.setPen(QColor(fg))
        p.drawText(QRectF(center.x() - radius, center.y() - radius,
                          radius * 2, radius * 2),
                   Qt.AlignmentFlag.AlignCenter, text)


# ---------------------------------------------------------------- ホイール描画

class WheelWidget(QWidget):
    """回転アニメーション付きのルーレットホイール。

    ポインタは上部固定。spin_to() で数減速しながら当選番号の区画が
    ポインタ位置に止まる。ベット受付中は set_idle(True) でゆっくり回る。
    """

    SECTOR = 360.0 / len(WHEEL_ORDER)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(220, 220)
        self.rot = 0.0            # 時計回りの回転角 (deg)
        self.center_text = "-"
        self.center_color = "#555"
        self._anim = None
        self._idle = QTimer(self)
        self._idle.timeout.connect(self._idle_step)

    # ---- 状態操作

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

    def _target_rot(self, number):
        """number の区画中心がポインタ (真上) に来る回転角。"""
        idx = WHEEL_ORDER.index(number)
        return (-(idx * self.SECTOR + self.SECTOR / 2)) % 360

    def show_number(self, number):
        """アニメーションなしで結果を表示 (途中参加者向け)。"""
        self.stop_spin()
        self.set_idle(False)
        self.rot = self._target_rot(number)
        self.set_center(str(number), COLOR_CSS[color_of(number)])

    def spin_to(self, number, on_finished=None, duration=4200):
        self.set_idle(False)
        self.stop_spin()
        self.set_center("?", "#555")
        start = self.rot % 360
        end = self._target_rot(number) + 360 * 5   # 5周してから停止
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
            self.set_center(str(number), COLOR_CSS[color_of(number)])
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
            self._anim.blockSignals(True)   # finished を発火させず停止
            self._anim.stop()
            self._anim = None

    def is_spinning(self):
        return self._anim is not None

    # ---- 描画

    def paintEvent(self, _event):
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        center = QPointF(cx, cy)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 外枠
        outer = QRectF(4, 4, w - 8, h - 8)
        p.setBrush(QColor("#3b2b18"))
        p.setPen(QPen(QColor("#d9b64c"), 3))
        p.drawEllipse(outer)

        # 区画
        sector_rect = QRectF(12, 12, w - 24, h - 24)
        radius = (w - 24) / 2.0
        num_font = QFont()
        num_font.setPointSize(7)
        num_font.setBold(True)
        for i, num in enumerate(WHEEL_ORDER):
            # 区画 i は「上から時計回りに i*SECTOR〜(i+1)*SECTOR + rot」を占める
            start_qt = 90 - (i * self.SECTOR + self.rot)
            path = QPainterPath()
            path.moveTo(center)
            path.arcTo(sector_rect, start_qt, -self.SECTOR)
            path.closeSubpath()
            p.setPen(QPen(QColor("#d9b64c"), 0.6))
            p.setBrush(QColor(COLOR_CSS[color_of(num)]))
            p.drawPath(path)
            # 数字 (放射方向に回転して描く)
            phi = (i * self.SECTOR + self.SECTOR / 2 + self.rot) % 360
            rad = math.radians(phi)
            tr = radius * 0.84
            pt = QPointF(cx + tr * math.sin(rad), cy - tr * math.cos(rad))
            p.save()
            p.translate(pt)
            p.rotate(phi)
            p.setPen(QColor("white"))
            p.setFont(num_font)
            p.drawText(QRectF(-10, -7, 20, 14),
                       Qt.AlignmentFlag.AlignCenter, str(num))
            p.restore()

        # 中央ハブ
        hub_r = radius * 0.48
        p.setBrush(QColor(self.center_color))
        p.setPen(QPen(QColor("#d9b64c"), 2.5))
        p.drawEllipse(center, hub_r, hub_r)
        hub_font = QFont()
        hub_font.setPointSize(20)
        hub_font.setBold(True)
        p.setPen(QColor("white"))
        p.setFont(hub_font)
        p.drawText(QRectF(cx - hub_r, cy - hub_r, hub_r * 2, hub_r * 2),
                   Qt.AlignmentFlag.AlignCenter, self.center_text)

        # ポインタ (上部固定)
        tri = QPolygonF([QPointF(cx - 9, 1), QPointF(cx + 9, 1),
                         QPointF(cx, 22)])
        p.setBrush(QColor("#ffd54f"))
        p.setPen(QPen(QColor("#8a6d1a"), 1.5))
        p.drawPolygon(tri)


# ---------------------------------------------------------------- メインウィンドウ

class RouletteWindow(GameWindowBase):
    DEFAULT_PORT = 35557
    GAME_TITLE = "ルーレット"
    GAME_KEY = "roulette"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("マルチプレイ・カジノルーレット")
        self.resize(1000, 820)
        self.statusBar().showMessage("メニューの「ゲーム > 接続設定」から開始してください")
        # ホスト用: 残り時間の配信と締切処理 (1秒間隔)
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_tick)
        # スピン演出の状態
        self._spinning = False
        self._rendered_phase = None
        self._fade_results = False   # スピン直後の描画で結果をフェードイン

    # ---------------- UI 構築

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("table")
        central.setStyleSheet("QWidget#table { background:#243b55; }")
        root = QVBoxLayout(central)

        # ホイール + ベットテーブル (当選番号・残り時間・履歴)
        board_box = QGroupBox("ルーレット")
        board_box.setStyleSheet("QGroupBox { color:white; font-weight:bold; }")
        bv = QVBoxLayout(board_box)
        top_row = QHBoxLayout()
        top_row.addStretch()
        self.wheel = WheelWidget()
        top_row.addWidget(self.wheel)
        top_row.addSpacing(14)

        table_col = QVBoxLayout()
        self.bet_table = BetTableWidget()
        self.bet_table.bet_clicked.connect(self._on_table_bet)
        table_col.addWidget(self.bet_table)
        # チップ選択 (額面を選んでテーブルをクリック)
        chip_row = QHBoxLayout()
        chip_label = QLabel("チップ:")
        chip_label.setStyleSheet("color:white; font-weight:bold;")
        chip_row.addWidget(chip_label)
        self.chip_value = 50
        self.chip_buttons = []
        for v in CHIP_VALUES:
            b = QPushButton(str(v))
            b.setCheckable(True)
            b.setFixedSize(46, 46)
            b.setEnabled(False)
            b.setStyleSheet(chip_button_style(v))
            b.clicked.connect(lambda _, v=v: self._select_chip(v))
            chip_row.addWidget(b)
            self.chip_buttons.append(b)
        self.chip_buttons[CHIP_VALUES.index(self.chip_value)].setChecked(True)
        hint = QLabel("額面を選んでテーブルをクリック")
        hint.setStyleSheet("color:#b9c9de; font-size:12px;")
        chip_row.addSpacing(10)
        chip_row.addWidget(hint)
        chip_row.addStretch()
        table_col.addLayout(chip_row)
        top_row.addLayout(table_col)
        top_row.addStretch()
        bv.addLayout(top_row)

        self.timer_label = QLabel("")
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_label.setStyleSheet(
            "color:#ffe082; font-size:18px; font-weight:bold;")
        bv.addWidget(self.timer_label)
        self.message_label = QLabel("")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setStyleSheet("color:#8ef58e; font-size:14px;")
        bv.addWidget(self.message_label)
        hist_row = QHBoxLayout()
        hist_row.addStretch()
        hist_label = QLabel("履歴:")
        hist_label.setStyleSheet("color:#b9c9de; font-size:12px;")
        hist_row.addWidget(hist_label)
        self.history_row = QHBoxLayout()
        hist_row.addLayout(self.history_row)
        hist_row.addStretch()
        bv.addLayout(hist_row)
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
        scroll.setMinimumHeight(220)
        root.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.clear_btn = QPushButton("ベット取消")
        self.done_btn = QPushButton("賭け終了")
        self.start_btn = QPushButton("ラウンド開始")
        for b in (self.clear_btn, self.done_btn, self.start_btn):
            b.setMinimumHeight(40)
            b.setStyleSheet("font-size:15px; font-weight:bold;")
            b.setEnabled(False)
        self.clear_btn.clicked.connect(
            lambda: self.submit_action({"type": "action", "action": "clear"}))
        self.done_btn.clicked.connect(
            lambda: self.submit_action({"type": "action", "action": "done"}))
        self.start_btn.clicked.connect(self.host_start_round)
        btn_row.addWidget(self.clear_btn)
        btn_row.addWidget(self.done_btn)
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
        return RouletteEngine()

    def on_host_started(self):
        self.start_btn.setEnabled(True)
        self._tick_timer.start(1000)

    def reset_game_ui(self):
        self._tick_timer.stop()
        self._spinning = False
        self._rendered_phase = None
        self._fade_results = False
        self.wheel.stop_spin()
        self.wheel.set_idle(False)
        self.wheel.set_center("-", "#555")
        self.bet_table.set_bets({}, {})
        self.bet_table.set_winning(None)
        self.bet_table.set_betting_enabled(False)
        for b in (self.clear_btn, self.done_btn, self.start_btn):
            b.setEnabled(False)
        for b in self.chip_buttons:
            b.setEnabled(False)
        clear_layout(self.players_row)
        clear_layout(self.history_row)
        self.timer_label.setText("")
        self.message_label.setText("")

    def handle_action(self, pid, msg):
        a = msg.get("action")
        if a == "bet":
            return self.engine.place_bet(
                pid, msg.get("bet_type"), msg.get("number", 0),
                msg.get("amount", 0))
        if a == "clear":
            return self.engine.clear_bets(pid)
        if a == "done":
            return self.engine.set_done(pid)
        return False

    # ---------------- ホスト: 1秒ティック (残り時間配信と締切)

    def _on_tick(self):
        if self.mode != "host" or not self.engine:
            return
        if self.engine.phase == "betting":
            if self.engine.expired():
                self.engine.close_betting()
                self.log(f"◆ 時間切れ! {self.engine.message}")
                self.broadcast_info(f"◆ 時間切れ! {self.engine.message}")
            self.broadcast_state()

    # ---------------- 操作

    def _select_chip(self, value):
        self.chip_value = value
        for b, v in zip(self.chip_buttons, CHIP_VALUES):
            b.setChecked(v == value)

    def _on_table_bet(self, btype, number):
        """ベットテーブルのセルがクリックされた → 選択中のチップ額を置く。"""
        me = (self.last_state or {}).get("players", {}).get(str(self.my_id))
        if (me and isinstance(me.get("chips"), int)
                and me["chips"] < self.chip_value):
            self.statusBar().showMessage(
                f"チップが足りません (残り {me['chips']})")
            return
        self.submit_action({
            "type": "action", "action": "bet", "bet_type": btype,
            "number": number, "amount": self.chip_value,
        })

    def host_start_round(self):
        if self.mode == "client":
            self.request_start()   # 専用サーバのルームマスターとして開始要求
            return
        if self.mode != "host" or not self.engine:
            return
        if not self.engine.start_round():
            self.log("◆ ラウンドを開始できません (チップを持つプレイヤーがいません)")
            return
        self.log(f"◆ ベット受付を開始しました (制限時間 {BETTING_TIME} 秒)")
        self.broadcast_info(f"◆ ベット受付を開始しました (制限時間 {BETTING_TIME} 秒)")
        self.broadcast_state()

    # ---------------- 状態描画 (スピン演出付き)

    @staticmethod
    def _mask_result(state):
        """スピン中に結果がネタバレしないよう勝敗情報を伏せた状態を作る。"""
        s = copy.deepcopy(state)
        if s["phase"] == "result":
            s["message"] = ""
            s["history"] = s["history"][:-1]
            for p in s["players"].values():
                p["result"] = ""
                p["chips"] = "?"   # 精算後のチップ額から結果が分かってしまうため
        return s

    def render_state(self, state):
        phase = state["phase"]
        if self._spinning:
            # スピン終了まで結果を伏せて描画し続ける
            self._render(self._mask_result(state), spinning=True)
            return
        if (self._rendered_phase == "betting" and phase == "result"
                and state["winning"] is not None):
            # 締切の瞬間 → スピン開始 (結果は止まってから公開)
            self._spinning = True
            self._render(self._mask_result(state), spinning=True)
            self.wheel.spin_to(state["winning"],
                               on_finished=self._on_spin_done)
            return
        self._render(state, spinning=False)

    def _on_spin_done(self):
        self._spinning = False
        if self.last_state:
            self._fade_results = True
            self._render(self.last_state, spinning=False)
            if self.last_state.get("message"):
                self.log(f"◆ {self.last_state['message']}")

    def _render(self, state, spinning):
        phase = state["phase"]
        self._rendered_phase = phase
        fade_results = self._fade_results
        self._fade_results = False

        # ホイールと残り時間
        timer_color = "#ffe082"
        if spinning:
            self.timer_label.setText("スピン中...")
        elif phase == "result" and state["winning"] is not None:
            # 途中参加などアニメーションなしの結果表示
            if not self.wheel.is_spinning():
                self.wheel.show_number(state["winning"])
            self.timer_label.setText("")
        elif phase == "betting":
            self.wheel.set_center("?", "#555")
            self.wheel.set_idle(True)
            t = state["time_left"]
            self.timer_label.setText(f"残り時間: {t} 秒")
            if t <= 10:
                timer_color = "#ff8a80"   # 締切間際は赤で知らせる
        else:
            self.wheel.set_idle(False)
            self.wheel.set_center("-", "#555")
            self.timer_label.setText("")
        self.timer_label.setStyleSheet(
            f"color:{timer_color}; font-size:18px; font-weight:bold;")
        self.message_label.setText(state["message"])
        if fade_results and state["message"]:
            fade_in(self.message_label, 360)

        # 履歴
        clear_layout(self.history_row)
        for i, n in enumerate(state["history"]):
            lbl = QLabel(str(n))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedSize(28, 28)
            lbl.setStyleSheet(
                f"background:{COLOR_CSS[color_of(n)]}; color:white;"
                "border-radius:14px; font-size:12px; font-weight:bold;")
            self.history_row.addWidget(lbl)
            if fade_results and i == len(state["history"]) - 1:
                fade_in(lbl, 420)   # 直近の当選番号を演出

        # ベットテーブル (全員のチップと当選番号)
        mine, others = {}, {}
        for pid_str, pl in state["players"].items():
            for b in pl.get("bets_raw", []):
                key = (b["type"],
                       b["number"] if b["type"] == "straight" else 0)
                target = (mine if (self.my_id is not None
                                   and pid_str == str(self.my_id)) else others)
                target[key] = target.get(key, 0) + b["amount"]
        self.bet_table.set_bets(mine, others)
        self.bet_table.set_winning(
            state["winning"] if phase == "result" and not spinning else None)

        # プレイヤー
        clear_layout(self.players_row)
        for pid in state["order"]:
            p = state["players"][str(pid)]
            box = QGroupBox()
            title = p["name"] + (" (あなた)" if pid == self.my_id else "")
            box.setTitle(title)
            deciding = (phase == "betting" and p["status"] == "betting"
                        and not p["done"])
            border = "#ffd54f" if deciding else "#7c93b3"
            box.setStyleSheet(
                f"QGroupBox {{ color:white; font-weight:bold;"
                f" border:2px solid {border}; border-radius:8px;"
                f" margin-top:8px; padding-top:4px; }}"
                f"QGroupBox::title {{ subcontrol-origin: margin; left:8px; }}")
            v = QVBoxLayout(box)
            info = QLabel(f"チップ: {p['chips']}  / ベット計: {p['total_bet']}")
            info.setStyleSheet("color:#dce6f2; font-size:13px;")
            v.addWidget(info)
            bets = QLabel("\n".join(p["bets"]) if p["bets"] else "(ベットなし)")
            bets.setStyleSheet("color:#b9c9de; font-size:12px;")
            v.addWidget(bets)
            if p["status"] == "betting":
                st_str = "賭け終了 ✓" if p["done"] else "ベット中..."
            else:
                st_str = "待機中"
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
            v.addStretch()
            self.players_row.addWidget(box)
        self.players_row.addStretch()

        # ボタン制御
        me = state["players"].get(str(self.my_id))
        can_bet = (phase == "betting" and me is not None
                   and me["status"] == "betting" and not me["done"])
        self.bet_table.set_betting_enabled(can_bet)
        for b in self.chip_buttons:
            b.setEnabled(can_bet)
        self.done_btn.setEnabled(can_bet)
        self.clear_btn.setEnabled(can_bet and bool(me["bets"]))
        # スピン演出中は次ラウンドを開始できない
        can = self.can_control(state)
        self.start_btn.setEnabled(can and phase != "betting" and not spinning)
        self.start_btn.setText(
            "次のラウンド" if phase == "result" else "ラウンド開始")

        # ステータスバー
        if spinning:
            self.statusBar().showMessage("スピン中...")
        elif can_bet:
            self.statusBar().showMessage(
                f"チップを選んでテーブルをクリック → 「賭け終了」"
                f" (残り {state['time_left']} 秒)")
        elif phase == "betting":
            waiting = [q["name"] for q in state["players"].values()
                       if q["status"] == "betting" and not q["done"]]
            self.statusBar().showMessage(
                "賭け終了待ち: " + "、".join(waiting) if waiting else "処理中...")
        elif phase == "result":
            self.statusBar().showMessage(state["message"])


def main():
    app = QApplication(sys.argv)
    win = RouletteWindow()
    win.show()
    win.open_connect_dialog()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
