#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""マルチプレイ・カジノルーレット (PySide6)

ホストモード : 全IP(0.0.0.0)で指定ポートをLISTENし、自身もプレイヤーとして参加。
クライアントモード : ホストのIPアドレスとポートを指定して接続。

ヨーロピアン式 (0-36)。ベットはターン制ではなく全員同時受付で、
全員が「賭け終了」を押すか、制限時間 (60秒) が経過するとスピンする。
"""

import copy
import math
import sys

from PySide6.QtCore import (
    QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation,
)
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

# common を最初に import することで shared パッケージへのパスが通る
from common import GameWindowBase, clear_layout, fade_in
from shared.engines.roulette import (
    BETTING_TIME, COLOR_CSS, RouletteEngine, START_CHIPS, WHEEL_ORDER,
    color_of,
)

# コンボボックス表示順
BET_TYPES = [
    ("straight", "ストレート (数字1点 / 配当35倍)"),
    ("red", "赤 (配当1倍)"),
    ("black", "黒 (配当1倍)"),
    ("odd", "奇数 (配当1倍)"),
    ("even", "偶数 (配当1倍)"),
    ("low", "ロー 1-18 (配当1倍)"),
    ("high", "ハイ 19-36 (配当1倍)"),
    ("dozen1", "ダース 1-12 (配当2倍)"),
    ("dozen2", "ダース 13-24 (配当2倍)"),
    ("dozen3", "ダース 25-36 (配当2倍)"),
]


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
        self.resize(980, 760)
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

        # ホイール (当選番号・残り時間・履歴)
        board_box = QGroupBox("ルーレット")
        board_box.setStyleSheet("QGroupBox { color:white; font-weight:bold; }")
        bv = QVBoxLayout(board_box)
        self.wheel = WheelWidget()
        wl_row = QHBoxLayout()
        wl_row.addStretch()
        wl_row.addWidget(self.wheel)
        wl_row.addStretch()
        bv.addLayout(wl_row)
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

        # ベット操作
        bet_row = QHBoxLayout()
        bet_row.addStretch()
        self.type_combo = QComboBox()
        for _, label in BET_TYPES:
            self.type_combo.addItem(label)
        self.type_combo.setMinimumHeight(36)
        self.type_combo.currentIndexChanged.connect(
            lambda i: self.num_spin.setEnabled(i == 0))
        bet_row.addWidget(self.type_combo)
        bet_row.addWidget(QLabel("数字:"))
        self.num_spin = QSpinBox()
        self.num_spin.setRange(0, 36)
        self.num_spin.setMinimumHeight(36)
        bet_row.addWidget(self.num_spin)
        bet_row.addWidget(QLabel("賭け額:"))
        self.amt_spin = QSpinBox()
        self.amt_spin.setRange(1, START_CHIPS)
        self.amt_spin.setValue(50)
        self.amt_spin.setSingleStep(10)
        self.amt_spin.setMinimumHeight(36)
        bet_row.addWidget(self.amt_spin)
        self.bet_btn = QPushButton("ベット追加")
        bet_row.addWidget(self.bet_btn)
        bet_row.addStretch()
        root.addLayout(bet_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.clear_btn = QPushButton("ベット取消")
        self.done_btn = QPushButton("賭け終了")
        self.start_btn = QPushButton("ラウンド開始")
        for b in (self.bet_btn, self.clear_btn, self.done_btn, self.start_btn):
            b.setMinimumHeight(40)
            b.setStyleSheet("font-size:15px; font-weight:bold;")
            b.setEnabled(False)
        self.bet_btn.clicked.connect(self.send_bet)
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
        for b in (self.bet_btn, self.clear_btn, self.done_btn, self.start_btn):
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

    def send_bet(self):
        btype = BET_TYPES[self.type_combo.currentIndex()][0]
        self.submit_action({
            "type": "action", "action": "bet", "bet_type": btype,
            "number": self.num_spin.value(), "amount": self.amt_spin.value(),
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
        self.bet_btn.setEnabled(can_bet)
        self.done_btn.setEnabled(can_bet)
        self.clear_btn.setEnabled(can_bet and bool(me["bets"]))
        if can_bet and me["chips"] > 0:
            self.amt_spin.setMaximum(me["chips"])
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
                f"ベットを置いて「賭け終了」を押してください (残り {state['time_left']} 秒)")
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
