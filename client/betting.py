#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""時限ベット型ゲームのウィンドウ共通基盤

「全員が賭け終わるか制限時間経過で締切 → 抽選演出 → 一括精算」という
進行 (ルーレット型) を持つゲームのウィンドウ基底とダイス演出ウィジェット。
バカラ / クラップス / シックボー / マネーホイールが共用する。
エンジン基底は shared.engines.betting_base にある。
"""

import copy
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

# common を最初に import することで shared パッケージへのパスが通る
from common import GameWindowBase, clear_layout, fade_in
from shared.engines.betting_base import START_CHIPS


# ---------------------------------------------------------------- ダイス演出

DIE_PIPS = {
    1: [(0.5, 0.5)],
    2: [(0.25, 0.25), (0.75, 0.75)],
    3: [(0.25, 0.25), (0.5, 0.5), (0.75, 0.75)],
    4: [(0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)],
    5: [(0.25, 0.25), (0.75, 0.25), (0.5, 0.5), (0.25, 0.75), (0.75, 0.75)],
    6: [(0.25, 0.25), (0.75, 0.25), (0.25, 0.5), (0.75, 0.5),
        (0.25, 0.75), (0.75, 0.75)],
}


class DiceRowWidget(QWidget):
    """転がるアニメーション付きのダイス表示。"""

    def __init__(self, n=2, size=64, parent=None):
        super().__init__(parent)
        self.n = n
        self.die_size = size
        self.values = [1] * n
        self.setFixedSize(n * (size + 12) + 12, size + 16)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._final = None
        self._cb = None
        self._end = 0.0

    def show_values(self, values):
        self._timer.stop()
        self._cb = None
        self.values = list(values)
        self.update()

    def roll_to(self, values, on_finished=None, duration=1800):
        self._final = list(values)
        self._cb = on_finished
        self._end = time.monotonic() + duration / 1000.0
        self._timer.start(70)

    def is_rolling(self):
        return self._timer.isActive()

    def _step(self):
        if time.monotonic() >= self._end:
            self._timer.stop()
            self.values = self._final
            self.update()
            cb, self._cb = self._cb, None
            if cb:
                cb()
        else:
            self.values = [random.randint(1, 6) for _ in range(self.n)]
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.die_size
        for i, v in enumerate(self.values):
            x = 12 + i * (s + 12)
            rect = QRectF(x, 8, s, s)
            p.setBrush(QColor("#fdfdfd"))
            p.setPen(QPen(QColor("#888"), 2))
            p.drawRoundedRect(rect, 10, 10)
            p.setBrush(QColor("#c0392b"))
            p.setPen(Qt.PenStyle.NoPen)
            r = s * 0.09
            for fx, fy in DIE_PIPS[v]:
                p.drawEllipse(QPointF(x + fx * s, 8 + fy * s), r, r)


# ---------------------------------------------------------------- ウィンドウ基底

class BettingWindowBase(GameWindowBase):
    """時限ベット型ゲームのウィンドウ基底 (演出マスク付き)。

    サブクラスは以下を実装する:
      BET_TYPES     : [(btype, コンボ表示, 番号必要?, 番号下限, 番号上限)]
      build_board(v): 盤面ウィジェットの構築
      render_board(state, spinning): 盤面の描画
      start_result_animation(state, on_done) -> bool: 演出開始 (Falseで演出なし)
    """

    BET_TYPES = []
    NUMBER_LABEL = "番号:"
    BOARD_TITLE = "テーブル"
    TABLE_BG = "#1e4d40"
    START_LABEL = "ラウンド開始"
    NEXT_LABEL = "次のラウンド"

    def __init__(self):
        super().__init__()
        self.statusBar().showMessage("メニューの「ゲーム > 接続設定」から開始してください")
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_tick)
        self._spinning = False
        self._rendered_phase = None
        self._fade_results = False   # 演出直後の描画で結果をフェードイン

    # ---- サブクラスのフック

    def build_board(self, layout):
        raise NotImplementedError

    def render_board(self, state, spinning):
        raise NotImplementedError

    def start_result_animation(self, state, on_done):
        return False

    def reset_board(self):
        pass

    # ---- UI 構築

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("table")
        central.setStyleSheet(f"QWidget#table {{ background:{self.TABLE_BG}; }}")
        root = QVBoxLayout(central)

        board_box = QGroupBox(self.BOARD_TITLE)
        board_box.setStyleSheet("QGroupBox { color:white; font-weight:bold; }")
        bv = QVBoxLayout(board_box)
        self.build_board(bv)
        self.timer_label = QLabel("")
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_label.setStyleSheet(
            "color:#ffe082; font-size:17px; font-weight:bold;")
        bv.addWidget(self.timer_label)
        self.message_label = QLabel("")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setStyleSheet(
            "color:#8ef58e; font-size:15px; font-weight:bold;")
        bv.addWidget(self.message_label)
        root.addWidget(board_box)

        # プレイヤー一覧
        self.players_row = QHBoxLayout()
        holder = QWidget()
        holder.setLayout(self.players_row)
        holder.setStyleSheet("background:transparent;")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        scroll.setStyleSheet("QScrollArea { background:transparent; border:none; }")
        scroll.setMinimumHeight(190)
        root.addWidget(scroll, 1)

        # ベット操作
        bet_row = QHBoxLayout()
        bet_row.addStretch()
        self.type_combo = QComboBox()
        for t in self.BET_TYPES:
            self.type_combo.addItem(t[1])
        self.type_combo.setMinimumHeight(36)
        self.type_combo.currentIndexChanged.connect(self._on_bet_type_changed)
        bet_row.addWidget(self.type_combo)
        self.num_label = QLabel(self.NUMBER_LABEL)
        self.num_label.setStyleSheet("color:white;")
        self.num_spin = QSpinBox()
        self.num_spin.setMinimumHeight(36)
        if any(t[2] for t in self.BET_TYPES):
            bet_row.addWidget(self.num_label)
            bet_row.addWidget(self.num_spin)
        amt_label = QLabel("賭け額:")
        amt_label.setStyleSheet("color:white;")
        bet_row.addWidget(amt_label)
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
        self.start_btn = QPushButton(self.START_LABEL)
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

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(90)
        root.addWidget(self.log_view)

        self.setCentralWidget(central)
        self._on_bet_type_changed(0)

    def _on_bet_type_changed(self, i):
        if not self.BET_TYPES:
            return
        _, _, needs, lo, hi = self.BET_TYPES[i]
        self.num_spin.setEnabled(needs)
        if needs:
            self.num_spin.setRange(lo, hi)

    # ---- 共通フック実装

    def on_host_started(self):
        self.start_btn.setEnabled(True)
        self._tick_timer.start(1000)

    def reset_game_ui(self):
        self._tick_timer.stop()
        self._spinning = False
        self._rendered_phase = None
        self._fade_results = False
        for b in (self.bet_btn, self.clear_btn, self.done_btn, self.start_btn):
            b.setEnabled(False)
        clear_layout(self.players_row)
        self.timer_label.setText("")
        self.message_label.setText("")
        self.reset_board()

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

    def _on_tick(self):
        if self.mode != "host" or not self.engine:
            return
        if self.engine.phase == "betting":
            if self.engine.expired():
                self.engine.close_betting()
                self.log(f"◆ 時間切れ! {self.engine.message}")
                self.broadcast_info(f"◆ 時間切れ! {self.engine.message}")
            self.broadcast_state()

    # ---- 操作

    def send_bet(self):
        btype = self.BET_TYPES[self.type_combo.currentIndex()][0]
        self.submit_action({
            "type": "action", "action": "bet", "bet_type": btype,
            "number": self.num_spin.value(), "amount": self.amt_spin.value(),
        })

    def host_start_round(self):
        if self.mode == "client":
            self.request_start()
            return
        if self.mode != "host" or not self.engine:
            return
        if not self.engine.start_round():
            self.log("◆ ラウンドを開始できません")
            return
        self.log(f"◆ ベット受付を開始しました (制限時間 {self.engine.BETTING_TIME} 秒)")
        self.broadcast_info(
            f"◆ ベット受付を開始しました (制限時間 {self.engine.BETTING_TIME} 秒)")
        self.broadcast_state()

    # ---- 状態描画 (演出マスク付き)

    def _mask_result(self, state):
        s = copy.deepcopy(state)
        if s["phase"] == "result":
            s["message"] = ""
            if "history" in s and s["history"]:
                s["history"] = s["history"][:-1]
            for p in s["players"].values():
                p["result"] = ""
                p["chips"] = "?"   # 精算後のチップ額から結果が分かるため
        return s

    def render_state(self, state):
        if self._spinning:
            self._render(self._mask_result(state), spinning=True)
            return
        if (self._rendered_phase == "betting" and state["phase"] == "result"):
            self._spinning = True
            self._render(self._mask_result(state), spinning=True)
            if not self.start_result_animation(state, self._on_anim_done):
                self._on_anim_done()
            return
        self._render(state, spinning=False)

    def _on_anim_done(self):
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

        timer_color = "#ffe082"
        if spinning:
            self.timer_label.setText("抽選中...")
        elif phase == "betting":
            t = state["time_left"]
            self.timer_label.setText(f"残り時間: {t} 秒")
            if t <= 10:
                timer_color = "#ff8a80"   # 締切間際は赤で知らせる
        else:
            self.timer_label.setText("")
        self.timer_label.setStyleSheet(
            f"color:{timer_color}; font-size:17px; font-weight:bold;")
        self.message_label.setText(state["message"])
        if fade_results and state["message"]:
            fade_in(self.message_label, 360)
        self.render_board(state, spinning)

        # プレイヤーパネル
        clear_layout(self.players_row)
        for pid in state["order"]:
            p = state["players"][str(pid)]
            box = QGroupBox()
            title = p["name"] + (" (あなた)" if pid == self.my_id else "")
            box.setTitle(title)
            deciding = (phase == "betting" and p["status"] == "betting"
                        and not p["done"])
            border = "#ffd54f" if deciding else "#88a89a"
            box.setStyleSheet(
                f"QGroupBox {{ color:white; font-weight:bold;"
                f" border:2px solid {border}; border-radius:8px;"
                f" margin-top:8px; padding-top:4px; }}"
                f"QGroupBox::title {{ subcontrol-origin: margin; left:8px; }}")
            v = QVBoxLayout(box)
            info = QLabel(f"チップ: {p['chips']}  / ベット計: {p['total_bet']}")
            info.setStyleSheet("color:#dcecdf; font-size:13px;")
            v.addWidget(info)
            bets = QLabel("\n".join(p["bets"]) if p["bets"] else "(ベットなし)")
            bets.setStyleSheet("color:#b8cabf; font-size:12px;")
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
        if can_bet and isinstance(me["chips"], int) and me["chips"] > 0:
            self.amt_spin.setMaximum(me["chips"])
        can = self.can_control(state)
        self.start_btn.setEnabled(can and phase != "betting" and not spinning)
        self.start_btn.setText(
            self.NEXT_LABEL if phase == "result" else self.START_LABEL)

        # ステータスバー
        if spinning:
            self.statusBar().showMessage("抽選中...")
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
