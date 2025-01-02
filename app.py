from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import os
import tweepy
import schedule
import time
import sqlite3
from datetime import datetime
import csv
from werkzeug.utils import secure_filename
import threading
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む 
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('APP_SECRET_KEY')

# 環境変数からTwitter API認証情報を取得 
consumer_api_key = os.getenv('CONSUMER_API_KEY') 
consumer_api_secret = os.getenv('CONSUMER_API_SECRET') 
bearer_token = os.getenv('BEARER_TOKEN') 
access_token = os.getenv('ACCESS_TOKEN') 
access_token_secret = os.getenv('ACCESS_TOKEN_SECRET')

client = tweepy.Client(
    bearer_token=bearer_token,
    consumer_key=consumer_api_key,
    consumer_secret=consumer_api_secret,
    access_token=access_token,
    access_token_secret=access_token_secret
)

# リセットフラグを初期化
reset_flag = False
# 初期値を設定 
interval = 3 
# 自動投稿実行中フラグ
is_auto_posting = False 

@app.route('/')
def index():
    global reset_flag
    conn = sqlite3.connect('tweets.db')
    cursor = conn.cursor()

    # 全ての is_deleted フラグが1になった場合、全てのフラグを0にリセット
    cursor.execute("SELECT COUNT(*) FROM tweets WHERE is_deleted = 0")
    count_not_deleted = cursor.fetchone()[0]
    if count_not_deleted == 0:
        cursor.execute("UPDATE tweets SET is_deleted = 0")
        conn.commit()
        flash("メッセージリストがリセットされました")
        reset_flag = True  # リセットフラグを立てる
    
    cursor.execute("SELECT id, message, is_deleted FROM tweets")
    messages = cursor.fetchall()
    conn.close()
    return render_template('index.html', messages=messages, interval=interval, is_auto_posting=is_auto_posting)

@app.route('/reset_status')
def reset_status():
    global reset_flag
    status = reset_flag
    reset_flag = False  # フラグをリセット
    return jsonify({"reset": status})

@app.route('/post', methods=['POST'])
def post():
    message = request.form['message']
    conn = sqlite3.connect('tweets.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tweets (message) VALUES (?)", (message,))
    conn.commit()
    conn.close()
    flash("メッセージが追加されました")
    return redirect(url_for('index'))

@app.route('/set_interval', methods=['POST'])
def set_interval():
    global interval
    interval = int(request.form['interval'])
    flash(f"投稿間隔が{interval}時間に設定されました")
    return redirect(url_for('index'))

@app.route('/start_auto_post')
def start_auto_post():
    global is_auto_posting 
    is_auto_posting = True 
    flash("自動投稿実行中") 
    threading.Thread(target=job).start() 
    return redirect(url_for('index'))

@app.route('/stop_auto_post') 
def stop_auto_post(): 
    global is_auto_posting 
    is_auto_posting = False 
    flash("自動投稿を停止しました") 
    return redirect(url_for('index'))

@app.route('/messages')
def get_messages():
    conn = sqlite3.connect('tweets.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, message, is_deleted FROM tweets")
    messages = cursor.fetchall()
    conn.close()
    return jsonify(messages)

@app.route('/delete/<int:id>', methods=['POST'])
def delete_message(id):
    conn = sqlite3.connect('tweets.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tweets WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash("メッセージが削除されました")
    return redirect(url_for('index'))

@app.route('/edit/<int:id>', methods=['POST'])
def edit_message(id):
    new_message = request.form['new_message']
    conn = sqlite3.connect('tweets.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE tweets SET message = ? WHERE id = ?", (new_message, id))
    conn.commit()
    conn.close()
    flash("メッセージが編集されました")
    return redirect(url_for('index'))

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        flash('ファイルがありません')
        return redirect(url_for('index'))

    file = request.files['file']

    if file.filename == '':
        flash('ファイルが選択されていません')
        return redirect(url_for('index'))

    if file and file.filename.endswith('.csv'):
        filename = secure_filename(file.filename)
        file.save(filename)
        with open(filename, newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            conn = sqlite3.connect('tweets.db')
            cursor = conn.cursor()
            for row in reader:
                if row:  # 空の行を無視
                    cursor.execute("INSERT INTO tweets (message) VALUES (?)", (row[0],))
            conn.commit()
            conn.close()
        flash('CSVファイルのメッセージが追加されました')
        os.remove(filename)  # 一時ファイルを削除
    else:
        flash('無効なファイル形式です。CSVファイルをアップロードしてください')

    return redirect(url_for('index'))

def get_message_from_db():
    conn = sqlite3.connect('tweets.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, message FROM tweets WHERE is_deleted = 0 ORDER BY RANDOM() LIMIT 1")
    result = cursor.fetchone()
    if result:
        cursor.execute("UPDATE tweets SET is_deleted = 1 WHERE id = ?", (result[0],))
        conn.commit()
    conn.close()
    return result[1] if result else None

def post_message():
    message = get_message_from_db()
    if message:
        try:
            response = client.create_tweet(text=message)
            print(f"投稿完了: {message} at {datetime.now()}")
            print(f"Tweet ID: {response.data['id']}")
        except tweepy.TweepyException as e:
            print(f"エラーが発生しました: {e}")
            if "duplicate" in str(e):
                print("重複投稿エラーが発生しました。次のメッセージを試します。")
                post_message()
    else:
        print("メッセージが見つかりませんでした")

def job():
    while is_auto_posting: 
        post_message() 
        time.sleep(interval * 3600) # 時間単位に変更

if __name__ == '__main__':
    app.run(debug=True)
