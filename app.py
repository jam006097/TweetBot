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
LOG_FILENAME = 'app.log'
logging.basicConfig(filename=LOG_FILENAME, level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s')

# 定数の定義
INTERVAL_IN_SECONDS = 3600  # 1時間（秒単位）
CHECK_INTERVAL = 60         # 1分（秒単位）
MINIMUM_POST_INTERVAL_MINUTES = 1  #重複回避のための最小投稿間隔（分単位）
DEFAULT_INTERVAL_HOURS = 3  # デフォルトの投稿間隔（時間単位）

# グローバル変数の初期化
reset_flag = False
current_account_id = None

# アカウントごとのデータを管理する辞書
clients = {}            # アカウントごとのTwitterクライアント
account_settings = {}   # アカウントごとの設定
is_auto_posting = {}    # アカウントごとの自動投稿状態
auto_post_threads = {}  # アカウントごとのスレッド（スレッドと停止用のイベントを格納）
last_post_time = {}     # アカウントごとの最後の投稿時間

# SQLite3へのコネクション作成
def get_db_connection():
    conn = sqlite3.connect('tweets.db')
    conn.row_factory = sqlite3.Row
    return conn

# データベースの初期化
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # テーブル作成
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

# データベースから全アカウントIDを取得する関数
def get_all_account_ids():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM accounts')
    account_ids = [row['id'] for row in cursor.fetchall()]
    conn.close()
    return account_ids

# アカウント情報の読み込み
def load_account(account_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
    account = cursor.fetchone()
    logging.debug(f"Loaded Account: {account}")

    if account:
        try:
            client = tweepy.Client(
                bearer_token=account['bearer_token'],
                consumer_key=account['consumer_api_key'],
                consumer_secret=account['consumer_api_secret'],
                access_token=account['access_token'],
                access_token_secret=account['access_token_secret']
            )
            clients[account_id] = client
            logging.debug(f"Twitter client initialized successfully for account {account_id}")
        except Exception as e:
            logging.error(f"Error initializing Twitter client for account {account_id}: {e}")
    else:
        logging.error(f"Account not found for account_id {account_id}")

    conn.close()

# 設定の読み込み
def load_settings(account_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT interval_type, interval, specific_time FROM settings WHERE account_id = ?", (account_id,))
    settings = cursor.fetchall()
    if settings:
        interval_type = settings[0]['interval_type']
        if interval_type == 'interval':
            interval = settings[0]['interval']
            specific_times = []
        else:
            specific_times = [setting['specific_time'] for setting in settings if setting['specific_time']]
            interval = None
    else:
        interval_type = 'interval'
        interval = DEFAULT_INTERVAL_HOURS  # デフォルトの間隔時間を使用
        specific_times = []

    account_settings[account_id] = {
        'interval_type': interval_type,
        'interval': interval,
        'specific_times': specific_times
    }

    conn.close()

# 自動投稿状態の取得
def load_auto_post_status(account_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT status FROM auto_post_status WHERE account_id = ?', (account_id,))
    status_row = cursor.fetchone()
    conn.close()
    is_auto_posting[account_id] = bool(status_row['status']) if status_row else False

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
def job(account_id, stop_event):
    try:
        logging.debug(f"Job function started for account {account_id}")
        while not stop_event.is_set():
            settings = account_settings.get(account_id, {})
            interval_type = settings.get('interval_type', 'interval')
            interval = settings.get('interval', DEFAULT_INTERVAL_HOURS)
            specific_times = settings.get('specific_times', [])

            if interval_type == 'interval':
                logging.debug(f"Posting message in interval mode for account {account_id}")
                post_message(account_id)
                if stop_event.wait(interval * INTERVAL_IN_SECONDS):
                    break
            else:
                current_time = datetime.now().strftime("%H:%M")
                if current_time in specific_times:
                    logging.debug(f"Posting message at specific time: {current_time} for account {account_id}")
                    post_message(account_id)
                if stop_event.wait(CHECK_INTERVAL):
                    break
    except Exception as e:
        logging.error(f"Error in job for account {account_id}: {e}")

# メッセージの投稿関数
def post_message(account_id, message=None):
    try:
        logging.debug(f"Attempting to post message for account {account_id}")
        current_time = datetime.now()

        # 前回の投稿時間を確認
        if account_id in last_post_time:
            time_since_last_post = current_time - last_post_time[account_id]
            if time_since_last_post < timedelta(minutes=MINIMUM_POST_INTERVAL_MINUTES):
                logging.debug(f"Skipping post for account {account_id} due to recent activity")
                return

        if not message:
            message = get_message_from_db(account_id)

        if message:
            logging.debug(f"Message to post for account {account_id}: {message}")
            client = clients.get(account_id)
            if client:
                response = client.create_tweet(text=message)
                logging.debug(f"Tweet Response for account {account_id}: {response}")
                print(f"投稿完了: {message} for account {account_id} at {datetime.now()}")
                print(f"Tweet ID for account {account_id}: {response.data['id']}")
                last_post_time[account_id] = current_time
            else:
                logging.error(f"No Twitter client available for account {account_id}")
        else:
            logging.debug(f"No message to post for account {account_id}")
    except tweepy.TweepyException as e:
        logging.error(f"Error posting message for account {account_id}: {e}")
        print(f"エラーが発生しました: {e}")
        if "duplicate" in str(e):
            print(f"重複投稿エラーが発生しました。次のメッセージを試します。 for account {account_id}")
            next_message = get_message_from_db(account_id)
            if next_message:
                post_message(account_id, message=next_message)
    except Exception as e:
        logging.error(f"Unexpected error in post_message for account {account_id}: {e}")

# データベースからメッセージを取得
def get_message_from_db(account_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        logging.debug(f"Fetching message for account ID: {account_id}")
        cursor.execute("SELECT id, message FROM tweets WHERE is_deleted = 0 AND account_id = ? ORDER BY RANDOM() LIMIT 1", (account_id,))
        result = cursor.fetchone()
        if result:
            cursor.execute("UPDATE tweets SET is_deleted = 1 WHERE id = ?", (result['id'],))
            conn.commit()
        conn.close()
        return result['message'] if result else None
    except Exception as e:
        logging.error(f"Error fetching message from DB for account {account_id}: {e}")
        return None

# 自動投稿スケジュールの更新
def update_auto_post_schedule(account_id):
    global auto_post_threads

    logging.debug(f"Updating auto post schedule for account {account_id}")

    # 現在のスレッドが存在し、動作中であれば停止
    if account_id in auto_post_threads:
        stop_event = auto_post_threads[account_id]['event']
        stop_event.set()  # スレッドを停止させる
        thread = auto_post_threads[account_id]['thread']
        thread.join()     # スレッドが終了するのを待つ
        logging.debug(f"Stopped existing thread for account {account_id}")

    # 新しいスレッドを開始
    stop_event = threading.Event()
    thread = threading.Thread(target=job, args=(account_id, stop_event))
    thread.start()
    auto_post_threads[account_id] = {'thread': thread, 'event': stop_event}
    logging.debug(f"Started new thread for account {account_id}")

# Flaskルート（省略せずに完全に記載します）

@app.route('/')
def index():
    global current_account_id, reset_flag
    conn = get_db_connection()
    cursor = conn.cursor()

    # アカウント一覧を取得
    cursor.execute("SELECT id, name FROM accounts")
    accounts = cursor.fetchall()

    if current_account_id:
        load_settings(current_account_id)
        load_auto_post_status(current_account_id)
        is_posting = is_auto_posting.get(current_account_id, False)
        settings = account_settings.get(current_account_id, {})
        interval = settings.get('interval')
        specific_times = settings.get('specific_times')
        interval_type = settings.get('interval_type')
    else:
        # 最初のアカウントをデフォルトとして選択
        if accounts:
            current_account_id = accounts[0]['id']
            load_account(current_account_id)
            load_settings(current_account_id)
            load_auto_post_status(current_account_id)
            is_posting = is_auto_posting.get(current_account_id, False)
            settings = account_settings.get(current_account_id, {})
            interval = settings.get('interval')
            specific_times = settings.get('specific_times')
            interval_type = settings.get('interval_type')
        else:
            is_posting = False
            interval = None
            specific_times = []
            interval_type = 'interval'

    # 現在のアカウント情報を取得
    cursor.execute("SELECT * FROM accounts WHERE id = ?", (current_account_id,))
    current_account = cursor.fetchone()

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

    return render_template(
        'index.html',
        accounts=accounts,
        current_account_id=current_account_id,
        current_account=current_account,
        messages=messages,
        interval=interval,
        specific_times=specific_times,
        is_auto_posting=is_posting,
        current_setting=current_setting,
        interval_type=interval_type
    )

@app.route('/select_account', methods=['POST'])
def select_account():
    global current_account_id
    account_id = int(request.form['account_id'])
    current_account_id = account_id

    load_account(account_id)
    load_settings(account_id)
    load_auto_post_status(account_id)

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

        conn = get_db_connection()
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

        conn = get_db_connection()
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
        conn = get_db_connection()
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
        interval_type = request.form['interval_type']

        conn = get_db_connection()
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
            for time_value in specific_times:
                cursor.execute("INSERT INTO settings (interval_type, specific_time, account_id) VALUES (?, ?, ?)", (interval_type, time_value, current_account_id))
            flash(f"投稿時間が{', '.join(specific_times)}に設定されました")

        conn.commit()
        conn.close()

        # アカウント設定を更新
        load_settings(current_account_id)

        # 自動投稿スケジュールを更新
        update_auto_post_schedule(current_account_id)
    except Exception as e:
        logging.error(f"Error setting interval: {e}")
        flash("投稿間隔の設定中にエラーが発生しました")
    return redirect(url_for('index'))

@app.route('/start_auto_post')
def start_auto_post():
    try:
        is_auto_posting[current_account_id] = True

        # 自動投稿スケジュールの更新
        update_auto_post_schedule(current_account_id)

        # auto_post_statusテーブルにデータを保存
        conn = get_db_connection()
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
        is_auto_posting[current_account_id] = False

        # スレッドを停止
        if current_account_id in auto_post_threads:
            stop_event = auto_post_threads[current_account_id]['event']
            stop_event.set()
            thread = auto_post_threads[current_account_id]['thread']
            thread.join()
            logging.debug(f"Stopped thread for account {current_account_id}")
            del auto_post_threads[current_account_id]

        # auto_post_statusテーブルにデータを保存
        conn = get_db_connection()
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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, message, is_deleted FROM tweets WHERE account_id = ?", (current_account_id,))
        messages = cursor.fetchall()
        conn.close()
        return jsonify([dict(msg) for msg in messages])
    except Exception as e:
        logging.error(f"Error fetching messages: {e}")
        return jsonify([])

@app.route('/delete/<int:id>', methods=['POST'])
def delete_message(id):
    try:
        conn = get_db_connection()
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
        conn = get_db_connection()
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
                conn = get_db_connection()
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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tweets WHERE account_id = ?", (current_account_id,))
        conn.commit()
        conn.close()
        flash("すべてのメッセージが削除されました")
    except Exception as e:
        logging.error(f"Error deleting all messages: {e}")
        flash("すべてのメッセージの削除中にエラーが発生しました")
    return redirect(url_for('index'))

# アプリケーション起動時に全てのアカウントの自動投稿状態をチェック
def check_and_start_auto_post():
    account_ids = get_all_account_ids()
    for account_id in account_ids:
        load_account(account_id)
        load_settings(account_id)
        load_auto_post_status(account_id)
        if is_auto_posting.get(account_id, False):
            update_auto_post_schedule(account_id)

check_and_start_auto_post()

if __name__ == '__main__':
    app.run(debug=True)
