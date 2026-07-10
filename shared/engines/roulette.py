# -*- coding: utf-8 -*-
"""ルーレットのエンジン (ヨーロピアン式 0-36 / 時限ベット型)。"""

import random
import time

BETTING_TIME = 60      # ベット受付時間 (秒)
START_CHIPS = 1000

RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18,
               19, 21, 23, 25, 27, 30, 32, 34, 36}

# ベット種別 -> 配当 (n:1)
ODDS = {
    "straight": 35,
    "red": 1, "black": 1, "odd": 1, "even": 1, "low": 1, "high": 1,
    "dozen1": 2, "dozen2": 2, "dozen3": 2,
}
BET_LABELS = {
    "straight": "1点", "red": "赤", "black": "黒",
    "odd": "奇数", "even": "偶数", "low": "ロー(1-18)", "high": "ハイ(19-36)",
    "dozen1": "ダース(1-12)", "dozen2": "ダース(13-24)", "dozen3": "ダース(25-36)",
}


def color_of(n):
    if n == 0:
        return "green"
    return "red" if n in RED_NUMBERS else "black"


COLOR_JP = {"green": "緑", "red": "赤", "black": "黒"}
COLOR_CSS = {"green": "#1e8a4a", "red": "#c0392b", "black": "#222"}

# ヨーロピアンホイールの実際の数字配列 (時計回り)
WHEEL_ORDER = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36,
               11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9,
               22, 18, 29, 7, 28, 12, 35, 3, 26]


def bet_wins(bet, num):
    t = bet["type"]
    if t == "straight":
        return num == bet["number"]
    if num == 0:
        return False
    if t == "red":
        return num in RED_NUMBERS
    if t == "black":
        return num not in RED_NUMBERS
    if t == "odd":
        return num % 2 == 1
    if t == "even":
        return num % 2 == 0
    if t == "low":
        return num <= 18
    if t == "high":
        return num >= 19
    if t == "dozen1":
        return num <= 12
    if t == "dozen2":
        return 13 <= num <= 24
    if t == "dozen3":
        return num >= 25
    return False


def bet_desc(bet):
    if bet["type"] == "straight":
        return f"#{bet['number']} : {bet['amount']}"
    return f"{BET_LABELS[bet['type']]} : {bet['amount']}"


class RouletteEngine:
    """ホスト側で動くゲーム状態の権威。ベットは全員同時受付。"""

    def __init__(self):
        self.players = {}    # pid -> dict(name, chips, bets, done, status, result)
        self.order = []
        self.phase = "lobby"   # lobby / betting / result
        self.deadline = None   # ベット締切 (time.monotonic 基準)
        self.winning = None    # 直近の当選番号
        self.history = []      # 当選番号の履歴
        self.message = ""

    def add_player(self, pid, name):
        self.players[pid] = {
            "name": name, "chips": START_CHIPS, "bets": [],
            "done": False, "status": "waiting", "result": "",
        }
        self.order.append(pid)

    def remove_player(self, pid):
        if pid not in self.players:
            return
        del self.players[pid]
        self.order.remove(pid)
        if self.phase == "betting":
            bp = self._betting_players()
            if not bp or all(p["done"] for p in bp):
                self.close_betting()

    def _betting_players(self):
        return [p for p in self.players.values() if p["status"] == "betting"]

    def start_round(self):
        if self.phase == "betting":
            return False
        if not any(p["chips"] > 0 for p in self.players.values()):
            return False
        for p in self.players.values():
            p["bets"] = []
            p["done"] = False
            p["result"] = ""
            p["status"] = "betting" if p["chips"] > 0 else "waiting"
        self.phase = "betting"
        self.deadline = time.monotonic() + BETTING_TIME
        self.message = ""
        return True

    def time_left(self):
        if self.phase != "betting" or self.deadline is None:
            return 0
        return max(0, int(round(self.deadline - time.monotonic())))

    def expired(self):
        return self.phase == "betting" and time.monotonic() >= self.deadline

    def place_bet(self, pid, btype, number, amount):
        p = self.players.get(pid)
        try:
            amount = int(amount)
            number = int(number)
        except (TypeError, ValueError):
            return False
        if (self.phase != "betting" or p is None or p["status"] != "betting"
                or p["done"] or btype not in ODDS
                or amount <= 0 or amount > p["chips"]
                or (btype == "straight" and not 0 <= number <= 36)):
            return False
        p["chips"] -= amount
        p["bets"].append({"type": btype, "number": number, "amount": amount})
        return True

    def clear_bets(self, pid):
        p = self.players.get(pid)
        if (self.phase != "betting" or p is None or p["status"] != "betting"
                or p["done"] or not p["bets"]):
            return False
        p["chips"] += sum(b["amount"] for b in p["bets"])
        p["bets"] = []
        return True

    def set_done(self, pid):
        p = self.players.get(pid)
        if (self.phase != "betting" or p is None
                or p["status"] != "betting" or p["done"]):
            return False
        p["done"] = True
        if all(q["done"] for q in self._betting_players()):
            self.close_betting()
        return True

    def close_betting(self, number=None):
        """スピンして精算。number はテスト用に固定可。"""
        if self.phase != "betting":
            return
        self.winning = random.randint(0, 36) if number is None else number
        for p in self._betting_players():
            stake = sum(b["amount"] for b in p["bets"])
            ret = sum(b["amount"] * (ODDS[b["type"]] + 1)
                      for b in p["bets"] if bet_wins(b, self.winning))
            p["chips"] += ret
            net = ret - stake
            if stake == 0:
                p["result"] = ""
            elif net > 0:
                p["result"] = f"WIN +{net}"
            elif net < 0:
                p["result"] = f"LOSE {net}"
            else:
                p["result"] = "PUSH ±0"
        self.history.append(self.winning)
        self.message = (f"当選番号: {self.winning} "
                        f"({COLOR_JP[color_of(self.winning)]})")
        self.phase = "result"
        self.deadline = None

    def public_state(self, viewer=None):
        # ルーレットのベットは全員に公開される (視点によらず同一)
        return {
            "phase": self.phase,
            "time_left": self.time_left(),
            "winning": self.winning,
            "history": self.history[-10:],
            "message": self.message,
            "order": list(self.order),
            "players": {
                str(pid): {
                    "name": p["name"],
                    "chips": p["chips"],
                    "status": p["status"],
                    "done": p["done"],
                    "bets": [bet_desc(b) for b in p["bets"]],
                    "total_bet": sum(b["amount"] for b in p["bets"]),
                    "result": p["result"],
                } for pid, p in self.players.items()
            },
        }
