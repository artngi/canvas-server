```python
import os
import uuid
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'straw-doll-secret-key-1298')

# CORS対応（すべてのオリジンからの接続を許可）
socketio = SocketIO(app, cors_allowed_origins="*")

# メモリ内に保持するデータ（Renderの無料枠等で動かすため、簡易的にメモリ保持。必要に応じてデータベース化してください）
# { user_id: { "username": str, "points": int, "totalDamage": int, "online": bool, "sid": str } }
players_db = {}
# 現在アクティブなバトル管理
# { battle_id: { "p1": uid, "p2": uid, "p1_hp": int, "p2_hp": int, "p1_max": int, "p2_max": int, "status": str } }
battles = {}

@app.route('/')
def index():
    return "Straw Doll Clicker Server is running!"

@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    user_id_to_offline = None
    for uid, p in players_db.items():
        if p.get('sid') == sid:
            p['online'] = False
            p['sid'] = None
            user_id_to_offline = uid
            break
    
    if user_id_to_offline:
        # 進行中のバトルがあれば異常終了させる
        for bid, b in list(battles.items()):
            if b['p1'] == user_id_to_offline or b['p2'] == user_id_to_offline:
                opponent_sid = None
                opp_id = b['p2'] if b['p1'] == user_id_to_offline else b['p1']
                if opp_id in players_db and players_db[opp_id]['online']:
                    opponent_sid = players_db[opp_id]['sid']
                
                if opponent_sid:
                    emit('battle_aborted', {'message': '対戦相手が切断されました。'}, room=opponent_sid)
                if bid in battles:
                    del battles[bid]

        broadcast_player_list()

@socketio.on('register_player')
def handle_register(data):
    user_id = data.get('userId')
    username = data.get('username', '名無し')
    points = int(data.get('points', 0))
    total_damage = int(data.get('totalDamage', 0))
    
    if not user_id:
        user_id = str(uuid.uuid4())
    
    players_db[user_id] = {
        "userId": user_id,
        "username": username,
        "points": points,
        "totalDamage": total_damage,
        "online": True,
        "sid": request.sid
    }
    
    emit('register_success', {'userId': user_id, 'username': username})
    broadcast_player_list()

@socketio.on('update_score')
def handle_update_score(data):
    user_id = data.get('userId')
    points = int(data.get('points', 0))
    total_damage = int(data.get('totalDamage', 0))
    
    if user_id in players_db:
        players_db[user_id]['points'] = points
        players_db[user_id]['totalDamage'] = total_damage
        players_db[user_id]['online'] = True
        players_db[user_id]['sid'] = request.sid
        broadcast_player_list()

# --- バトルシステム ---

@socketio.on('challenge_player')
def handle_challenge(data):
    challenger_id = data.get('challengerId')
    target_id = data.get('targetId')
    
    if not challenger_id or not target_id or challenger_id == target_id:
        return
        
    challenger = players_db.get(challenger_id)
    target = players_db.get(target_id)
    
    if challenger and target and target.get('online') and target.get('sid'):
        emit('challenge_received', {
            'challengerId': challenger_id,
            'challengerName': challenger['username']
        }, room=target['sid'])

@socketio.on('respond_challenge')
def handle_respond(data):
    challenger_id = data.get('challengerId')
    target_id = data.get('targetId')
    accepted = data.get('accepted', False)
    
    challenger = players_db.get(challenger_id)
    target = players_db.get(target_id)
    
    if not challenger or not target:
        return
        
    if not accepted:
        if challenger.get('sid'):
            emit('challenge_rejected', {'targetName': target['username']}, room=challenger['sid'])
        return
    
    # 承認された場合、バトルルームを作成
    battle_id = f"battle_{challenger_id}_{target_id}"
    
    # バトルの初期HP設定（総ダメージやレベルに応じたスケールも可能ですが、公平性のために一定または実力に合わせたベースを用意）
    # ここでは、互いに最大HP「1000」として戦闘開始
    max_hp = 1000
    battles[battle_id] = {
        "p1": challenger_id,
        "p2": target_id,
        "p1_hp": max_hp,
        "p2_hp": max_hp,
        "p1_max": max_hp,
        "p2_max": max_hp,
        "status": "ongoing"
    }
    
    # 両者に戦闘開始を通知
    if challenger.get('sid'):
        emit('battle_start', {
            'battleId': battle_id,
            'opponentId': target_id,
            'opponentName': target['username'],
            'myHp': max_hp,
            'oppHp': max_hp,
            'isChallenger': True
        }, room=challenger['sid'])
        
    if target.get('sid'):
        emit('battle_start', {
            'battleId': battle_id,
            'opponentId': challenger_id,
            'opponentName': challenger['username'],
            'myHp': max_hp,
            'oppHp': max_hp,
            'isChallenger': False
        }, room=target['sid'])

@socketio.on('battle_attack')
def handle_battle_attack(data):
    battle_id = data.get('battleId')
    attacker_id = data.get('playerId')
    damage = int(data.get('damage', 1))
    
    battle = battles.get(battle_id)
    if not battle or battle['status'] != 'ongoing':
        return
        
    p1_id = battle['p1']
    p2_id = battle['p2']
    
    # 攻撃を受けた側のHPを減らす
    if attacker_id == p1_id:
        # p1が攻撃 -> p2のHPが減る
        battle['p2_hp'] = max(0, battle['p2_hp'] - damage)
    elif attacker_id == p2_id:
        # p2が攻撃 -> p1のHPが減る
        battle['p1_hp'] = max(0, battle['p1_hp'] - damage)
        
    p1_info = players_db.get(p1_id)
    p2_info = players_db.get(p2_id)
    
    # 途中状況を両者に配信
    if p1_info and p1_info.get('sid'):
        emit('battle_update', {
            'myHp': battle['p1_hp'],
            'oppHp': battle['p2_hp']
        }, room=p1_info['sid'])
    if p2_info and p2_info.get('sid'):
        emit('battle_update', {
            'myHp': battle['p2_hp'],
            'oppHp': battle['p1_hp']
        }, room=p2_info['sid'])
        
    # 勝敗判定
    if battle['p1_hp'] <= 0 or battle['p2_hp'] <= 0:
        resolve_battle(battle_id)

def resolve_battle(battle_id):
    battle = battles.get(battle_id)
    if not battle or battle['status'] != 'ongoing':
        return
        
    battle['status'] = 'finished'
    p1_id = battle['p1']
    p2_id = battle['p2']
    
    p1_info = players_db.get(p1_id)
    p2_info = players_db.get(p2_id)
    
    winner_id = None
    loser_id = None
    
    if battle['p1_hp'] <= 0 and battle['p2_hp'] <= 0:
        # 引き分け
        pass
    elif battle['p1_hp'] <= 0:
        winner_id = p2_id
        loser_id = p1_id
    elif battle['p2_hp'] <= 0:
        winner_id = p1_id
        loser_id = p2_id
        
    # 勝者・敗者に結果を通知し、ポイントを反映
    # 報酬：勝者は50,000pt（または敗者のポイントの一部など）、敗者も参加賞1,000pt
    reward_win = 50000
    reward_lose = 2000
    
    if winner_id:
        win_player = players_db.get(winner_id)
        lose_player = players_db.get(loser_id)
        
        if win_player:
            win_player['points'] += reward_win
            if win_player.get('sid'):
                emit('battle_end', {
                    'result': 'win',
                    'message': f'勝利！ボーナス {reward_win} ptを獲得しました！',
                    'reward': reward_win
                }, room=win_player['sid'])
                
        if lose_player:
            lose_player['points'] += reward_lose
            if lose_player.get('sid'):
                emit('battle_end', {
                    'result': 'lose',
                    'message': f'敗北... 参加賞として {reward_lose} ptを獲得しました。',
                    'reward': reward_lose
                }, room=lose_player['sid'])
    else:
        # 引き分けまたは時間切れ時の判定（この関数はHP=0トリガー。時間切れは別途タイムアウトクライアントが要請可能）
        for pid in [p1_id, p2_id]:
            p = players_db.get(pid)
            if p and p.get('sid'):
                p['points'] += reward_lose
                emit('battle_end', {
                    'result': 'draw',
                    'message': f'引き分け！ 参加賞として {reward_lose} ptを獲得しました。',
                    'reward': reward_lose
                }, room=p['sid'])
                
    if battle_id in battles:
        del battles[battle_id]
    broadcast_player_list()

@socketio.on('battle_timeout')
def handle_battle_timeout(data):
    # 時間切れ時に、HPが多い方を勝者として決定する
    battle_id = data.get('battleId')
    battle = battles.get(battle_id)
    if not battle or battle['status'] != 'ongoing':
        return
        
    battle['status'] = 'finished'
    p1_id = battle['p1']
    p2_id = battle['p2']
    
    p1_info = players_db.get(p1_id)
    p2_info = players_db.get(p2_id)
    
    reward_win = 50000
    reward_lose = 2000
    
    # HP比較
    if battle['p1_hp'] > battle['p2_hp']:
        winner_id, loser_id = p1_id, p2_id
    elif battle['p2_hp'] > battle['p1_hp']:
        winner_id, loser_id = p2_id, p1_id
    else:
        winner_id, loser_id = None, None # 完全な引き分け
        
    if winner_id:
        win_player = players_db.get(winner_id)
        lose_player = players_db.get(loser_id)
        if win_player and win_player.get('sid'):
            win_player['points'] += reward_win
            emit('battle_end', {'result': 'win', 'message': f'時間切れ判定勝ち！ボーナス {reward_win} pt獲得！', 'reward': reward_win}, room=win_player['sid'])
        if lose_player and lose_player.get('sid'):
            lose_player['points'] += reward_lose
            emit('battle_end', {'result': 'lose', 'message': f'時間切れ判定負け... 参加賞 {reward_lose} pt獲得。', 'reward': reward_lose}, room=lose_player['sid'])
    else:
        for pid in [p1_id, p2_id]:
            p = players_db.get(pid)
            if p and p.get('sid'):
                p['points'] += reward_lose
                emit('battle_end', {'result': 'draw', 'message': f'同HPで時間切れ引き分け！ 参加賞 {reward_lose} pt獲得。', 'reward': reward_lose}, room=p['sid'])
                
    if battle_id in battles:
        del battles[battle_id]
    broadcast_player_list()

def broadcast_player_list():
    # 全プレイヤーリストをクライアントにブロードキャスト
    # セキュリティやデータ量削減のため、必要な情報のみ整形
    player_list = []
    for uid, p in players_db.items():
        player_list.append({
            "userId": uid,
            "username": p.get("username", "名無し"),
            "points": p.get("points", 0),
            "totalDamage": p.get("totalDamage", 0),
            "online": p.get("online", False)
        })
    # スコア（総ダメージ）順にソート
    player_list.sort(key=lambda x: x['totalDamage'], reverse=True)
    socketio.emit('update_players', {'players': player_list})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)

```
