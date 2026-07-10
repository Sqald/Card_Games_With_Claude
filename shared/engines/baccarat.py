# -*- coding: utf-8 -*-
"""バカラのエンジン (時限ベット型)。

サードカードは標準ルールで自動処理。
配当: プレイヤー1倍 / バンカー0.95倍 / タイ8倍 / ペア11倍。
"""

import math
import random

from ..cards import RANKS, SUITS
from .betting_base import BettingEngineBase

NUM_DECKS = 8


def card_value(card):
    rank = card[0]
    if rank == "A":
        return 1
    if rank in ("10", "J", "Q", "K"):
        return 0
    return int(rank)


def hand_total(cards):
    return sum(card_value(c) for c in cards) % 10


def new_shoe():
    shoe = [(r, s) for s in SUITS for r in RANKS] * NUM_DECKS
    random.shuffle(shoe)
    return shoe


class BaccaratEngine(BettingEngineBase):
    BETTING_TIME = 60
    BET_LABELS = {
        "player": "プレイヤー", "banker": "バンカー", "tie": "タイ",
        "ppair": "Pペア", "bpair": "Bペア",
    }

    def __init__(self):
        super().__init__()
        self.p_cards = []
        self.b_cards = []
        self.winner = None      # "player" / "banker" / "tie"
        self.history = []       # 勝者の履歴 ("P"/"B"/"T")

    def on_round_start(self):
        self.p_cards = []
        self.b_cards = []
        self.winner = None

    def resolve(self, shoe=None):
        d = list(shoe) if shoe is not None else new_shoe()
        p = [d.pop(), ]
        b = [d.pop(), ]
        p.append(d.pop())
        b.append(d.pop())
        pt, bt = hand_total(p), hand_total(b)
        if pt < 8 and bt < 8:            # ナチュラルでなければサードカード
            p3 = None
            if pt <= 5:
                p3 = d.pop()
                p.append(p3)
            if p3 is None:
                if bt <= 5:
                    b.append(d.pop())
            else:
                v = card_value(p3)
                draw = (bt <= 2 or (bt == 3 and v != 8)
                        or (bt == 4 and 2 <= v <= 7)
                        or (bt == 5 and 4 <= v <= 7)
                        or (bt == 6 and v in (6, 7)))
                if draw:
                    b.append(d.pop())
        self.p_cards, self.b_cards = p, b
        pt, bt = hand_total(p), hand_total(b)
        if pt > bt:
            self.winner = "player"
        elif bt > pt:
            self.winner = "banker"
        else:
            self.winner = "tie"
        ppair = p[0][0] == p[1][0]
        bpair = b[0][0] == b[1][0]

        for pl in self._betting_players():
            stake = sum(bt_["amount"] for bt_ in pl["bets"])
            ret = 0
            for bet in pl["bets"]:
                a = bet["amount"]
                t = bet["type"]
                if t == "player":
                    if self.winner == "player":
                        ret += a * 2
                    elif self.winner == "tie":
                        ret += a          # タイは返還
                elif t == "banker":
                    if self.winner == "banker":
                        ret += a + math.floor(a * 0.95)   # 5%コミッション
                    elif self.winner == "tie":
                        ret += a
                elif t == "tie" and self.winner == "tie":
                    ret += a * 9
                elif t == "ppair" and ppair:
                    ret += a * 12
                elif t == "bpair" and bpair:
                    ret += a * 12
            pl["chips"] += ret
            pl["result"] = self.result_text(stake, ret)
            pl["bets"] = []
        win_jp = {"player": "プレイヤーの勝ち", "banker": "バンカーの勝ち",
                  "tie": "タイ"}[self.winner]
        self.message = f"プレイヤー {pt} - バンカー {bt} : {win_jp}"
        self.history.append(
            {"player": "P", "banker": "B", "tie": "T"}[self.winner])

    def extra_state(self):
        return {
            "p_cards": self.p_cards,
            "b_cards": self.b_cards,
            "p_total": hand_total(self.p_cards) if self.p_cards else None,
            "b_total": hand_total(self.b_cards) if self.b_cards else None,
            "winner": self.winner,
            "history": self.history[-14:],
        }
