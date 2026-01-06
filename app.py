import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# 本番環境ではランダムな文字列に変更してください
app.config['SECRET_KEY'] = 'secret_key_change_this_in_production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gomoku.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- SSL化に伴うセキュリティ設定 (HTTPS運用時) ---
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# WebSocket設定
socketio = SocketIO(app, async_mode='eventlet')
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'index'

# --- データベースモデル ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    nickname = db.Column(db.String(100), nullable=False)

# 対戦履歴テーブル
class GameResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    black_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    white_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    winner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    black = db.relationship('User', foreign_keys=[black_id])
    white = db.relationship('User', foreign_keys=[white_id])
    winner = db.relationship('User', foreign_keys=[winner_id])

# --- 状態管理 (メモリ上) ---
connected_users = {} # {socket_id: user_id}
games = {} 
# games構造: 
# { 
#   room_id: {
#       'black': user_id, 
#       'white': user_id, 
#       'board': [[0]*15...], 
#       'turn': user_id
#   } 
# }

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- ルーティング ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username')
    password = request.form.get('password')
    nickname = request.form.get('nickname')
    
    if User.query.filter_by(username=username).first():
        return {'status': 'error', 'msg': 'ID already exists'}, 400
    
    new_user = User(username=username, 
                    password=generate_password_hash(password, method='pbkdf2:sha256'),
                    nickname=nickname)
    db.session.add(new_user)
    db.session.commit()
    login_user(new_user)
    return {'status': 'success'}

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')
    user = User.query.filter_by(username=username).first()
    
    if user and check_password_hash(user.password, password):
        login_user(user)
        return {'status': 'success'}
    return {'status': 'error', 'msg': 'Invalid credentials'}, 401

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/api/history')
@login_required
def get_history():
    results = GameResult.query.order_by(GameResult.timestamp.desc()).limit(30).all()
    history_data = []
    for r in results:
        jst_time = r.timestamp + timedelta(hours=9)
        history_data.append({
            'time': jst_time.strftime('%Y-%m-%d %H:%M'),
            'black': r.black.nickname,
            'white': r.white.nickname,
            'winner': r.winner.nickname
        })
    return {'history': history_data}

# --- Socket.IO イベント ---

@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        connected_users[request.sid] = current_user.id
        join_room('lobby')
        emit_user_list()

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in connected_users:
        del connected_users[request.sid]
        emit_user_list()

# 【修正】ユーザーリスト送信時にステータス(対戦中かどうか)を含める
def emit_user_list():
    # 現在対戦中のユーザーIDと部屋IDのマッピングを作成
    playing_users = {}
    for rid, game in games.items():
        playing_users[game['black']] = rid
        playing_users[game['white']] = rid

    active_users = []
    seen_ids = set()
    for sid, uid in connected_users.items():
        if uid not in seen_ids:
            u = User.query.get(uid)
            if u:
                status = 'playing' if uid in playing_users else 'free'
                room_id = playing_users.get(uid) # 対戦中なら部屋ID
                
                active_users.append({
                    'id': u.id, 
                    'nickname': u.nickname,
                    'status': status,
                    'room_id': room_id
                })
            seen_ids.add(uid)
    
    socketio.emit('update_user_list', active_users, room='lobby')

@socketio.on('challenge_request')
def handle_challenge(data):
    target_user_id = int(data['target_id'])
    target_sid = None
    for sid, uid in connected_users.items():
        if uid == target_user_id:
            target_sid = sid
            break
    
    if target_sid:
        emit('receive_challenge', {
            'challenger_id': current_user.id,
            'challenger_name': current_user.nickname
        }, room=target_sid)

