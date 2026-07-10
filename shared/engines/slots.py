# -*- coding: utf-8 -*-
"""スロットのエンジン (自由プレイ型 / 即時精算)。"""

import random

BET = 50
START_CHIPS = 1000

# リール1本分のシンボル構成 (重み付き)
REEL = (["7"] * 1 + ["💎"] * 2 + ["🔔"] * 3 + ["BAR"] * 3
        + ["⭐"] * 4 + ["🍋"] * 5 + ["🍒"] * 6)
TRIPLE_PAYS = {"7": 100, "💎": 40, "🔔": 20, "BAR": 15,
               "⭐": 10, "🍋": 8, "🍒": 5}

PAYTABLE_TEXT = (
    "7×3=100倍  💎×3=40倍  🔔×3=20倍  BAR×3=15倍  ⭐×3=10倍\n"
    "🍋×3=8倍  🍒×3=5倍  |  7×2=4倍  🍒×2=2倍  7×1=1倍")


def calc_mult(symbols):
    if symbols[0] == symbols[1] == symbols[2]:
        return TRIPLE_PAYS[symbols[0]]
    sevens = symbols.count("7")
    if sevens == 2:
        return 4
    if symbols.count("🍒") == 2:
        return 2
    if sevens == 1:
        return 1
    return 0


class SlotsEngine:
    """スピンは即時精算。フェーズなし (常にプレイ可能)。"""

    def __init__(self):
        self.players = {}
        self.order = []
        self.phase = "playing"
        self.message = ""

    def add_player(self, pid, name):
        self.players[pid] = {"name": name, "chips": START_CHIPS,
                             "seq": 0, "symbols": None, "win": 0}
        self.order.append(pid)

    def remove_player(self, pid):
        if pid in self.players:
            del self.players[pid]
            self.order.remove(pid)

    def _spin_symbols(self):
        return [random.choice(REEL) for _ in range(3)]

    def act(self, pid, action):
        if action != "spin":
            return False
        p = self.players.get(pid)
        if p is None or p["chips"] < BET:
            return False
        p["chips"] -= BET
        symbols = self._spin_symbols()
        mult = calc_mult(symbols)
        win = mult * BET
        p["chips"] += win
        p["seq"] += 1
        p["symbols"] = symbols
        p["win"] = win
        if mult >= 20:
            self.message = f"🎉 {p['name']} が大当たり! +{win}"
        return True

    def public_state(self, viewer=None):
        return {
            "phase": self.phase,
            "message": self.message,
            "order": list(self.order),
            "players": {
                str(pid): {
                    "name": p["name"], "chips": p["chips"], "seq": p["seq"],
                    "symbols": p["symbols"], "win": p["win"],
                } for pid, p in self.players.items()
            },
        }
