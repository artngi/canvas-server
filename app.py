import os
from flask import Flask
from flask_socketio import SocketIO, emit

app = Flask(__name__)
# セキュリティ設定：全てのURLからの接続を許可
socketio = SocketIO(app, cors_allowed_origins="*")

# 過去の描画データを保持するリスト（サーバー起動中のみ保持されます）
canvas_history = []

@app.route('/')
def index():
    return "Canvas Server is Running!"

@socketio.on('connect')
def handle_connect():
    # 後から入ってきた人にこれまでの履歴を全送信
    emit('history', canvas_history)

@socketio.on('draw')
def handle_draw(data):
    canvas_history.append(data)
    # 他の全員にリアルタイムで描画データを共有
    emit('draw', data, broadcast=True, include_self=False)

@socketio.on('clear')
def handle_clear():
    global canvas_history
    canvas_history = []
    emit('clear', broadcast=True)

if __name__ == '__main__':
    # クラウドサーバーが指定するポート番号を自動取得する設定
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)
