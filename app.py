import os
import random  # 【追加】ランダム用
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
# 本番環境ではランダムな文字列に変更してください
app.config['SECRET_KEY'] = 'secret_key_change_this_in_production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gomoku.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# HTTPS運用時のセキュリティ設定
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Nginx経由のHTTPS情報を正しく解釈させる設定
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

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
connected_users = {} 
games = {} 

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
    print(f"Connect Request: SID={request.sid}, Auth={current_user.is_authenticated}")
    
    if current_user.is_authenticated:
        connected_users[request.sid] = current_user.id
        
        # 進行中のゲームがあるか探す
        ongoing_game_id = None
        my_role = None
        opponent_name = "Unknown"
        
        for rid, game in games.items():
            if game['black'] == current_user.id:
                ongoing_game_id = rid
                my_role = 'black'
                opp_user = User.query.get(game['white'])
                if opp_user: opponent_name = opp_user.nickname
                break
            elif game['white'] == current_user.id:
                ongoing_game_id = rid
                my_role = 'white'
                opp_user = User.query.get(game['black'])
                if opp_user: opponent_name = opp_user.nickname
                break
        
        if ongoing_game_id:
            join_room(ongoing_game_id)
            game_data = games[ongoing_game_id]
            
            emit('reconnect_game', {
                'room_id': ongoing_game_id,
                'role': my_role,
                'opponent': opponent_name,
                'board': game_data['board'],
                'current_turn': game_data['turn']
            })
            emit_user_list()
        else:
            join_room('lobby')
            emit_user_list()

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in connected_users:
        del connected_users[request.sid]
        emit_user_list()

def emit_user_list():
    playing_map = {}
    for rid, game in games.items():
        playing_map[game['black']] = rid
        playing_map[game['white']] = rid

    active_users = []
    seen_ids = set()
    current_connections = connected_users.copy()
    
    for sid, uid in current_connections.items():
        if uid not in seen_ids:
            u = User.query.get(uid)
            if u:
                is_playing = uid in playing_map
                status = 'playing' if is_playing else 'free'
                room_id = playing_map.get(uid) 

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
        # 部屋IDの作成
        room_id = f"game_{min(current_user.id, challenger_id)}_{max(current_user.id, challenger_id)}"
        
        # 【修正】先手・後手をランダムに決定
        # random.choice で True/False を決め、Trueなら挑戦者が黒(先手)
        is_challenger_black = random.choice([True, False])
        
        if is_challenger_black:
            black_id = challenger_id
            white_id = current_user.id
            challenger_role = 'black'
            opponent_role = 'white'
        else:
            black_id = current_user.id
            white_id = challenger_id
            challenger_role = 'white'
            opponent_role = 'black'

        games[room_id] = {
            'black': black_id,
            'white': white_id,
            'board': [[0]*15 for _ in range(15)],
            'turn': black_id # 五目並べは常に黒が先手
        }
        
        # 各プレイヤーに通知
        # challenger_sid (申し込んだ人) には自分のロールを通知
        emit('game_start', {'room_id': room_id, 'opponent': current_user.nickname, 'role': challenger_role}, room=challenger_sid)
        
        # opponent_sid (申し込まれた人=current_user) には自分のロールを通知
        emit('game_start', {'room_id': room_id, 'opponent': User.query.get(challenger_id).nickname, 'role': opponent_role}, room=opponent_sid)
        
        emit_user_list()
        
    elif challenger_sid:
        emit('challenge_declined', {'msg': f'{current_user.nickname} declined.'}, room=challenger_sid)

@socketio.on('join_game_room')
def handle_join_game(data):
    room = data['room_id']
    join_room(room)
    leave_room('lobby')

@socketio.on('join_spectate')
def handle_join_spectate(data):
    room_id = data['room_id']
    game = games.get(room_id)
    
    if game:
        join_room(room_id)
        leave_room('lobby')
        
        black_user = User.query.get(game['black'])
        white_user = User.query.get(game['white'])
        
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
    
    if game['turn'] != user_id:
        return 
        
    if game['board'][row][col] != 0:
        return

    stone_val = 1 if game['black'] == user_id else 2
    game['board'][row][col] = stone_val
    
    winner = check_winner(game['board'], stone_val, row, col)
    
    next_turn = game['white'] if game['turn'] == game['black'] else game['black']
    game['turn'] = next_turn
    
    emit('update_board', {
        'row': row, 'col': col, 'color': stone_val, 'next_turn': next_turn
    }, room=room_id)
    
    if winner:
        record_game_result(game['black'], game['white'], user_id)
        emit('game_over', {'winner': user_id}, room=room_id)
        
        if room_id in games:
            del games[room_id]
        
        emit_user_list()

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
    socketio.run(app, host='0.0.0.0', port=5003)
