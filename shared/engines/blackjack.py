# -*- coding: utf-8 -*-
"""ブラックジャックのエンジン (一斉選択型)。"""

import random

from ..cards import RANKS, SUITS

BET = 100          # 1ラウンドの固定ベット額
START_CHIPS = 1000
NUM_DECKS = 4


def new_deck():
    deck = [(r, s) for s in SUITS for r in RANKS] * NUM_DECKS
    random.shuffle(deck)
    return deck


def hand_value(cards):
    """A を 1/11 として最良の合計を返す。"""
    total = 0
    aces = 0
    for rank, _ in cards:
        if rank == "A":
            aces += 1
            total += 11
        elif rank in ("J", "Q", "K"):
            total += 10
        else:
            total += int(rank)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def is_blackjack(cards):
    return len(cards) == 2 and hand_value(cards) == 21


class GameEngine:
    """ホスト側で動くゲーム状態の権威。

    ターンは一斉選択制: 全員の hit / stand の選択が揃った時点で
    一括して1ターン進む。
    """

    def __init__(self):
        self.players = {}   # pid -> dict(name, cards, status, chips, result, choice)
        self.order = []     # 参加順の pid リスト
        self.deck = []
        self.dealer = []
        self.phase = "lobby"   # lobby / playing / result

    def add_player(self, pid, name):
        self.players[pid] = {
            "name": name, "cards": [], "status": "waiting",
            "chips": START_CHIPS, "result": "", "choice": None,
        }
        self.order.append(pid)

    def remove_player(self, pid):
        if pid not in self.players:
            return
        del self.players[pid]
        self.order.remove(pid)
        if self.phase == "playing":
            # 選択待ちだったプレイヤーの離脱で全員揃うことがある
            self._resolve_if_ready()

    def start_round(self):
        if self.phase == "playing" or not self.players:
            return
        self.deck = new_deck()
        self.dealer = [self.deck.pop(), self.deck.pop()]
        for p in self.players.values():
            p["cards"] = [self.deck.pop(), self.deck.pop()]
            p["result"] = ""
            p["choice"] = None
            p["status"] = "blackjack" if is_blackjack(p["cards"]) else "playing"
        self.phase = "playing"
        self._resolve_if_ready()   # 全員ブラックジャックなら即精算

    def act(self, pid, action):
        """hit / stand の選択を受け付ける。全員揃ったら一括で1ターン進む。"""
        p = self.players.get(pid)
        if (self.phase != "playing" or p is None
                or p["status"] != "playing" or p["choice"] is not None
                or action not in ("hit", "stand")):
            return False
        p["choice"] = action
        self._resolve_if_ready()
        return True

    def _resolve_if_ready(self):
        """全員の選択が揃っていたら一括処理。残っていなければ精算へ。"""
        playing = [p for p in self.players.values() if p["status"] == "playing"]
        if not playing:
            self._dealer_play_and_score()
            return
        if any(p["choice"] is None for p in playing):
            return   # まだ選択待ちのプレイヤーがいる
        for p in playing:
            if p["choice"] == "hit":
                p["cards"].append(self.deck.pop())
                v = hand_value(p["cards"])
                if v > 21:
                    p["status"] = "bust"
                elif v == 21:
                    p["status"] = "stand"
            else:
                p["status"] = "stand"
            p["choice"] = None
        self._resolve_if_ready()   # 全員終了ならディーラーへ

    def _dealer_play_and_score(self):
        while hand_value(self.dealer) < 17:
            self.dealer.append(self.deck.pop())
        d_val = hand_value(self.dealer)
        d_bj = is_blackjack(self.dealer)
        for p in self.players.values():
            if p["status"] == "waiting":   # 途中参加者はラウンド外
                continue
            v = hand_value(p["cards"])
            if p["status"] == "bust":
                delta = -BET
            elif p["status"] == "blackjack":
                delta = 0 if d_bj else int(BET * 1.5)
            elif d_bj or (d_val <= 21 and d_val > v):
                delta = -BET
            elif d_val > 21 or v > d_val:
                delta = BET
            else:
                delta = 0
            p["chips"] += delta
            if delta > 0:
                p["result"] = f"WIN +{delta}"
            elif delta < 0:
                p["result"] = f"LOSE {delta}"
            else:
                p["result"] = "PUSH ±0"
        self.phase = "result"

    def public_state(self, viewer=None):
        """配布する状態。手番中はディーラーの2枚目を隠す。(視点によらず同一)"""
        hide = self.phase == "playing"
        dealer = list(self.dealer)
        if hide and len(dealer) >= 2:
            dealer = [dealer[0], ["?", "?"]]
        return {
            "phase": self.phase,
            "dealer": dealer,
            "dealer_value": None if hide else hand_value(self.dealer),
            "order": list(self.order),
            "players": {
                str(pid): {
                    "name": p["name"],
                    "cards": p["cards"],
                    "value": hand_value(p["cards"]),
                    "status": p["status"],
                    "chips": p["chips"],
                    "result": p["result"],
                    # 何を選んだかは伏せて「選択済み」だけ公開する
                    "chosen": p["choice"] is not None,
                } for pid, p in self.players.items()
            },
        }
