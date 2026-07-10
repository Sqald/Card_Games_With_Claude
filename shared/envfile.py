# -*- coding: utf-8 -*-
"""簡易 .env ローダ (外部ライブラリ不要)。

リポジトリルート (このファイルの親の親) にある .env を読み込み、
**未設定のキーのみ** os.environ に取り込む。
つまり優先度は OSの環境変数 > .env > コード内の既定値 となる
(Docker Compose では env_file が環境変数として渡るため .env の読込は不要)。

書式: KEY=VALUE (1行1件)。# 始まりの行と空行は無視。値の前後の引用符は外す。
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path=None):
    """path (省略時 <ルート>/.env) を読み込む。無ければ何もしない。"""
    p = Path(path) if path else ROOT / ".env"
    loaded = {}
    if not p.exists():
        return loaded
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            loaded[key] = value
            os.environ.setdefault(key, value)
    return loaded


def env_str(key, default=""):
    return os.environ.get(key, default)


def env_int(key, default=0):
    try:
        return int(os.environ.get(key, ""))
    except (TypeError, ValueError):
        return default
