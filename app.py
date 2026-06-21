from flask import Flask, request, jsonify
from flask_cors import CORS
import datetime
import random

app = Flask(__name__)
# 開発環境や別ドメインからのアクセスを許可するためのCORS設定
CORS(app)

# 簡易的なインメモリデータベース（Renderの無料プランなど、インスタンス再起動でクリアされますが、手軽に動作します）
# 本格的に運用する場合はSQLiteやFirestoreなどをご検討ください
players_db = {}

# 10分以上更新がないプレイヤーをオフライン（非アクティブ）とみなす判定用
OFFLINE_THRESHOLD_SECONDS = 600

def get_clean_players():
    """プレイヤーの最終更新時刻を確認し、オンライン/オフライン状態を含めたリストを返します"""
    now = datetime.datetime.now()
    list_players = []
    for uid, p in players_db.items():
        last_seen = p.get("last_seen", now)
        elapsed = (now - last_seen).total_seconds()
        is_online = elapsed < OFFLINE_THRESHOLD_SECONDS
        
        list_players.append({
            "id": uid,
            "name": p.get("name", "名無しのわら"),
            "points": p.get("points", 0),
            "totalDamage": p.get("total_damage", 0),
            "state": p.get("state", {}),
            "is_online": is_online,
            "last_active": last_seen.strftime("%Y-%m-%d %H:%M:%S")
        })
    # 総ダメージ順でソート
    list_players.sort(key=lambda x: x["totalDamage"], reverse=True)
    return list_players

@app.route('/api/ping', methods=['GET'])
def ping():
    return jsonify({"status": "ok", "message": "わら人形オンラインサーバー稼働中！"})

@app.route('/api/sync', methods=['POST'])
def sync_player():
    """プレイヤーデータのアップロード＆同期"""
    data = request.json or {}
    uid = data.get("id")
    name = data.get("name")
    
    if not uid:
        return jsonify({"error": "プレイヤーIDが必要です"}), 400
    
    if not name or name.strip() == "":
        name = f"プレイヤー_{uid[:6]}"

    # データベースに保存
    players_db[uid] = {
        "name": name,
        "points": int(data.get("points", 0)),
        "total_damage": int(data.get("totalDamage", 0)),
        "state": data.get("state", {}),
        "last_seen": datetime.datetime.now()
    }
    
    return jsonify({
        "success": True, 
        "players": get_clean_players()
    })

@app.route('/api/battle', methods=['POST'])
def battle():
    """他プレイヤーに戦いを挑むロジック"""
    data = request.json or {}
    attacker_id = data.get("attacker_id")
    defender_id = data.get("defender_id")
    
    if not attacker_id or not defender_id:
        return jsonify({"error": "攻撃者と防衛者のIDが必要です"}), 400
        
    if attacker_id == defender_id:
        return jsonify({"error": "自分自身には戦いを挑めません"}), 400
        
    attacker = players_db.get(attacker_id)
    defender = players_db.get(defender_id)
    
    if not attacker or not defender:
        return jsonify({"error": "プレイヤーが見つかりません"}), 404
        
    # 戦闘力の簡易計算 (剣Lv, 銃Lv, ジェムLv, タレットLv, わら人形Lvを総合評価)
    def calc_power(player):
        st = player.get("state", {})
        sword = int(st.get("sword", {}).get("lv", 0))
        gun = int(st.get("gun", {}).get("lv", 0))
        gem = int(st.get("gem", {}).get("lv", 0))
        turret = int(st.get("turret", {}).get("lv", 0))
        doll = int(st.get("doll", {}).get("lv", 1))
        
        # 補正値をかけた戦闘スコア
        power = (sword * 10) + (gun * 15) + (gem * 30) + (turret * 40) + (doll * 5) + 10
        return power

    att_power = calc_power(attacker)
    def_power = calc_power(defender)
    
    # 乱数要素（実力が近くても勝敗がブレるようにする）
    att_roll = att_power * random.uniform(0.7, 1.3)
    def_roll = def_power * random.uniform(0.7, 1.3)
    
    winner_id = None
    loot_points = 0
    
    if att_roll > def_roll:
        # 攻撃側の勝利！相手のポイントの10%（上限50000pt）を奪う
        winner_id = attacker_id
        loot_points = int(defender.get("points", 0) * 0.10)
        if loot_points > 50000:
            loot_points = 50000
        if loot_points < 10:
            loot_points = 10
            
        # ポイント移動処理
        defender["points"] = max(0, defender["points"] - loot_points)
        attacker["points"] = attacker["points"] + loot_points
        message = f"【勝利！】 {attacker['name']} は {defender['name']} に勝利した！ {loot_points}pt を奪い取りました！"
        win = True
    else:
        # 防衛側の勝利！攻撃側が返り討ちに遭い、5%失う（防衛側に渡る）
        winner_id = defender_id
        loot_points = int(attacker.get("points", 0) * 0.05)
        if loot_points > 25000:
            loot_points = 25000
        if loot_points < 5:
            loot_points = 5
            
        attacker["points"] = max(0, attacker["points"] - loot_points)
        defender["points"] = defender["points"] + loot_points
        message = f"【敗北...】 {attacker['name']} は {defender['name']} に返り討ちにされた！ 罰金として {loot_points}pt を失いました。"
        win = False
        
    # タイムスタンプ更新
    attacker["last_seen"] = datetime.datetime.now()
    defender["last_seen"] = datetime.datetime.now()
    
    return jsonify({
        "success": True,
        "win": win,
        "message": message,
        "loot_points": loot_points,
        "attacker_points": attacker["points"],
        "players": get_clean_players()
    })

if __name__ == '__main__':
    # ローカル開発時は 5000番ポート等で動作
    app.run(host='0.0.0.0', port=5000, debug=True)


