# 五目ならべ Webアプリ用 Dockerfile
FROM python:3.11-alpine

WORKDIR /app

# ソースコードをコピー（src 配下を /app に）
COPY src/ .

# DB 永続化用ディレクトリ（docker-compose でボリュームマウント）
RUN mkdir -p /app/data

# C 拡張ビルド用（eventlet 等に必要）
RUN apk add --no-cache gcc musl-dev

# 依存関係のインストール（app.py で使用する Flask-Login を追加）
RUN pip install --no-cache-dir -r requirements.txt Flask-Login

# アプリケーションのポートを公開
EXPOSE 5003

# Flask-SocketIO アプリを起動（0.0.0.0 で全インターフェースにバインド）
CMD ["python", "app.py"]
