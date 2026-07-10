# 統合ゲームサーバ (標準ライブラリのみ / 依存パッケージなし)
# ビルドコンテキストはリポジトリルート (shared/ を含めるため):
#   docker compose up -d --build
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY shared/ ./shared/
COPY server/ ./server/

# 実際の待受ポートは環境変数 SERVER_PORT (既定80) で決まる
EXPOSE 80

CMD ["python", "server/server.py"]
