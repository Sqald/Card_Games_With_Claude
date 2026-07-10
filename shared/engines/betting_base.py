# -*- coding: utf-8 -*-
"""時限ベット型ゲームのエンジン基底

「全員が賭け終わるか制限時間経過で締切 → 抽選 → 一括精算」という
進行 (ルーレット型) を持つゲームの共通ロジック。サブクラスは
resolve() (抽選と精算) と extra_state() を実装する。
"""

import time

START_CHIPS = 1000


class BettingEngineBase:
    """時限ベット型エンジンの基底。サブクラスは resolve() で抽選と精算を行う。"""

    BETTING_TIME = 60
    BET_LABELS = {}       # btype -> 表示ラベル
    NUMBERED_BETS = set()  # 番号指定が必要な btype

    def __init__(self):
        self.players = {}   # pid -> dict(name, chips, bets, done, status, result)
        self.order = []
        self.phase = "lobby"   # lobby / betting / result
        self.deadline = None
        self.message = ""

    # ---- サブクラスのフック

    def bet_valid(self, p, btype, number, amount):
        """ベット可否の追加検証 (基本検証は place_bet が行う)。"""
        return True

    def keeps_bet(self, bet):
        """ラウンドをまたいで場に残るベットか (クラップスのパスライン等)。"""
        return False

    def on_round_start(self):
        pass

    def can_start(self):
        return True

    def resolve(self, **rig):
        """抽選して全員を精算し、message / result を設定する。"""
        raise NotImplementedError

    def extra_state(self):
        """公開状態に追加するゲーム固有情報。"""
        return {}

    # ---- 共通処理

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
        if self.phase == "betting" or not self.can_start():
            return False
        any_active = False
        for p in self.players.values():
            p["bets"] = [b for b in p["bets"] if self.keeps_bet(b)]
            p["done"] = False
            p["result"] = ""
            active = p["chips"] > 0 or bool(p["bets"])
            p["status"] = "betting" if active else "waiting"
            any_active = any_active or active
        if not any_active:
            return False
        self.on_round_start()
        self.phase = "betting"
        self.deadline = time.monotonic() + self.BETTING_TIME
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
                or p["done"] or btype not in self.BET_LABELS
                or amount <= 0 or amount > p["chips"]
                or not self.bet_valid(p, btype, number, amount)):
            return False
        p["chips"] -= amount
        p["bets"].append({"type": btype, "number": number,
                          "amount": amount, "locked": False})
        return True

    def clear_bets(self, pid):
        """このラウンドに置いたベットを返金 (ロック済みは対象外)。"""
        p = self.players.get(pid)
        if (self.phase != "betting" or p is None or p["status"] != "betting"
                or p["done"]):
            return False
        unlocked = [b for b in p["bets"] if not b.get("locked")]
        if not unlocked:
            return False
        p["chips"] += sum(b["amount"] for b in unlocked)
        p["bets"] = [b for b in p["bets"] if b.get("locked")]
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

    def close_betting(self, **rig):
        """抽選と精算。rig はテスト用に結果を固定するキーワード引数。"""
        if self.phase != "betting":
            return
        self.resolve(**rig)
        self.phase = "result"
        self.deadline = None

    @staticmethod
    def result_text(stake, ret):
        if stake == 0:
            return ""
        net = ret - stake
        if net > 0:
            return f"WIN +{net}"
        if net < 0:
            return f"LOSE {net}"
        return "PUSH ±0"

    def bet_desc(self, bet):
        label = self.BET_LABELS.get(bet["type"], bet["type"])
        if bet["type"] in self.NUMBERED_BETS:
            label += f" {bet['number']}"
        if bet.get("locked"):
            label += " 🔒"
        return f"{label} : {bet['amount']}"

    def public_state(self, viewer=None):
        st = {
            "phase": self.phase,
            "time_left": self.time_left(),
            "message": self.message,
            "order": list(self.order),
            "players": {
                str(pid): {
                    "name": p["name"],
                    "chips": p["chips"],
                    "status": p["status"],
                    "done": p["done"],
                    "bets": [self.bet_desc(b) for b in p["bets"]],
                    "total_bet": sum(b["amount"] for b in p["bets"]),
                    "result": p["result"],
                } for pid, p in self.players.items()
            },
        }
        st.update(self.extra_state())
        return st
