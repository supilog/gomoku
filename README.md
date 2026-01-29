# 五目ならべ Webアプリ

Flask + Socket.IO で動作する五目ならべの Web アプリケーションです。  
ユーザー登録・ログイン、ロビーでの対戦申し込み、観戦、勝敗履歴の表示に対応しています。

## 前提条件

- **Docker で起動する場合**: Docker および Docker Compose がインストールされていること
- **ローカルで起動する場合**: Python 3.11 以上

---

## 起動手順

### 方法1: Docker で起動（推奨）

1. リポジトリのルートで以下を実行します。

   ```bash
   docker compose up --build
   ```

2. バックグラウンドで起動する場合:

   ```bash
   docker compose up -d --build
   ```

3. ブラウザで **http://localhost:5003** にアクセスします。

4. 停止する場合:

   ```bash
   docker compose down
   ```

- ユーザー情報・ゲーム履歴は Docker ボリューム（`gomoku-data`）に保存されるため、コンテナを削除してもデータは残ります。

---

### 方法2: ローカル環境で起動（Python 直接）

1. リポジトリをクローンし、`src` ディレクトリに移動します。

   ```bash
   cd /path/to/gomoku/src
   ```

2. 仮想環境を作成して有効化します。

   ```bash
   python3 -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   ```

3. 依存関係をインストールします（Flask-Login は `requirements.txt` に含まれていないため追加で指定）。

   ```bash
   pip install -r requirements.txt Flask-Login
   ```

4. アプリケーションを起動します。

   ```bash
   python app.py
   ```

5. ブラウザで **http://localhost:5003** にアクセスします。

- SQLite の DB ファイル（`gomoku.db`）は `src` ディレクトリに作成されます。

---

## 主な機能

- ユーザー登録・ログイン
- ロビーでのオンラインユーザー一覧表示
- 対戦申し込み・受諾でゲーム開始（先手・後手はランダム）
- 観戦モード（第三者による閲覧のみ）
- 勝敗履歴の表示（日本時間）
- スマートフォン表示の最適化

---

## 本番リリース

本番環境へのデプロイ手順・設定は [DEPLOYMENT.md](DEPLOYMENT.md) を参照してください。
