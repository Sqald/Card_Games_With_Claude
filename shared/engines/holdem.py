# -*- coding: utf-8 -*-
"""テキサスホールデムのエンジン (役判定・サイドポット対応)。"""

import random
from collections import Counter
from itertools import combinations

from ..cards import RANKS, SUITS

BLIND_SB = 10
BLIND_BB = 20
START_CHIPS = 1000

RANK_ORDER = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8,
              "9": 9, "10": 10, "J": 11, "Q": 12, "K": 13, "A": 14}

HAND_NAMES = {
    8: "ストレートフラッシュ", 7: "フォーカード", 6: "フルハウス",
    5: "フラッシュ", 4: "ストレート", 3: "スリーカード",
    2: "ツーペア", 1: "ワンペア", 0: "ハイカード",
}


# ---------------------------------------------------------------- 役判定

def new_deck():
    deck = [(r, s) for s in SUITS for r in RANKS]
    random.shuffle(deck)
    return deck


def eval5(cards):
    """5枚の役をタプルで返す (大きいほど強い)。"""
    ranks = sorted((RANK_ORDER[r] for r, _ in cards), reverse=True)
    flush = len({s for _, s in cards}) == 1
    uniq = sorted(set(ranks), reverse=True)
    straight_high = None
    if len(uniq) == 5:
        if uniq[0] - uniq[4] == 4:
            straight_high = uniq[0]
        elif uniq == [14, 5, 4, 3, 2]:   # A-2-3-4-5 (ホイール)
            straight_high = 5
    groups = sorted(Counter(ranks).items(),
                    key=lambda kv: (kv[1], kv[0]), reverse=True)
    if flush and straight_high:
        return (8, straight_high)
    if groups[0][1] == 4:
        return (7, groups[0][0], groups[1][0])
    if groups[0][1] == 3 and groups[1][1] == 2:
        return (6, groups[0][0], groups[1][0])
    if flush:
        return (5, *ranks)
    if straight_high:
        return (4, straight_high)
    if groups[0][1] == 3:
        kickers = [r for r in ranks if r != groups[0][0]]
        return (3, groups[0][0], *kickers)
    if groups[0][1] == 2 and groups[1][1] == 2:
        kicker = [r for r in ranks
                  if r != groups[0][0] and r != groups[1][0]][0]
        return (2, groups[0][0], groups[1][0], kicker)
    if groups[0][1] == 2:
        kickers = [r for r in ranks if r != groups[0][0]]
        return (1, groups[0][0], *kickers)
    return (0, *ranks)


def best_hand(cards):
    """7枚(以下)から最良の5枚役を返す。"""
    return max(eval5(list(c)) for c in combinations(cards, 5))


def hand_name_jp(score):
    if score[0] == 8 and score[1] == 14:
        return "ロイヤルフラッシュ"
    return HAND_NAMES[score[0]]


# ---------------------------------------------------------------- ゲームエンジン

