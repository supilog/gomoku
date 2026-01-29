# 本番リリース手順

五目ならべアプリの本番環境へのデプロイ手順と設定です。

---

## 1. 本番環境の前提条件

- **サーバー**: Docker および Docker Compose が利用可能な Linux サーバー（推奨: Ubuntu 22.04 LTS）
- **ネットワーク**: 本番では **HTTPS** を前提とします（Nginx 等でリバースプロキシし、SSL 終端）
- **ドメイン**: 任意（例: `gomoku.example.com`）

---

## 2. 本番用設定ファイルの準備

### 2.1 環境変数ファイル（.env）の作成

1. テンプレートをコピーします。

   ```bash
   cp env.example .env
   ```

2. `.env` を編集し、**SECRET_KEY** を必ず設定します。

   ```bash
   # 秘密鍵の生成（32バイト hex）
   openssl rand -hex 32
   ```

   生成した文字列を `.env` の `SECRET_KEY=` に設定してください。

3. 必要に応じて `SQLALCHEMY_DATABASE_URI` を変更します。  
   本番で PostgreSQL を使う場合は、接続文字列を指定してください。

**重要**: `.env` には秘密情報が含まれるため、**リポジトリにコミットしないでください**。  
（`.env` を `.gitignore` に追加することを推奨します。）

### 2.2 本番用アプリ設定の確認

- `FLASK_ENV=production` が設定されていると、Secure Cookie 等の本番向け設定が有効になります。
- `SECRET_KEY` が未設定の場合は起動時に警告が出ます。本番では必ず設定してください。

---

## 3. 本番リリースの手順

### 3.1 リリース前チェックリスト

- [ ] `.env` を作成し、`SECRET_KEY` を設定済みである
- [ ] `FLASK_ENV=production` が設定されている
- [ ] 本番サーバーに Docker / Docker Compose がインストールされている
- [ ] データ永続化用の `data/` ディレクトリのバックアップ方針を決めている（既存データがある場合）
- [ ] リバースプロキシ（Nginx 等）で HTTPS と WebSocket の設定が済んでいる

### 3.2 初回デプロイ（サーバー上で実行）

1. リポジトリをクローン（または rsync/scp でファイルを配置）します。

   ```bash
   git clone <リポジトリURL> gomoku
   cd gomoku
   ```

2. 環境変数ファイルを用意します。

   ```bash
   cp env.example .env
   # .env を編集して SECRET_KEY 等を設定
   ```

3. イメージをビルドし、本番用 Compose で起動します。

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env build --no-cache
   docker compose -f docker-compose.prod.yml --env-file .env up -d
   ```

4. 動作確認をします。

   ```bash
   curl -s -o /dev/null -w "%{http_code}" http://localhost:5003
   # 200 が返れば OK
   ```

5. ログでエラーがないか確認します。

   ```bash
   docker compose -f docker-compose.prod.yml logs -f gomoku
   ```

### 3.3 通常のリリース（更新時）

1. 最新コードを取得します。

   ```bash
   git pull
   ```

2. イメージを再ビルドし、コンテナを再作成します。

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env build --no-cache
   docker compose -f docker-compose.prod.yml --env-file .env up -d
   ```

3. ログでエラーがないか確認します。

   ```bash
   docker compose -f docker-compose.prod.yml logs -f gomoku
   ```

### 3.4 ロールバック手順

問題が発生した場合、前のバージョンに戻す手順です。

1. 前のコミットに戻します。

   ```bash
   git log --oneline   # 戻したいコミットを確認
   git checkout <コミットハッシュ>
   ```

2. イメージを再ビルドして起動します。

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env build --no-cache
   docker compose -f docker-compose.prod.yml --env-file .env up -d
   ```

3. 復旧後、必要に応じて `git checkout main` でブランチを戻し、原因修正後に再度リリースします。

---

## 4. リバースプロキシ（Nginx）の設定例

本番では Nginx で HTTPS を終端し、アプリへプロキシする構成を推奨します。

```nginx
# /etc/nginx/sites-available/gomoku の例
server {
    listen 443 ssl http2;
    server_name gomoku.example.com;

    ssl_certificate     /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5003;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /socket.io {
        proxy_pass http://127.0.0.1:5003;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

設定後、`nginx -t` で確認し、`systemctl reload nginx` で反映してください。

---

## 5. 運用メモ

| 項目 | 内容 |
|------|------|
| データ永続化 | `./data` に SQLite の DB が保存されます。定期的なバックアップを推奨します。 |
| ログ | `docker compose -f docker-compose.prod.yml logs gomoku` で確認できます。 |
| 停止 | `docker compose -f docker-compose.prod.yml down` で停止します。`data/` は残ります。 |
| 再起動 | `restart: unless-stopped` により、サーバー再起動後もコンテナは自動で起動します。 |

---

## 6. トラブルシューティング

- **502 Bad Gateway**: アプリ（5003）が起動していない、または Nginx の `proxy_pass` のポートが誤っている可能性があります。`docker compose -f docker-compose.prod.yml ps` でコンテナ状態を確認してください。
- **WebSocket がつながらない**: Nginx の `/socket.io` の `Upgrade` / `Connection` 設定を確認してください。
- **ログインできない・セッションが切れる**: HTTPS でアクセスしているか、`FLASK_ENV=production` と `SECRET_KEY` が正しく設定されているか確認してください。