@socketio.on('challenge_response')
def handle_challenge_response(data):
    challenger_id = int(data['challenger_id'])
    accepted = data['accepted']
    
    challenger_sid = None
    opponent_sid = request.sid 
    
    for sid, uid in connected_users.items():
        if uid == challenger_id:
            challenger_sid = sid
            break
            
    if accepted and challenger_sid:
        room_id = f"game_{min(current_user.id, challenger_id)}_{max(current_user.id, challenger_id)}"
        
        games[room_id] = {
            'black': challenger_id,
            'white': current_user.id,
            'board': [[0]*15 for _ in range(15)],
            'turn': challenger_id
        }
        
        # プレイヤーに対戦開始通知
        emit('game_start', {'room_id': room_id, 'opponent': current_user.nickname, 'role': 'black'}, room=challenger_sid)
        emit('game_start', {'room_id': room_id, 'opponent': User.query.get(challenger_id).nickname, 'role': 'white'}, room=opponent_sid)
        
        # ロビーのステータス更新のためにリスト再送信
        emit_user_list()
        
    elif challenger_sid:
        emit('challenge_declined', {'msg': f'{current_user.nickname} declined.'}, room=challenger_sid)

@socketio.on('join_game_room')
def handle_join_game(data):
    room = data['room_id']
    join_room(room)
    leave_room('lobby')

# 【追加】観戦リクエスト処理
@socketio.on('join_spectate')
def handle_join_spectate(data):
    room_id = data['room_id']
    game = games.get(room_id)
    
    if game:
        join_room(room_id)
        leave_room('lobby')
        
        black_user = User.query.get(game['black'])
        white_user = User.query.get(game['white'])
        
        # 観戦者用の初期データ送信 (現在の盤面含む)
        emit('spectate_start', {
            'room_id': room_id,
            'black_name': black_user.nickname,
            'white_name': white_user.nickname,
            'board': game['board'],
            'current_turn': game['turn'],
            'black_id': game['black'],
            'white_id': game['white']
        })

@socketio.on('back_to_lobby')
def handle_back_to_lobby(data):
    old_room = data.get('room_id')
    if old_room:
        leave_room(old_room)
    join_room('lobby')
    emit_user_list()

@socketio.on('place_stone')
def handle_place_stone(data):
    room_id = data['room_id']
    row = data['row']
    col = data['col']
    user_id = current_user.id
    
    game = games.get(room_id)
    if not game:
        return
    
    # 観戦者や手番以外のプレイヤーによる操作を防止
    if game['turn'] != user_id:
        return 
        
    if game['board'][row][col] != 0:
        return

    stone_val = 1 if game['black'] == user_id else 2
    game['board'][row][col] = stone_val
    
    winner = check_winner(game['board'], stone_val, row, col)
    
    next_turn = game['white'] if game['turn'] == game['black'] else game['black']
    game['turn'] = next_turn
    
    # 観戦者を含む部屋全体に通知
    emit('update_board', {
        'row': row, 'col': col, 'color': stone_val, 'next_turn': next_turn
    }, room=room_id)
    
    if winner:
        record_game_result(game['black'], game['white'], user_id)
        emit('game_over', {'winner': user_id}, room=room_id)
        if room_id in games:
            del games[room_id]
            # ゲーム終了時、ロビーのステータス更新はクライアントがロビーに戻ったタイミングで行われるが
            # ここでも念のためemit_user_listを呼んでも良い（ただしbroadcastには工夫が必要なので今回は省略）

def record_game_result(black_id, white_id, winner_id):
    try:
        result = GameResult(black_id=black_id, white_id=white_id, winner_id=winner_id)
        db.session.add(result)
        db.session.commit()
    except Exception as e:
        print(f"Error saving game result: {e}")
        db.session.rollback()

def check_winner(board, stone, r, c):
    directions = [(0, 1), (1, 0), (1, 1), (1, -1)]
    for dr, dc in directions:
        count = 1
        for i in range(1, 5):
            nr, nc = r + dr * i, c + dc * i
            if 0 <= nr < 15 and 0 <= nc < 15 and board[nr][nc] == stone:
                count += 1
            else:
                break
        for i in range(1, 5):
            nr, nc = r - dr * i, c - dc * i
            if 0 <= nr < 15 and 0 <= nc < 15 and board[nr][nc] == stone:
                count += 1
            else:
                break
        if count >= 5:
            return True
    return False

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)