class HoldemEngine:
    """ホスト側で動くゲーム状態の権威。"""

    BETTING_PHASES = ("preflop", "flop", "turn", "river")

    def __init__(self):
        self.players = {}     # pid -> dict
        self.order = []       # 参加順の pid リスト
        self.phase = "lobby"  # lobby / preflop / flop / turn / river / showdown
        self.deck = []
        self.community = []
        self.button_pos = -1
        self.button_pid = None
        self.turn = None
        self.current_bet = 0
        self.min_raise = BLIND_BB
        self.contribs = {}    # pid -> このハンドの総投入額 (退出者の分も保持)
        self.hand_order = []  # このハンドの参加 pid (ハンド中は不変)
        self.message = ""     # 結果メッセージ

    def in_betting(self):
        return self.phase in self.BETTING_PHASES

    def add_player(self, pid, name):
        self.players[pid] = {
            "name": name, "chips": START_CHIPS, "hole": [], "bet": 0,
            "committed": 0, "status": "waiting", "acted": False,
            "result": "", "hand_name": "", "revealed": False,
        }
        self.order.append(pid)

    def remove_player(self, pid):
        p = self.players.get(pid)
        if not p:
            return
        was_turn = self.turn == pid
        in_hand = self.in_betting() and p["status"] in ("active", "allin")
        del self.players[pid]
        self.order.remove(pid)
        # 投入済みチップ (contribs) はポットに残る
        if not in_hand:
            return
        contenders = [q for q, pl in self.players.items()
                      if pl["status"] in ("active", "allin")]
        if len(contenders) == 1:
            self._win_by_fold(contenders[0])
        elif was_turn:
            idx = self.hand_order.index(pid)
            nxt = self._next_actor_from((idx + 1) % len(self.hand_order))
            if nxt is None:
                self._next_street()
            else:
                self.turn = nxt

    # ---------------- ハンド進行

    def start_hand(self):
        if self.in_betting():
            return False
        parts = [pid for pid in self.order if self.players[pid]["chips"] > 0]
        if len(parts) < 2:
            return False
        self.deck = new_deck()
        self.community = []
        self.contribs = {pid: 0 for pid in parts}
        self.hand_order = parts
        self.message = ""
        for pid, p in self.players.items():
            p.update(hole=[], bet=0, committed=0, acted=False,
                     result="", hand_name="", revealed=False)
            p["status"] = "active" if pid in parts else "waiting"
        for pid in parts:
            self.players[pid]["hole"] = [self.deck.pop(), self.deck.pop()]
        n = len(parts)
        self.button_pos = (self.button_pos + 1) % n
        self.button_pid = parts[self.button_pos]
        if n == 2:
            # ヘッズアップはボタンがSB
            sb_i, bb_i = self.button_pos, (self.button_pos + 1) % n
        else:
            sb_i, bb_i = (self.button_pos + 1) % n, (self.button_pos + 2) % n
        self._post(parts[sb_i], BLIND_SB)
        self._post(parts[bb_i], BLIND_BB)
        self.current_bet = BLIND_BB
        self.min_raise = BLIND_BB
        self.phase = "preflop"
        self.turn = self._next_actor_from((bb_i + 1) % n)
        if self.turn is None:   # ブラインドで全員オールイン等
            self._next_street()
        return True

    def _post(self, pid, amount):
        p = self.players[pid]
        amount = min(amount, p["chips"])
        p["chips"] -= amount
        p["bet"] += amount
        p["committed"] += amount
        self.contribs[pid] = self.contribs.get(pid, 0) + amount
        if p["chips"] == 0 and p["status"] == "active":
            p["status"] = "allin"

    def _needs_action(self, pid):
        p = self.players.get(pid)
        return (p is not None and p["status"] == "active"
                and (not p["acted"] or p["bet"] < self.current_bet))

    def _next_actor_from(self, idx):
        n = len(self.hand_order)
        for i in range(n):
            pid = self.hand_order[(idx + i) % n]
            if self._needs_action(pid):
                return pid
        return None

    def act(self, pid, action, amount=0):
        """fold / check_call / raise を処理。状態が変わったら True。"""
        if not self.in_betting() or pid != self.turn:
            return False
        p = self.players[pid]
        if action == "fold":
            p["status"] = "folded"
        elif action == "check_call":
            to_call = self.current_bet - p["bet"]
            if to_call > 0:
                self._post(pid, to_call)   # チップ不足ならオールインコール
            p["acted"] = True
        elif action == "raise":
            try:
                amount = int(amount)       # このストリートの合計ベット額 (raise to)
            except (TypeError, ValueError):
                return False
            max_to = p["bet"] + p["chips"]
            min_to = self.current_bet + self.min_raise
            if amount > max_to or amount <= self.current_bet:
                return False
            if amount < min_to and amount != max_to:
                return False               # ミニマム未満はオールインのみ許可
            if amount - self.current_bet >= self.min_raise:
                self.min_raise = amount - self.current_bet
            self.current_bet = amount
            self._post(pid, amount - p["bet"])
            p["acted"] = True
        else:
            return False
        self._after_action(pid)
        return True

    def _after_action(self, pid):
        contenders = [q for q, p in self.players.items()
                      if p["status"] in ("active", "allin")]
        if len(contenders) == 1:
            self._win_by_fold(contenders[0])
            return
        idx = self.hand_order.index(pid) if pid in self.hand_order else 0
        nxt = self._next_actor_from((idx + 1) % len(self.hand_order))
        if nxt is None:
            self._next_street()
        else:
            self.turn = nxt

    def _next_street(self):
        self.turn = None
        for p in self.players.values():
            p["bet"] = 0
            p["acted"] = False
        self.current_bet = 0
        self.min_raise = BLIND_BB
        if self.phase == "preflop":
            self.community += [self.deck.pop() for _ in range(3)]
            self.phase = "flop"
        elif self.phase == "flop":
            self.community.append(self.deck.pop())
            self.phase = "turn"
        elif self.phase == "turn":
            self.community.append(self.deck.pop())
            self.phase = "river"
        else:
            self._showdown()
            return
        actives = [pid for pid, p in self.players.items()
                   if p["status"] == "active"]
        if len(actives) <= 1:
            # ベット可能なのが1人以下 (残りはオールイン) → ボードを配りきる
            self._next_street()
            return
        if self.button_pid in self.hand_order:
            start = (self.hand_order.index(self.button_pid) + 1) % len(self.hand_order)
        else:
            start = 0
        self.turn = self._next_actor_from(start)
        if self.turn is None:
            self._next_street()

    def _win_by_fold(self, winner):
        pot = sum(self.contribs.values())
        p = self.players[winner]
        p["chips"] += pot
        p["result"] = f"WIN +{pot}"
        self.message = f"{p['name']} がポット {pot} を獲得"
        self.phase = "showdown"
        self.turn = None

    def _showdown(self):
        self.phase = "showdown"
        self.turn = None
        contenders = [pid for pid, p in self.players.items()
                      if p["status"] in ("active", "allin")]
        scores = {}
        for pid in contenders:
            p = self.players[pid]
            p["revealed"] = True
            scores[pid] = best_hand(p["hole"] + self.community)
            p["hand_name"] = hand_name_jp(scores[pid])
        # サイドポット: 投入額の低い順にレイヤーを切り出して精算
        contribs = dict(self.contribs)
        winnings = {pid: 0 for pid in contenders}
        while True:
            remaining = [v for v in contribs.values() if v > 0]
            if not remaining:
                break
            level = min(remaining)
            eligible = [pid for pid in contenders if contribs.get(pid, 0) > 0]
            pot = 0
            for pid in contribs:
                take = min(contribs[pid], level)
                contribs[pid] -= take
                pot += take
            if not eligible:
                break
            best = max(scores[q] for q in eligible)
            winners = [q for q in eligible if scores[q] == best]
            share = pot // len(winners)
            rem = pot - share * len(winners)
            for i, q in enumerate(winners):
                winnings[q] += share + (rem if i == 0 else 0)
        parts = []
        for pid in contenders:
            p = self.players[pid]
            amt = winnings[pid]
            if amt > 0:
                p["chips"] += amt
                p["result"] = f"WIN +{amt}"
                parts.append(f"{p['name']}: +{amt} ({p['hand_name']})")
        self.message = " / ".join(parts)

    # ---------------- 状態配信

    def public_state(self, viewer=None):
        """viewer の視点の状態。他人の手札はショーダウンまで隠す。"""
        players = {}
        for pid, p in self.players.items():
            if pid == viewer or p["revealed"]:
                hole = p["hole"]
            elif p["hole"] and p["status"] in ("active", "allin"):
                hole = [["?", "?"], ["?", "?"]]
            else:
                hole = []
            players[str(pid)] = {
                "name": p["name"], "chips": p["chips"], "bet": p["bet"],
                "status": p["status"], "hole": hole,
                "result": p["result"], "hand_name": p["hand_name"],
            }
        return {
            "phase": self.phase,
            "turn": self.turn,
            "community": self.community,
            "pot": sum(self.contribs.values()),
            "current_bet": self.current_bet,
            "min_raise_to": self.current_bet + self.min_raise,
            "button": self.button_pid,
            "order": list(self.order),
            "message": self.message,
            "players": players,
        }
