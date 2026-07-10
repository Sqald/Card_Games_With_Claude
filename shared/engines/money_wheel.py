# -*- coding: utf-8 -*-
"""マネーホイール (Big Six) のエンジン (時限ベット型)。

54区画にシンボル (1/2/5/10/20/JOKER/LOGO) が並び、
賭けたシンボルで止まれば額面の倍率で配当。
"""

import random

from .betting_base import BettingEngineBase

ODDS = {"1": 1, "2": 2, "5": 5, "10": 10, "20": 20, "JOKER": 40, "LOGO": 40}
SYMBOL_COLOR = {
    "1": "#7f8c8d", "2": "#2980b9", "5": "#c0392b", "10": "#27ae60",
    "20": "#d68910", "JOKER": "#8e44ad", "LOGO": "#b8a13a",
}
SYMBOL_DISP = {"JOKER": "JK", "LOGO": "★"}


def _make_segments():
    """54区画: 1×24, 2×15, 5×7, 10×4, 20×2, JOKER×1, LOGO×1。"""
    others = (["2"] * 15 + ["5"] * 7 + ["10"] * 4 + ["20"] * 2
              + ["JOKER"] + ["LOGO"])
    random.Random(6).shuffle(others)   # 配置は固定シードで毎回同じ
    segs = []
    oi = 0
    for i in range(54):
        if i % 9 in (0, 2, 4, 6):      # 9区画ごとに「1」を4つ → 計24
            segs.append("1")
        else:
            segs.append(others[oi])
            oi += 1
    return segs


SEGMENTS = _make_segments()


class MoneyWheelEngine(BettingEngineBase):
    BETTING_TIME = 60
    BET_LABELS = {s: (s if s not in SYMBOL_DISP else s) for s in ODDS}

    def __init__(self):
        super().__init__()
        self.index = None      # 当選区画
        self.symbol = None
        self.history = []

    def resolve(self, index=None):
        idx = random.randrange(len(SEGMENTS)) if index is None else index
        self.index = idx
        self.symbol = SEGMENTS[idx]
        for p in self._betting_players():
            stake = sum(b["amount"] for b in p["bets"])
            ret = 0
            for bet in p["bets"]:
                if bet["type"] == self.symbol:
                    ret += bet["amount"] * (ODDS[self.symbol] + 1)
            p["chips"] += ret
            p["result"] = self.result_text(stake, ret)
            p["bets"] = []
        self.message = f"当選シンボル: {self.symbol} (配当{ODDS[self.symbol]}倍)"
        self.history.append(self.symbol)

    def extra_state(self):
        return {"index": self.index, "symbol": self.symbol,
                "history": self.history[-14:]}
