# -*- coding: utf-8 -*-
"""Color & Numbers のエンジン (ターン制カードゲーム)。

色または数字が合うカードを出していき、先に手札を出し切ったら勝ち。
スキップ / リバース / ドロー2 / ワイルド / ドロー4 に対応。
上がった時点で他プレイヤーの手札点数を獲得する。
"""

import random

COLORS = ["R", "G", "B", "Y"]
HAND_SIZE = 7


def new_deck():
    """標準108枚: 各色 0×1, 1-9×2, skip/rev/+2×2, ワイルド×4, ドロー4×4。"""
    deck = []
    for c in COLORS:
        deck.append((c, "0"))
        for v in [str(n) for n in range(1, 10)] + ["skip", "rev", "+2"]:
            deck.append((c, v))
            deck.append((c, v))
    for _ in range(4):
        deck.append(("W", "wild"))
        deck.append(("W", "+4"))
    random.shuffle(deck)
    return deck


def is_playable(card, top, color):
    """card が場 (top, 現在色 color) に出せるか。"""
    if card[0] == "W":
        return True
    return card[0] == color or card[1] == top[1]


def card_points(card):
    v = card[1]
    if v.isdigit():
        return int(v)
    return 50 if card[0] == "W" else 20


class ColorNumbersEngine:
    """ホスト側で動くゲーム状態の権威。"""

    def __init__(self):
        self.players = {}     # pid -> dict(name, hand, score)
        self.order = []
        self.phase = "lobby"  # lobby / playing / result
        self.deck = []
        self.discard = []
        self.hand_order = []  # このゲームの参加 pid (ゲーム中は不変)
        self.direction = 1
        self.turn = None
        self.current_color = None
        self.pending = None   # (pid, index): 引いたカードを出すか選択中
        self.message = ""

    def add_player(self, pid, name):
        self.players[pid] = {"name": name, "hand": [], "score": 0}
        self.order.append(pid)

    def remove_player(self, pid):
        if pid not in self.players:
            return
        if self.pending and self.pending[0] == pid:
            self.pending = None
        if (self.phase == "playing" and pid in self.hand_order
                and self.turn == pid):
            self._advance(1)   # 削除前に手番を次へ回す
        del self.players[pid]
        self.order.remove(pid)
        if self.phase == "playing" and pid in self.hand_order:
            alive = [q for q in self.hand_order if q in self.players]
            if len(alive) == 1:
                self._finish(alive[0], prefix="他のプレイヤーが退出したため ")
            elif not alive:
                self.phase = "result"
                self.turn = None

    # ---------------- ゲーム進行

    def start_game(self):
        if self.phase == "playing" or len(self.players) < 2:
            return False
        self.deck = new_deck()
        self.hand_order = list(self.order)
        for p in self.players.values():
            p["hand"] = []
        for _ in range(HAND_SIZE):
            for pid in self.hand_order:
                self.players[pid]["hand"].append(self.deck.pop())
        # 最初の場札は数字カードにする
        for i, c in enumerate(self.deck):
            if c[1].isdigit():
                self.discard = [self.deck.pop(i)]
                break
        self.current_color = self.discard[-1][0]
        self.direction = 1
        self.pending = None
        self.message = ""
        self.turn = self.hand_order[0]
        self.phase = "playing"
        return True

    def _reshuffle(self):
        if len(self.discard) > 1:
            top = self.discard[-1]
            self.deck = self.discard[:-1]
            random.shuffle(self.deck)
            self.discard = [top]

    def _draw_cards(self, pid, k):
        p = self.players.get(pid)
        if not p:
            return 0
        drawn = 0
        for _ in range(k):
            if not self.deck:
                self._reshuffle()
            if not self.deck:
                break
            p["hand"].append(self.deck.pop())
            drawn += 1
        return drawn

    def _advance(self, steps):
        """direction 方向に手番を進める (退出済みプレイヤーは飛ばす)。"""
        if self.turn not in self.hand_order:
            return
        if not any(q in self.players for q in self.hand_order):
            self.turn = None
            return
        n = len(self.hand_order)
        idx = self.hand_order.index(self.turn)
        moved = 0
        while moved < steps:
            idx = (idx + self.direction) % n
            if self.hand_order[idx] in self.players:
                moved += 1
        self.turn = self.hand_order[idx]

    def _peek_next(self):
        """direction 方向の次の現存プレイヤー。"""
        n = len(self.hand_order)
        idx = self.hand_order.index(self.turn)
        while True:
            idx = (idx + self.direction) % n
            pid = self.hand_order[idx]
            if pid in self.players:
                return pid

    def _finish(self, winner, prefix=""):
        pts = sum(card_points(c)
                  for q, p in self.players.items() if q != winner
                  for c in p["hand"])
        w = self.players[winner]
        w["score"] += pts
        self.message = f"{prefix}{w['name']} の勝ち! +{pts}点"
        self.phase = "result"
        self.turn = None
        self.pending = None

    def act(self, pid, action, index=None, color=None):
        """play / draw / pass を処理。状態が変わったら True。"""
        if self.phase != "playing" or pid != self.turn or pid not in self.players:
            return False
        p = self.players[pid]

        if action == "draw":
            if self.pending:
                return False
            n = self._draw_cards(pid, 1)
            if n and is_playable(p["hand"][-1], self.discard[-1],
                                 self.current_color):
                # 引いたカードを出すかパスするか選択できる
                self.pending = (pid, len(p["hand"]) - 1)
            else:
                self._advance(1)
            return True

        if action == "pass":
            if not self.pending or self.pending[0] != pid:
                return False
            self.pending = None
            self._advance(1)
            return True

        if action == "play":
            try:
                index = int(index)
            except (TypeError, ValueError):
                return False
            if not 0 <= index < len(p["hand"]):
                return False
            if self.pending and self.pending[0] == pid and index != self.pending[1]:
                return False   # ドロー後はその1枚しか出せない
            card = p["hand"][index]
            if not is_playable(card, self.discard[-1], self.current_color):
                return False
            if card[0] == "W":
                if color not in COLORS:
                    return False
                new_color = color
            else:
                new_color = card[0]
            p["hand"].pop(index)
            self.discard.append(card)
            self.current_color = new_color
            self.pending = None
            if not p["hand"]:
                self._finish(pid)
                return True
            v = card[1]
            alive = [q for q in self.hand_order if q in self.players]
            if v == "skip":
                self._advance(2)
            elif v == "rev":
                if len(alive) == 2:
                    self._advance(2)   # 2人ではリバース=スキップ
                else:
                    self.direction *= -1
                    self._advance(1)
            elif v == "+2":
                self._draw_cards(self._peek_next(), 2)
                self._advance(2)
            elif v == "+4":
                self._draw_cards(self._peek_next(), 4)
                self._advance(2)
            else:
                self._advance(1)
            return True

        return False

    # ---------------- 状態配信

    def public_state(self, viewer=None):
        """viewer の視点の状態。他人の手札は枚数のみ (結果画面では公開)。"""
        players = {}
        for pid, p in self.players.items():
            reveal = pid == viewer or self.phase == "result"
            players[str(pid)] = {
                "name": p["name"], "count": len(p["hand"]),
                "score": p["score"], "in_round": pid in self.hand_order,
                "hand": p["hand"] if reveal else None,
            }
        return {
            "phase": self.phase,
            "turn": self.turn,
            "direction": self.direction,
            "deck_count": len(self.deck),
            "top": self.discard[-1] if self.discard else None,
            "current_color": self.current_color,
            "message": self.message,
            "pending": self.pending[0] if self.pending else None,
            "pending_index": (self.pending[1]
                              if self.pending and viewer == self.pending[0]
                              else None),
            "order": list(self.order),
            "players": players,
        }
