from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import os
import tweepy
import time
import sqlite3
import csv
import threading
import logging
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('APP_SECRET_KEY')

# ログ設定
logging.basicConfig(filename='app.log', level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s')

# 定数の定義
INTERVAL_IN_SECONDS = 3600  # 1時間
CHECK_INTERVAL = 60  # 1分

# グローバル変数の初期化
reset_flag = False
interval = 3
specific_times = []
is_auto_posting = False
interval_type = 'interval'  # 初期値は時間間隔
current_account_id = None
auto_post_threads = {}  # アカウントごとのスレッドを管理する辞書

# データベースの初期化
def init_db():
    conn = sqlite3.connect('tweets.db')
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY,
        interval_type TEXT,
        interval INTEGER,
        specific_time TEXT,
        account_id INTEGER,
        FOREIGN KEY(account_id) REFERENCES accounts(id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tweets (
        id INTEGER PRIMARY KEY,
        message TEXT,
        is_deleted INTEGER DEFAULT 0,
        account_id INTEGER,
        FOREIGN KEY(account_id) REFERENCES accounts(id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        consumer_api_key TEXT NOT NULL,
        consumer_api_secret TEXT NOT NULL,
        bearer_token TEXT NOT NULL,
        access_token TEXT NOT NULL,
        access_token_secret TEXT NOT NULL
    )
    ''')

    # auto_post_statusテーブルを作成（存在しない場合は新規作成）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS auto_post_status (
        account_id INTEGER PRIMARY KEY,
        status BOOLEAN NOT NULL,
        FOREIGN KEY (account_id) REFERENCES accounts (id)
    )
    ''')

    conn.commit()
    conn.close()

init_db()

# SQLite3へのコネクション作成
def get_db_connection():
    conn = sqlite3.connect('tweets.db')
    conn.row_factory = sqlite3.Row
    return conn

# アカウント情報の読み込み
def load_account(account_id):
    global client, current_account_id, current_account
    current_account_id = account_id
    conn = get_db_connection() 
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
    current_account = cursor.fetchone()
    logging.debug(f"Loaded Account: {current_account}")

    if current_account:
        try:
            #logging.debug(f"Consumer Key: {current_account[2]}, Consumer Secret: {current_account[3]}, Access Token: {current_account[5]}, Access Token Secret: {current_account[6]}, Bearer Token: {current_account[4]}")
            client = tweepy.Client(
                bearer_token=current_account[4],
                consumer_key=current_account[2],
                consumer_secret=current_account[3],
                access_token=current_account[5],
                access_token_secret=current_account[6]
            )
            logging.debug("Twitter client initialized successfully")
        except Exception as e:
            logging.error(f"Error initializing Twitter client: {e}")

    conn.close()

# 設定の読み込み
def load_settings(account_id):
    global interval, specific_times, interval_type
    conn = get_db_connection() 
    cursor = conn.cursor()

    cursor.execute("SELECT interval_type, interval, specific_time FROM settings WHERE account_id = ?", (account_id,))
    settings = cursor.fetchall()
    if settings:
        interval_type = settings[0][0]
        if interval_type == 'interval':
            interval = settings[0][1]
            specific_times = []
        else:
            specific_times = [setting[2] for setting in settings if setting[2]]
            interval = None
    else:
        # 設定が見つからない場合の初期値を設定
        interval_type = 'interval'  # デフォルトの間隔タイプ
        interval = 1  # デフォルトの間隔時間（例：1時間）
        specific_times = []  # デフォルトの特定の時間は空

    conn.close()

# 自動投稿状態の取得
def load_auto_post_status(account_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT status FROM auto_post_status WHERE account_id = ?', (account_id,))
    status_row = cursor.fetchone()
    conn.close()
    return status_row[0] if status_row else False


# 自動投稿スケジュールの更新
def update_auto_post_schedule(account_id):
    global auto_post_threads

    logging.debug(f"Updating auto post schedule for account {account_id}: interval_type={interval_type}, interval={interval}, specific_times={specific_times}")

    # 現在のスレッドが存在し、動作中であればキャンセル
    if account_id in auto_post_threads and auto_post_threads[account_id]:
        logging.debug(f"auto_post_thread exists for account {account_id}: {auto_post_threads[account_id]}")
    if account_id in auto_post_threads and isinstance(auto_post_threads[account_id], threading.Thread):
        logging.debug(f"auto_post_thread is a threading.Thread instance for account {account_id}: {auto_post_threads[account_id].is_alive()}")

    if account_id in auto_post_threads and isinstance(auto_post_threads[account_id], threading.Thread) and auto_post_threads[account_id].is_alive():
        auto_post_threads[account_id].cancel()

    # 新しいスケジュールの設定
    if interval_type == 'interval' and interval is not None:
        auto_post_threads[account_id] = threading.Timer(interval * INTERVAL_IN_SECONDS, lambda : job(account_id))
    elif interval_type == 'specific' and specific_times:
        next_post_time = get_seconds_until_next_post(specific_times)
        auto_post_threads[account_id] = threading.Timer(next_post_time, lambda: job(account_id))

    if account_id in auto_post_threads and auto_post_threads[account_id]:
        auto_post_threads[account_id].start()

# 次の投稿時間の計算
def get_seconds_until_next_post(specific_times):
    now = datetime.now().time()
    future_times = [datetime.strptime(t, "%H:%M").time() for t in specific_times if datetime.strptime(t, "%H:%M").time() > now]
    if future_times:
        next_time = min(future_times)
    else:
        next_time = min([datetime.strptime(t, "%H:%M").time() for t in specific_times])
    next_post_time = datetime.combine(datetime.today(), next_time)
    if next_post_time < datetime.now():
        next_post_time += timedelta(days=1)
    return (next_post_time - datetime.now()).total_seconds()

# 自動投稿の実行関数
def job(account_id):
    try:
        logging.debug(f"Job function started for account {account_id}")
        load_account(account_id)
        load_settings(account_id)
        is_auto_posting = load_auto_post_status(account_id)
        while is_auto_posting:
            if interval_type == 'interval':
                logging.debug("Posting message in interval mode")
                post_message(account_id)
                time.sleep(interval * INTERVAL_IN_SECONDS)
            else:
                current_time = datetime.now().strftime("%H:%M")
                if current_time in specific_times:
                    logging.debug(f"Posting message at specific time: {current_time}")
                    post_message(account_id)
                    time.sleep(CHECK_INTERVAL)
                else:
                    time.sleep(CHECK_INTERVAL)
    except Exception as e:
        logging.error(f"Error in job for account {account_id}: {e}")

# メッセージの投稿関数
def post_message(account_id):
    try:
        logging.debug("Attempting to post message")
        message = get_message_from_db(account_id)
        if message:
            logging.debug(f"Message to post: {message}")
            response = client.create_tweet(text=message)
            logging.debug(f"Tweet Response: {response}")
            print(f"投稿完了: {message} at {datetime.now()}")
            print(f"Tweet ID: {response.data['id']}")
        else:
            logging.debug("No message to post")
    except tweepy.TweepyException as e:
        logging.error(f"Error posting message: {e}")
        print(f"エラーが発生しました: {e}")
        if "duplicate" in str(e):
            print("重複投稿エラーが発生しました。次のメッセージを試します。")
            post_message(account_id)
    except Exception as e:
        logging.error(f"Unexpected error in post_message for account {account_id}: {e}")

# データベースからメッセージを取得
def get_message_from_db(account_id):
    try:
        conn = get_db_connection() 
        cursor = conn.cursor()
        logging.debug(f"Fetching message for account ID: {account_id}")  # デバッグ用のログ
        cursor.execute("SELECT id, message FROM tweets WHERE is_deleted = 0 AND account_id = ? ORDER BY RANDOM() LIMIT 1", (account_id,))
        result = cursor.fetchone()
        if result:
            cursor.execute("UPDATE tweets SET is_deleted = 1 WHERE id = ?", (result[0],))
            conn.commit()
        conn.close()
        return result[1] if result else None
    except Exception as e:
        logging.error(f"Error fetching message from DB for account {account_id}: {e}")
        return None

@app.route('/')
def index():
    global reset_flag, interval, specific_times, interval_type, current_account_id, current_account
    conn = get_db_connection() 
    cursor = conn.cursor()

    # アカウント一覧を取得
    cursor.execute("SELECT id, name FROM accounts")
    accounts = cursor.fetchall()

    if current_account_id:
        load_settings(current_account_id)
        is_auto_posting = load_auto_post_status(current_account_id)  # 自動投稿の状態を取得して設定
    else:
        # 最初のアカウントをデフォルトとして選択
        if accounts:
            load_account(accounts[0][0])
            load_settings(accounts[0][0])
            is_auto_posting = load_auto_post_status(accounts[0][0])  

    # 全ての is_deleted フラグが1になった場合、全てのフラグを0にリセット
    cursor.execute("SELECT COUNT(*) FROM tweets WHERE is_deleted = 0 AND account_id = ?", (current_account_id,))
    count_not_deleted = cursor.fetchone()[0]
    if count_not_deleted == 0:
        cursor.execute("UPDATE tweets SET is_deleted = 0 WHERE account_id = ?", (current_account_id,))
        conn.commit()
        flash("メッセージリストがリセットされました")
        reset_flag = True  # リセットフラグを立てる

    cursor.execute("SELECT id, message, is_deleted FROM tweets WHERE account_id = ?", (current_account_id,))
    messages = cursor.fetchall()
    conn.close()
    
    current_setting = f"時間間隔: {interval}時間" if interval_type == 'interval' else f"時間指定: {', '.join(specific_times)}"
    
    return render_template('index.html', accounts=accounts, current_account_id=current_account_id, current_account=current_account, messages=messages, interval=interval, specific_times=specific_times, is_auto_posting=is_auto_posting, current_setting=current_setting, interval_type=interval_type)

@app.route('/select_account', methods=['POST'])
def select_account():
    global current_account_id, is_auto_posting
    account_id = request.form['account_id']
    current_account_id = account_id

    load_account(account_id)
    load_settings(account_id)

    # 自動投稿の状態を取得
    is_auto_posting = load_auto_post_status(account_id)

    update_auto_post_schedule(current_account_id)
    return redirect(url_for('index'))

@app.route('/register_account', methods=['POST'])
def register_account():
    try:
        name = request.form['name']
        consumer_api_key = request.form['consumer_api_key']
        consumer_api_secret = request.form['consumer_api_secret']
        bearer_token = request.form['bearer_token']
        access_token = request.form['access_token']
        access_token_secret = request.form['access_token_secret']

        conn = sqlite3.connect('tweets.db')
        cursor = conn.cursor()

        cursor.execute('''
        INSERT INTO accounts (name, consumer_api_key, consumer_api_secret, bearer_token, access_token, access_token_secret)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            name,
            consumer_api_key,
            consumer_api_secret,
            bearer_token,
            access_token,
            access_token_secret
        ))

        conn.commit()
        conn.close()
        flash("新しいアカウントが登録されました")
    except Exception as e:
        logging.error(f"Error registering account: {e}")
        flash("アカウント登録中にエラーが発生しました")
    return redirect(url_for('index'))

@app.route('/edit_account', methods=['POST'])
def edit_account():
    try:
        name = request.form['name']
        consumer_api_key = request.form['consumer_api_key']
        consumer_api_secret = request.form['consumer_api_secret']
        bearer_token = request.form['bearer_token']
        access_token = request.form['access_token']
        access_token_secret = request.form['access_token_secret']

        logging.debug(f"Edit Account - Name: {name}, Consumer API Key: {consumer_api_key}, Consumer API Secret: {consumer_api_secret}, Bearer Token: {bearer_token}, Access Token: {access_token}, Access Token Secret: {access_token_secret}")

        conn = sqlite3.connect('tweets.db')
        cursor = conn.cursor()

        cursor.execute("""
        UPDATE accounts
        SET name = ?, consumer_api_key = ?, consumer_api_secret = ?, bearer_token = ?, access_token = ?, access_token_secret = ?
        WHERE id = ?
        """, (name, consumer_api_key, consumer_api_secret, bearer_token, access_token, access_token_secret, current_account_id))

        logging.debug(f"SQL Update Query executed for Account ID: {current_account_id}")

        conn.commit()
        conn.close()
        flash("アカウント情報が更新されました")

        # 最新のアカウント情報を再読み込み 
        load_account(current_account_id)
    except Exception as e:
        logging.error(f"Error updating account: {e}")
        flash("アカウント情報の更新中にエラーが発生しました")
    return redirect(url_for('index'))

@app.route('/reset_status')
def reset_status():
    global reset_flag
    status = reset_flag
    reset_flag = False  # フラグをリセット
    return jsonify({"reset": status})

@app.route('/post', methods=['POST'])
def post():
    try:
        message = request.form['message']
        conn = sqlite3.connect('tweets.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO tweets (message, account_id) VALUES (?, ?)", (message, current_account_id))
        conn.commit()
        conn.close()
        flash("メッセージが追加されました")
    except Exception as e:
        logging.error(f"Error posting message: {e}")
        flash("メッセージ追加中にエラーが発生しました")
    return redirect(url_for('index'))

@app.route('/set_interval', methods=['POST'])
def set_interval():
    try:
        global interval, specific_times, interval_type
        interval_type = request.form['interval_type']

        conn = sqlite3.connect('tweets.db')
        cursor = conn.cursor()

        if interval_type == 'interval':
            interval = int(request.form['interval'])
            specific_times = []
            cursor.execute("DELETE FROM settings WHERE account_id = ?", (current_account_id,))
            cursor.execute("INSERT INTO settings (interval_type, interval, account_id) VALUES (?, ?, ?)", (interval_type, interval, current_account_id))
            flash(f"投稿間隔が{interval}時間に設定されました")
        else:
            specific_times = [time for time in request.form.getlist('specific_times') if time]
            interval = None
            cursor.execute("DELETE FROM settings WHERE account_id = ?", (current_account_id,))
            for time in specific_times:
                cursor.execute("INSERT INTO settings (interval_type, specific_time, account_id) VALUES (?, ?, ?)", (interval_type, time, current_account_id))
            flash(f"投稿時間が{', '.join(specific_times)}に設定されました")

        conn.commit()
        conn.close()

        # 自動投稿スケジュールを更新
        update_auto_post_schedule(current_account_id)
    except Exception as e:
        logging.error(f"Error setting interval: {e}")
        flash("投稿間隔の設定中にエラーが発生しました")
    return redirect(url_for('index'))

@app.route('/remove_specific_time', methods=['POST'])
def remove_specific_time():
    try:
        global specific_times
        time_to_remove = request.args.get('time')
        logging.debug(f"Removing specific time: {time_to_remove}")
        specific_times = [time for time in specific_times if time != time_to_remove]
        conn = sqlite3.connect('tweets.db')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM settings WHERE specific_time = ? AND account_id = ?", (time_to_remove, current_account_id))
        conn.commit()
        conn.close()
        flash(f"{time_to_remove}の投稿時間を削除しました")
    except Exception as e:
        logging.error(f"Error removing specific time: {e}")
        flash("投稿時間の削除中にエラーが発生しました")
    return redirect(url_for('index'))

@app.route('/start_auto_post')
def start_auto_post():
    try:
        global is_auto_posting, current_account  # current_accountをグローバル変数として宣言
        is_auto_posting = True

        # logging.debug(f"Starting auto post with credentials: Bearer Token - {current_account[4]}, Consumer Key - {current_account[2]}, Access Token - {current_account[5]}")

        # 現在のアカウント情報をログに出力
        logging.debug(f"Current account ID: {current_account_id}")
        logging.debug(f"Current account details: {current_account}")

        # 自動投稿スケジュールの更新
        update_auto_post_schedule(current_account_id)

        # auto_post_statusテーブルにデータを保存
        conn = sqlite3.connect('tweets.db')
        conn.execute('INSERT OR REPLACE INTO auto_post_status (account_id, status) VALUES (?, ?)', (current_account_id, True))
        conn.commit()
        conn.close()

        flash("自動投稿実行中")
    except Exception as e:
        logging.error(f"Error starting auto post: {e}")
        flash("自動投稿の開始中にエラーが発生しました")
    return redirect(url_for('index'))

@app.route('/stop_auto_post')
def stop_auto_post():
    try:
        global is_auto_posting, auto_post_threads
        is_auto_posting = False

        if current_account_id in auto_post_threads and auto_post_threads[current_account_id]:
            auto_post_threads[current_account_id].cancel()

        # auto_post_statusテーブルにデータを保存
        conn = sqlite3.connect('tweets.db')
        conn.execute('INSERT OR REPLACE INTO auto_post_status (account_id, status) VALUES (?, ?)', (current_account_id, False))
        conn.commit()
        conn.close()

        flash("自動投稿を停止しました")
    except Exception as e:
        logging.error(f"Error stopping auto post: {e}")
        flash("自動投稿の停止中にエラーが発生しました")
    return redirect(url_for('index'))

@app.route('/messages')
def get_messages():
    try:
        conn = sqlite3.connect('tweets.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id, message, is_deleted FROM tweets WHERE account_id = ?", (current_account_id,))
        messages = cursor.fetchall()
        conn.close()
        return jsonify(messages)
    except Exception as e:
        logging.error(f"Error fetching messages: {e}")
        return jsonify([])

@app.route('/delete/<int:id>', methods=['POST'])
def delete_message(id):
    try:
        conn = sqlite3.connect('tweets.db')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tweets WHERE id = ? AND account_id = ?", (id, current_account_id))
        conn.commit()
        conn.close()
        flash("メッセージが削除されました")
    except Exception as e:
        logging.error(f"Error deleting message: {e}")
        flash("メッセージの削除中にエラーが発生しました")
    return redirect(url_for('index'))

@app.route('/edit/<int:id>', methods=['POST'])
def edit_message(id):
    try:
        new_message = request.form['new_message']
        logging.debug(f"Editing message ID: {id}, New Message: {new_message}")
        conn = sqlite3.connect('tweets.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE tweets SET message = ? WHERE id = ? AND account_id = ?", (new_message, id, current_account_id))
        conn.commit()
        conn.close()
        flash("メッセージが編集されました")
    except Exception as e:
        logging.error(f"Error editing message: {e}")
        flash("メッセージの編集中にエラーが発生しました")
    return redirect(url_for('index'))

@app.route('/upload', methods=['POST'])
def upload():
    try:
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
            failed_messages = []
            with open(filename, newline='', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)
                conn = sqlite3.connect('tweets.db')
                cursor = conn.cursor()
                for row in reader:
                    if row:  # 空の行を無視
                        cursor.execute("SELECT COUNT(*) FROM tweets WHERE message = ? AND account_id = ?", (row[0], current_account_id))
                        count = cursor.fetchone()[0]
                        if count == 0:
                            cursor.execute("INSERT INTO tweets (message, account_id) VALUES (?, ?)", (row[0], current_account_id))
                        else:
                            failed_messages.append(row[0])
                conn.commit()
                conn.close()
            flash('CSVファイルのメッセージが追加されました')
            if failed_messages:
                flash(f"重複のため保存できなかったメッセージ: {', '.join(failed_messages)}")
        else:
            flash('無効なファイル形式です。CSVファイルをアップロードしてください')
    except Exception as e:
        logging.error(f"Error uploading CSV file: {e}")
        flash("CSVファイルのアップロード中にエラーが発生しました")
    return redirect(url_for('index'))

@app.route('/delete_all_messages', methods=['POST'])
def delete_all_messages():
    try:
        conn = sqlite3.connect('tweets.db')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tweets WHERE account_id = ?", (current_account_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "すべてのメッセージが削除されました"})
    except Exception as e:
        logging.error(f"Error deleting all messages: {e}")
        return jsonify({"success": False, "message": "すべてのメッセージの削除中にエラーが発生しました"})

# 全てのアカウントの自動投稿状態をチェックして実行する関数
def check_and_start_auto_post():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT account_id FROM auto_post_status WHERE status = 1')
    accounts = cursor.fetchall()
    conn.close()

    for account in accounts:
        account_id = account[0]
        load_account(account_id)
        load_settings(account_id)
        update_auto_post_schedule(account_id)

# アプリケーション起動時に全てのアカウントの自動投稿状態をチェック
check_and_start_auto_post()

if __name__ == '__main__':
    app.run(debug=True)
