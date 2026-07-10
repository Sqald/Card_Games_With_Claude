# -*- coding: utf-8 -*-
"""シックボー (大小) のエンジン (時限ベット型・ワンロール)。"""

import random

from .betting_base import BettingEngineBase

TOTAL_ODDS = {4: 60, 5: 30, 6: 17, 7: 12, 8: 8, 9: 6, 10: 6,
              11: 6, 12: 6, 13: 8, 14: 12, 15: 17, 16: 30, 17: 60}


class SicBoEngine(BettingEngineBase):
    BETTING_TIME = 60
    BET_LABELS = {
        "big": "大 (11-17)", "small": "小 (4-10)",
        "triple": "エニートリプル", "total": "合計",
        "single": "シングル",
    }
    NUMBERED_BETS = {"total", "single"}

    def __init__(self):
        super().__init__()
        self.dice = None
        self.history = []   # 合計の履歴

    def bet_valid(self, p, btype, number, amount):
        if btype == "total":
            return number in TOTAL_ODDS
        if btype == "single":
            return 1 <= number <= 6
        return True

    def resolve(self, dice=None):
        d = list(dice) if dice else [random.randint(1, 6) for _ in range(3)]
        self.dice = d
        total = sum(d)
        triple = d[0] == d[1] == d[2]

        for p in self._betting_players():
            stake = sum(b["amount"] for b in p["bets"])
            ret = 0
            for bet in p["bets"]:
                a = bet["amount"]
                t = bet["type"]
                if t == "big" and 11 <= total <= 17 and not triple:
                    ret += a * 2
                elif t == "small" and 4 <= total <= 10 and not triple:
                    ret += a * 2
                elif t == "triple" and triple:
                    ret += a * 31
                elif t == "total" and total == bet["number"]:
                    ret += a * (TOTAL_ODDS[bet["number"]] + 1)
                elif t == "single":
                    cnt = d.count(bet["number"])
                    if cnt:
                        ret += a * (cnt + 1)
            p["chips"] += ret
            p["result"] = self.result_text(stake, ret)
            p["bets"] = []
        if triple:
            note = f"トリプル {d[0]}!"
        else:
            note = "大" if total >= 11 else "小"
        self.message = (f"🎲 {d[0]}・{d[1]}・{d[2]} = {total}  ({note})")
        self.history.append(total)

    def extra_state(self):
        return {"dice": self.dice, "history": self.history[-14:]}
