# -*- coding: utf-8 -*-
"""クラップスのエンジン (時限ベット型)。

パスライン / ドントパスはポイント制でロールをまたいで場に残る (locked)。
フィールド / エニーセブン / エニークラップス / イレブンはワンロールベット。
"""

import random

from .betting_base import BettingEngineBase


class CrapsEngine(BettingEngineBase):
    BETTING_TIME = 30
    BET_LABELS = {
        "pass": "パスライン", "dp": "ドントパス", "field": "フィールド",
        "any7": "エニーセブン", "anycraps": "エニークラップス",
        "eleven": "イレブン",
    }

    def __init__(self):
        super().__init__()
        self.point = None     # 成立中のポイント (None = カムアウト)
        self.dice = None
        self.history = []     # 出目合計の履歴

    def bet_valid(self, p, btype, number, amount):
        # ポイント成立中はパスライン系の新規ベット不可 (標準ルール)
        if btype in ("pass", "dp") and self.point is not None:
            return False
        return True

    def keeps_bet(self, bet):
        return bet.get("locked", False)

    def resolve(self, dice=None):
        d = tuple(dice) if dice else (random.randint(1, 6), random.randint(1, 6))
        total = d[0] + d[1]
        self.dice = list(d)
        point_was = self.point

        for p in self._betting_players():
            stake = 0
            ret = 0
            remain = []
            for bet in p["bets"]:
                a = bet["amount"]
                t = bet["type"]
                if t == "field":
                    stake += a
                    if total in (3, 4, 9, 10, 11):
                        ret += a * 2
                    elif total == 2:
                        ret += a * 3
                    elif total == 12:
                        ret += a * 4
                elif t == "any7":
                    stake += a
                    if total == 7:
                        ret += a * 5
                elif t == "anycraps":
                    stake += a
                    if total in (2, 3, 12):
                        ret += a * 8
                elif t == "eleven":
                    stake += a
                    if total == 11:
                        ret += a * 16
                elif t == "pass":
                    if point_was is None:        # カムアウトロール
                        if total in (7, 11):
                            stake += a
                            ret += a * 2
                        elif total in (2, 3, 12):
                            stake += a
                        else:
                            bet["locked"] = True   # ポイント成立 → 場に残る
                            remain.append(bet)
                    else:
                        if total == point_was:
                            stake += a
                            ret += a * 2
                        elif total == 7:
                            stake += a
                        else:
                            remain.append(bet)
                elif t == "dp":
                    if point_was is None:
                        if total in (2, 3):
                            stake += a
                            ret += a * 2
                        elif total == 12:
                            stake += a
                            ret += a     # 12はプッシュ
                        elif total in (7, 11):
                            stake += a
                        else:
                            bet["locked"] = True
                            remain.append(bet)
                    else:
                        if total == 7:
                            stake += a
                            ret += a * 2
                        elif total == point_was:
                            stake += a
                        else:
                            remain.append(bet)
            p["bets"] = remain
            p["chips"] += ret
            p["result"] = self.result_text(stake, ret)

        if point_was is None:
            if total in (7, 11):
                note = "ナチュラル!"
            elif total in (2, 3, 12):
                note = "クラップス!"
            else:
                self.point = total
                note = f"ポイント {total} 成立"
        else:
            if total == point_was:
                note = f"ポイント {point_was} ヒット!"
                self.point = None
            elif total == 7:
                note = "セブンアウト!"
                self.point = None
            else:
                note = "ロール継続"
        self.message = f"🎲 {d[0]} + {d[1]} = {total}  {note}"
        self.history.append(total)

    def extra_state(self):
        return {
            "dice": self.dice,
            "point": self.point,
            "history": self.history[-14:],
        }
